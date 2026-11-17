"""Kiểm nguyên tử bằng quy tắc, không xác nhận tính đúng ngữ nghĩa của đáp án.

Usage: python check_reference_answers.py bo_110.csv folder [folder ...] out.csv
Chỉ thư viện chuẩn; PDF dùng pypdf nếu đã có. Không OCR hoặc gọi mạng/LLM.
"""
import argparse
import ast
import csv
import re
import unicodedata
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
REF = re.compile(r'(?<!\d)(\d{1,4})\s*[/_\-]\s*((?:19|20)\d{2})\s*[/_\-]\s*TT(?:\s*[-_]\s*BGD[ĐD]T)?\b', re.I)
OLD_REF = re.compile(r'\bTT\s*(\d{1,4})\s*[-_/]\s*((?:19|20)\d{2})', re.I)
PREFIX_REF = re.compile(r'\b(?:TT|Thông\s+tư)(?:\s+số)?\s*(\d{1,4})\s*[/_\-]\s*((?:19|20)\d{2})', re.I)
NUMBER = re.compile(r'(?<![\w])\d+(?:[.,]\d+)?(?![\w])', re.U)
DATE = re.compile(r'(?<!\d)(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{4})(?!\d)|ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})', re.I)
ARTICLE = re.compile(r'\bĐiều\s+(\d+)\b', re.I)
CLAUSE = re.compile(r'\bkhoản\s+(\d+)\b', re.I)
HEADING = re.compile(r'^\s*Điều\s+(\d+)\s*[.:]', re.I | re.M)


def normalize(text):
    return unicodedata.normalize('NFC', text).replace('\xa0', ' ')


def read_text(path):
    path = Path(path)
    try:
        if path.suffix.lower() == '.txt':
            return normalize(path.read_text(encoding='utf-8-sig')), ''
        if path.suffix.lower() == '.docx':
            with zipfile.ZipFile(path) as z:
                doc = ET.fromstring(z.read('word/document.xml'))
                text = '\n'.join(''.join(t.text or '' for t in p.iter(W + 't')) for p in doc.iter(W + 'p'))
                return normalize(text), ''
        if path.suffix.lower() == '.pdf':
            try:
                from pypdf import PdfReader
            except ImportError:
                return '', 'không có pypdf trong venv'
            text = '\n'.join(p.extract_text() or '' for p in PdfReader(str(path)).pages)
            return normalize(text), '' if text.strip() else 'PDF không có chữ'
    except Exception as exc:
        return '', f'{type(exc).__name__}: {exc}'
    return '', 'định dạng không hỗ trợ'


def references(text):
    return list(dict.fromkeys((int(m[1]), int(m[2])) for rx in (REF, OLD_REF, PREFIX_REF) for m in rx.finditer(normalize(text))))


def num(s):
    return Decimal(s.replace(',', '.')).normalize()


def numbers(text):
    return {num(m[0]) for m in NUMBER.finditer(text)}


def dates(text):
    return {(int(m[1] or m[4]), int(m[2] or m[5]), int(m[3] or m[6])) for m in DATE.finditer(text)}


def atoms(text):
    text = normalize(text)
    result = []
    masked = text
    result += [('reference', key, f'{key[0]:02}/{key[1]}/TT-BGDĐT') for key in references(text)]
    for m in DATE.finditer(text):
        d, mo, y = (int(m[1] or m[4]), int(m[2] or m[5]), int(m[3] or m[6]))
        result.append(('date', (d, mo, y), f'{d:02}/{mo:02}/{y}'))
    for rx, kind in ((ARTICLE, 'article'), (CLAUSE, 'clause')):
        # Includes lists "Khoản 1, 2 và 3" / "Điều 2 và Điều 5".
        for m in rx.finditer(text):
            result.append((kind, int(m[1]), f'{"Điều" if kind == "article" else "khoản"} {int(m[1])}'))
            tail = re.match(r'((?:\s*(?:,|và|hoặc)\s*\d+)+)', text[m.end():], re.I)
            if tail:
                for n in re.findall(r'\d+', tail[0]):
                    result.append((kind, int(n), f'{"Điều" if kind == "article" else "khoản"} {int(n)}'))
    for rx in (DATE, REF, OLD_REF, PREFIX_REF, ARTICLE, CLAUSE):
        masked = rx.sub(lambda m: ' ' * len(m[0]), masked)
    result += [('number', num(m[0]), m[0]) for m in NUMBER.finditer(masked)]
    return list(dict.fromkeys(result))


class Corpus:
    def __init__(self, folders):
        self.docs = []
        paths = sorted({p.resolve() for folder in folders for p in Path(folder).rglob('*') if p.suffix.lower() in {'.txt', '.docx', '.pdf'}})
        for path in paths:
            text, error = read_text(path)
            keys = references(path.name)
            # Some signed files have only the leading serial in their filename.
            if not keys:
                keys = references(text[:3000])[:1]
            self.docs.append({'path': path, 'text': text, 'error': error, 'keys': keys})

    def resolve(self, key):
        candidates = [d for d in self.docs if key in d['keys']]
        readable = [d for d in candidates if len(re.findall(r'[^\W\d_]', d['text'])) >= 100 and HEADING.search(d['text'])]
        if not readable:
            return None
        # TXT preferred over DOCX/PDF; use one version per exact serial/year.
        return min(readable, key=lambda d: ({'.txt': 0, '.docx': 1, '.pdf': 2}[d['path'].suffix.lower()], str(d['path'])))


def article_blocks(text):
    matches = list(HEADING.finditer(text))
    return [(int(m[1]), text[m.start():matches[i + 1].start() if i + 1 < len(matches) else len(text)]) for i, m in enumerate(matches)]


def clause_numbers(text):
    return {int(m[1]) for m in CLAUSE.finditer(text)} | {int(m[1]) for m in re.finditer(r'^\s*(\d+)\s*[.)]\s+', text, re.M)}


def arithmetic(target, text):
    """Conservative bounded witness: up to 3 pair products from one paragraph window.

    Only quantities in prose, excluding article/clause labels, dates and serials.
    All factor occurrences are consumed once. No invented numeric constants.
    """
    if target != target.to_integral() or not 0 < target <= 10000:
        return ''
    text = re.sub(r'^\s*\d+\s*[.)]\s+', '', text, flags=re.M)
    for rx in (DATE, REF, OLD_REF, PREFIX_REF, ARTICLE, CLAUSE):
        text = rx.sub(' ', text)
    vals = [int(v) for m in NUMBER.finditer(text) if (v := num(m[0])) == v.to_integral() and 0 < v <= 1000]
    vals = vals[:32]
    target = int(target)
    # Addition/subtraction of two factual quantities.
    for i, a in enumerate(vals):
        for j in range(i + 1, len(vals)):
            b = vals[j]
            for value, expr in ((a+b, f'{a}+{b}'), (a-b, f'{a}-{b}'), (b-a, f'{b}-{a}'), (a*b, f'{a}x{b}')):
                if value == target:
                    return f'{expr}={target}'
    pairs = [(vals[i] * vals[j], (1 << i) | (1 << j), f'{vals[i]}x{vals[j]}') for i in range(len(vals)) for j in range(i+1, len(vals)) if vals[i] * vals[j] <= target]
    by_value = {}
    for item in pairs:
        by_value.setdefault(item[0], []).append(item)
    for a, mask_a, expr_a in pairs:
        for b, mask_b, expr_b in pairs:
            if mask_a & mask_b:
                continue
            if a + b == target:
                return f'{expr_a}+{expr_b}={target}'
            for c, mask_c, expr_c in by_value.get(target-a-b, []):
                if not (mask_a | mask_b) & mask_c:
                    return f'{expr_a}+{expr_b}+{expr_c}={target}'
    return ''


def explicit_expressions(text):
    rx = re.compile(r'(?<![\w/])(?:[\[(]*\s*\d+(?:[.,]\d+)?\s*[\])]*)(?:\s*[+*/x×−–-]\s*[\[(]*\s*\d+(?:[.,]\d+)?\s*[\])]*)+')
    for ref in (DATE, REF, OLD_REF, PREFIX_REF):
        text = ref.sub(lambda m: ' ' * len(m[0]), text)
    for m in rx.finditer(text):
        original = m[0].strip()
        # A fraction or day/month alone is not an arithmetic answer.
        if not re.search(r'[+*x×−–-]', original):
            continue
        # Only a terminal RHS is an asserted result; intermediate equalities may
        # be followed by another expression (a*b = c+d = result).
        tail = re.match(r'\s*=\s*(\d+(?:[.,]\d+)?)(?![\d.,])', text[m.end():])
        if tail and not re.match(r'\s*[+*/x×−–-]', text[m.end()+tail.end():]):
            original += '=' + tail[1]
        yield original


def verify_expression(expr, available, derived=None):
    left, _, right = expr.partition('=')
    clean = left.translate(str.maketrans({'x': '*', '×': '*', '−': '-', '–': '-', ',': '.', '[': '(', ']': ')'}))
    values = set()
    try:
        tree = ast.parse(clean.strip(), mode='eval')
        def calc(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                value = Decimal(str(node.value))
                if value not in available:
                    raise ValueError('factor absent')
                return value
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                a, b = calc(node.left), calc(node.right)
                value = a+b if isinstance(node.op, ast.Add) else a-b if isinstance(node.op, ast.Sub) else a*b if isinstance(node.op, ast.Mult) else a/b
                values.add(value)
                return value
            raise ValueError('unsupported')
        value = calc(tree.body)
        ok = not right or value == num(right.strip())
        if ok and derived is not None:
            derived.update(values)
        return ok, f'{left.strip()}={value.normalize():f}'
    except (ValueError, SyntaxError, ArithmeticError):
        return False, ''


def check_row(row, corpus):
    answer = normalize(row.get('dap_an_tham_khao', ''))
    # Answer parenthetical citations are sources; repealed acts mentioned in
    # prose remain atoms to check in that source, not required extra documents.
    citations = [k for part in re.findall(r'\([^()]*\)', answer) for k in references(part)]
    keys = list(dict.fromkeys(references(row.get('van_ban_nguon', '')) + citations))
    if not keys:
        keys = references(row.get('cau_hoi', '')) or references(answer)
    if not keys:
        return 'khong_kiem_duoc', 'không xác định số hiệu nguồn', ''
    docs = [corpus.resolve(key) for key in keys]
    absent = [f'{n:02}/{y}: thiếu văn bản có chữ' for (n, y), d in zip(keys, docs) if d is None]
    if absent:
        return 'khong_kiem_duoc', '; '.join(absent), ''
    text = '\n'.join(d['text'] for d in docs)
    wanted = atoms(answer)
    if not wanted:
        return 'khong_kiem_duoc', 'đáp án không có nguyên tử số/ngày/Điều/khoản', ''
    available = numbers(text)
    # Local source identity may come from the filename if extraction lost the
    # serial in its header. This is a filename match, not header verification.
    source_refs = set(references(text)) | {key for d in docs for key in d['keys']}
    article_ids = {n for n, _ in article_blocks(text)}
    clauses = clause_numbers(text)
    found_dates = dates(text)
    missing, expressions, derived = [], [], set()
    # Scenario quantities from the question are allowed as arithmetic inputs,
    # but cannot make a plain unmatched assertion pass without a witness.
    scenario = numbers(normalize(row.get('cau_hoi', '')))
    explicit = list(explicit_expressions(answer))
    for expr in explicit:
        ok, proof = verify_expression(expr, available | scenario | derived, derived)
        if ok:
            expressions.append(proof)
        else:
            missing.append('biểu thức không được xác minh: ' + expr)
    # Compute witnesses only inside cited articles, then within at most 6 adjacent paragraphs.
    cited = {v for kind, v, _ in wanted if kind == 'article'}
    blocks = [b for n, b in article_blocks(text) if n in cited]
    windows = []
    for block in blocks:
        lines = [p for p in block.splitlines() if p.strip()]
        windows += ['\n'.join(lines[i:i+6]) for i in range(len(lines))]
    for kind, value, label in wanted:
        exists = value in (available if kind == 'number' else article_ids if kind == 'article' else clauses if kind == 'clause' else source_refs if kind == 'reference' else found_dates)
        if exists:
            continue
        if kind == 'number':
            if value in derived:
                continue
            proof = next((p for window in windows if (p := arithmetic(value, window))), '')
            if proof:
                expressions.append(proof)
                continue
            # Explicit arithmetic result can be absent from source.
            if any(num(p.rsplit('=', 1)[1]) == value for p in expressions):
                continue
            if explicit and expressions and value in scenario:
                continue
        missing.append(label)
    return ('khong_khop' if missing else 'tinh_toan' if expressions else 'khop', '; '.join(dict.fromkeys(missing)), '; '.join(dict.fromkeys(expressions)))


def run(input_csv, folders, output_csv):
    corpus = Corpus(folders)
    with Path(input_csv).open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    results = [dict(zip(('id', 'nhan', 'nguyen_tu_thieu', 'bieu_thuc'), (row['id'], *check_row(row, corpus)))) for row in rows]
    output = Path(output_csv)
    for path, data in ((output, results), (output.with_name('CAN_NGUOI_KIEM.csv'), [r for r in results if r['nhan'] == 'khong_khop'])):
        with path.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'nhan', 'nguyen_tu_thieu', 'bieu_thuc'])
            writer.writeheader()
            writer.writerows(data)
    print(dict(Counter(r['nhan'] for r in results)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_csv')
    parser.add_argument('folders', nargs='+')
    parser.add_argument('output_csv')
    args = parser.parse_args()
    run(args.input_csv, args.folders, args.output_csv)
