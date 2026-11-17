"""Small deterministic tests; retain all fixtures, never delete files.

Run with the requested isolated Python directly, no third party test runner.
"""
import builtins
import csv
import importlib.util
import unittest
import uuid
import zipfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('checker', Path(__file__).resolve().parents[1] / 'scripts' / 'check_reference_answers.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class CheckAnswersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).parent / '_test_runs' / uuid.uuid4().hex
        cls.root.mkdir(parents=True)
        cls.text = ('Số: 34/2026/TT-BGDĐT\nHà Nội, ngày 19 tháng 4 năm 2026\n'
                    'Điều 1. Quy định đào tạo\n1. Thời hạn tối đa 05 năm, mức hỗ trợ 5,0 phần trăm.\n'
                    '2. Hệ số 3, 6 và 8 cho các nhóm đào tạo; số người lần lượt 5, 3 và 2.\n'
                    'Điều 2. Tổ chức thực hiện\n1. Các cơ sở giáo dục thực hiện đầy đủ quy định.\n')
        (cls.root / '34_2026_TT-BGDDT.txt').write_text(cls.text, encoding='utf-8')
        (cls.root / '59_2026_TT-BGDDT.txt').write_text('Người ký: Cổng thông tin chính phủ', encoding='utf-8')
        cls.corpus = c.Corpus([cls.root])

    def row(self, answer, question='', source='34/2026/TT-BGDĐT'):
        return c.check_row({'dap_an_tham_khao': answer, 'cau_hoi': question, 'van_ban_nguon': source}, self.corpus)

    def test_normalized_numbers(self):
        self.assertEqual(self.row('Thời hạn 5 năm, mức 5.0 phần trăm, Điều 1 khoản 2.')[0], 'khop')

    def test_normalized_date(self):
        self.assertEqual(self.row('Ban hành ngày 19/04/2026, Điều 1.')[0], 'khop')
        self.assertEqual(c.references('ngày 19/04/2026'), [])

    def test_missing_date(self):
        label, missing, _ = self.row('Ngày 20/04/2026, Điều 1.')
        self.assertEqual(label, 'khong_khop')
        self.assertIn('20/04/2026', missing)

    def test_missing_article(self):
        self.assertEqual(self.row('Điều 99 khoản 1.')[0], 'khong_khop')

    def test_missing_clause_list(self):
        label, missing, _ = self.row('Điều 1 Khoản 1, 2 và 99.')
        self.assertEqual(label, 'khong_khop')
        self.assertIn('khoản 99', missing)

    def test_missing_source(self):
        self.assertEqual(self.row('Điều 1.', source='17/2026/TT-BGDĐT')[0], 'khong_kiem_duoc')

    def test_signature_is_not_source(self):
        self.assertEqual(self.row('Điều 1.', source='59/2026/TT-BGDĐT')[0], 'khong_kiem_duoc')

    def test_no_source(self):
        self.assertEqual(self.row('05 năm.', source='')[0], 'khong_kiem_duoc')

    def test_49_implicit(self):
        label, missing, proof = self.row('49 nghiên cứu sinh (34_2026_TT-BGDĐT, Điều 1 khoản 2).')
        self.assertEqual((label, missing), ('tinh_toan', ''))
        self.assertTrue(proof.endswith('=49'), proof)

    def test_49_explicit(self):
        label, missing, proof = self.row('5 x 3 + 3 x 6 + 2 x 8 = 15 + 18 + 16 = 49 nghiên cứu sinh (34_2026_TT-BGDĐT, Điều 1 khoản 2).')
        self.assertEqual((label, missing), ('tinh_toan', ''))
        self.assertIn('5 x 3 + 3 x 6 + 2 x 8=49', proof)

    def test_wrong_arithmetic_result(self):
        self.assertEqual(self.row('5 x 3 + 3 x 6 + 2 x 8 = 48 (34_2026_TT-BGDĐT, Điều 1).')[0], 'khong_khop')

    def test_day_month_is_not_arithmetic(self):
        self.assertEqual(list(c.explicit_expressions('trước 31/8 và ngày 31/12 hằng năm')), [])
        self.assertEqual(list(c.explicit_expressions('1/3 thời hạn (1/3 của 06 tháng)')), [])

    def test_parentheses_and_division(self):
        ok, proof = c.verify_expression('[(30 - 27)/7,50] x 0,75=0,30', {Decimal(s) for s in ('30', '27', '7.5', '.75')})
        self.assertTrue(ok, proof)

    def test_citation_preferred_to_repealed_question(self):
        self.assertEqual(self.row('Điều 1 (34_2026_TT-BGDĐT).', question='Thay thế TT 12/2017?', source='')[0], 'khop')

    def test_filename_identifies_source_without_header(self):
        folder = self.root / 'without_header'
        folder.mkdir(exist_ok=True)
        (folder / '17_2026_TT-BGDDT.txt').write_text(self.text.replace('Số: 34/2026/TT-BGDĐT', ''), encoding='utf-8')
        self.assertEqual(c.check_row({'dap_an_tham_khao': 'Điều 1 (17_2026_TT-BGDĐT).'}, c.Corpus([folder]))[0], 'khop')

    def test_no_arbitrary_unbounded_sum(self):
        label, missing, _ = self.row('9999 năm (34_2026_TT-BGDĐT, Điều 1).')
        self.assertEqual(label, 'khong_khop')
        self.assertIn('9999', missing)

    def test_repealed_reference_atom(self):
        label, missing, _ = self.row('Bãi bỏ Thông tư 15/2018/TT-BGDĐT (34_2026_TT-BGDĐT, Điều 1).', source='')
        self.assertEqual(label, 'khong_khop')
        self.assertIn('15/2018', missing)

    def test_docx_zipfile(self):
        path = self.root / 'fixture.docx'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Điều 1.</w:t></w:r></w:p><w:p><w:r><w:t>05 năm</w:t></w:r></w:p></w:body></w:document>')
        self.assertEqual(c.read_text(path), ('Điều 1.\n05 năm', ''))

    def test_pdf_without_pypdf(self):
        importer = builtins.__import__
        def no_pypdf(name, *args, **kwargs):
            if name == 'pypdf':
                raise ImportError('test')
            return importer(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=no_pypdf):
            text, error = c.read_text(self.root / 'scan.pdf')
        self.assertEqual(text, '')
        self.assertIn('không có pypdf', error)

    def test_expression_parser_rejects_code(self):
        self.assertEqual(c.verify_expression('__import__("os").system("echo bad")', {Decimal(1)})[0], False)

    def test_csv_outputs(self):
        source = self.root / 'input.csv'
        with source.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'van_ban_nguon', 'dap_an_tham_khao'])
            writer.writeheader()
            writer.writerows([{'id': 'ok', 'van_ban_nguon': '34/2026/TT-BGDĐT', 'dap_an_tham_khao': 'Điều 1.'},
                             {'id': 'bad', 'van_ban_nguon': '34/2026/TT-BGDĐT', 'dap_an_tham_khao': 'Điều 99.'}])
        c.run(source, [self.root], self.root / 'out.csv')
        with (self.root / 'CAN_NGUOI_KIEM.csv').open(encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([r['id'] for r in rows], ['bad'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
