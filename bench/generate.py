"""Generate deterministic synthetic corpora and their gold labels."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from seed import SEED, rows

CONFLICT_COUNTS = {"n5": 3, "n30": 10, "n100": 25}
SIZES = {"n5": 5, "n30": 30, "n100": 100}
FILLER = ("Quy trình được rà soát trong đợt phát hành định kỳ. Nhóm phụ trách ghi nhận thay đổi, "
          "kiểm tra quyền truy cập và lưu biên bản để các bộ phận có thể tra cứu thống nhất. "
          "Mọi ngoại lệ cần nêu rõ phạm vi áp dụng, người chịu trách nhiệm và ngày đánh giá tiếp theo. ")

def sentence(f):
    v, u = f["value"], f["unit"]
    if f["attribute"] == "thời hạn mật khẩu":
        return f"Mật khẩu phải được đổi sau {v} {u}."
    if f["attribute"] == "thời hạn lưu" and f["subject"] == "nhật ký truy cập":
        return f"Nhật ký truy cập được lưu trong {v} {u}."
    if f["attribute"] == "xác thực hai yếu tố":
        return f"{f['subject'].capitalize()} {v} xác thực hai yếu tố ({f['condition']})."
    if f["attribute"].startswith("quyền "):
        return f"{f['subject'].capitalize()} {v} ({f['attribute']}; {f['condition']})."
    if f["attribute"] == "thời hạn lưu":
        return f"{f['subject'].capitalize()} được lưu {v} {u} ({f['condition']})."
    return f"{f['subject'].capitalize()} — {f['attribute']}: {v}{(' ' + u) if u else ''} ({f['condition']})."

def variant(f, idx):
    base = sentence(f)
    alternatives = [base, f"Theo chính sách, {base[0].lower() + base[1:]}",
                    f"Phạm vi {f['condition']}: {base}"]
    if f["fact_id"] == "bak01": alternatives[idx % 3] = "Bản sao lưu cơ sở dữ liệu chạy mỗi 1 ngày."
    if f["fact_id"] == "onb05": alternatives[idx % 3] = "Mỗi phiên đào tạo kéo dài 30 phút."
    if f["fact_id"] == "bil07": alternatives[idx % 3] = "Có thể tải hóa đơn trong 365 ngày kể từ khi phát hành."
    return alternatives[idx % len(alternatives)]

def normalize_fact(f):
    result = dict(f)
    if (f["value"], f["unit"]) in (("24", "giờ"), ("1", "ngày")):
        result["normalised_value_seconds_or_number"] = 86400
    elif (f["value"], f["unit"]) in (("0.5", "giờ"), ("30", "phút")):
        result["normalised_value_seconds_or_number"] = 1800
    elif (f["value"], f["unit"]) in (("1", "năm"), ("365", "ngày")):
        result["normalised_value_seconds_or_number"] = 31536000
    elif f["unit"] == "giờ": result["normalised_value_seconds_or_number"] = float(f["value"]) * 3600
    elif f["unit"] == "phút": result["normalised_value_seconds_or_number"] = float(f["value"]) * 60
    else: result["normalised_value_seconds_or_number"] = float(f["value"]) if f["value"].replace(".", "", 1).isdigit() else f["value"]
    return result

def build(output_dir):
    root = Path(output_dir)
    if root.exists(): shutil.rmtree(root)
    root.mkdir(parents=True)
    allfacts = rows()
    for size_name, n_docs in SIZES.items():
        count = 20 if size_name == "n5" else 60
        corpusfacts = allfacts[:count]
        facts_dir = root / size_name / "docs"
        facts_dir.mkdir(parents=True)
        placements = {}
        docs = {}
        # Distribute known facts evenly, keeping the same fact IDs across corpus sizes.
        for i in range(n_docs):
            rel = f"{size_name}/docs/doc_{i+1:03}.md"
            assigned = [f for j, f in enumerate(corpusfacts) if j % n_docs == i]
            if size_name == "n100" and i >= count: assigned = [allfacts[i % len(allfacts)]]
            lines = [f"# Document {i+1:03}", ""]
            last_heading = None
            for k, f in enumerate(assigned):
                heading = f"{f['doc_kind'].title()} requirements"
                if heading != last_heading:
                    lines += [f"## {heading}", ""]
                    last_heading = heading
                s = variant(f, i + k)
                lines += [s, "", FILLER]
                placements.setdefault(f["fact_id"], {"doc": rel, "heading": heading, "sentence": s})
            if not assigned:
                lines += ["## Operational notes", "", FILLER * 5]
            # Long surrounding prose ensures facts occur across ordinary 1200-character chunks.
            while len("\n".join(lines)) < 1450:
                lines += [FILLER, ""]
            content = "\n".join(lines).strip() + "\n"
            (root / rel).write_text(content, encoding="utf-8")
            docs[rel] = content
        # Inject explicit conflicting statements into the final documents.
        conflicts = []
        chosen = ["sec01", "sec02", "sec05"] if size_name == "n5" else ["log01", "sec01", "bak02", "api02", "bak03", "log02", "bil01", "sec05", "onb03", "api03", "log03", "bak04", "bil02", "sec06", "onb04", "api07", "bil08", "bak06", "log07", "sec07", "bak07", "api10", "onb09", "bil05", "log08"][:CONFLICT_COUNTS[size_name]]
        for ix, fid in enumerate(chosen):
            base = next(f for f in corpusfacts if f["fact_id"] == fid)
            alternate = dict(base, fact_id=f"cx_{size_name}_{ix+1:02}", value=str(int(base["value"]) // 2 if base["value"].isdigit() else "180"), unit=base["unit"])
            # Contradiction has identical subject, attribute, condition and a distinct value.
            alt_sentence = sentence(alternate)
            rel = f"{size_name}/docs/doc_{(n_docs-1-ix) % n_docs:03}.md"
            heading = "Conflicting revision"
            append = f"\n## {heading}\n\n{alt_sentence}\n"
            (root / rel).write_text((root / rel).read_text(encoding="utf-8") + append, encoding="utf-8")
            docs[rel] += append
            placements[alternate["fact_id"]] = {"doc": rel, "heading": heading, "sentence": alt_sentence}
            conflicts.append({"fact_a": fid, "fact_b": alternate["fact_id"], "doc_a": placements[fid]["doc"], "heading_a": placements[fid]["heading"], "doc_b": rel, "heading_b": heading, "reason": f"Same subject, attribute and scope; {base['value']} {base['unit']} conflicts with {alternate['value']} {alternate['unit']} after unit normalization."})
        # Duplicate a fact verbatim in a second document; duplicates must not count as contradictions.
        duplicates = []
        for ix, fid in enumerate(["api01", "bak01", "bil06"]):
            if fid not in placements: continue
            target = f"{size_name}/docs/doc_{(n_docs-2-ix) % n_docs:03}.md"
            heading = "Repeated policy"
            s = placements[fid]["sentence"]
            append = f"\n## {heading}\n\n{s}\n"
            (root / target).write_text((root / target).read_text(encoding="utf-8") + append, encoding="utf-8")
            docs[target] += append
            duplicates.append({"fact_id": fid, "doc_a": placements[fid]["doc"], "heading_a": placements[fid]["heading"], "doc_b": target, "heading_b": heading})
        # Decoys are same-value/different-attribute or same fact across different scopes.
        decoys = []
        for i in range(45):
            a, b = corpusfacts[i % len(corpusfacts)], corpusfacts[(i + 17) % len(corpusfacts)]
            if a["fact_id"] == b["fact_id"]: continue
            decoys.append({"fact_a": a["fact_id"], "fact_b": b["fact_id"], "doc_a": placements[a["fact_id"]]["doc"], "heading_a": placements[a["fact_id"]]["heading"], "doc_b": placements[b["fact_id"]]["doc"], "heading_b": placements[b["fact_id"]]["heading"], "reason": "Consistent decoy: different attribute or scope; apparent value overlap is not a contradiction."})
        truth_facts = {f["fact_id"]: {**normalize_fact(f), **placements[f["fact_id"]]} for f in corpusfacts if f["fact_id"] in placements}
        for conflict in conflicts:
            # Include alternate facts in truth for exact quote matching.
            af = next((x for x in placements if x.startswith(f"cx_{size_name}_") and placements[x]["doc"] == conflict["doc_b"]), None)
            if af:
                original = next(f for f in corpusfacts if f["fact_id"] == conflict["fact_a"])
                truth_facts[af] = {**normalize_fact(dict(original, fact_id=af, value=conflict["reason"].split("conflicts with ")[1].split(" ")[0])), **placements[af]}
        truth = {"size": size_name, "facts": truth_facts, "contradictions": conflicts, "decoys": decoys, "duplicates": duplicates, "document_texts": docs}
        (root / size_name / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    questions = make_questions(allfacts)
    (root / "questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sanity = {"documents": [
        {"path": "docs/DEMO_QUICKSTART.md", "questions": [
            {"question": "Which Python version does the Windows quickstart specify?", "answer": "Python 3.12", "quote": "On Windows with Python 3.12, run this once from the repository root:"},
            {"question": "Which provider does the fake demo use?", "answer": "PROVIDER=fake", "quote": "`PROVIDER=fake` and `REVIEW_ENGINE=fake` mean answers/findings are deterministic fake-provider demo output, not real model output."},
            {"question": "Is vector indexing enabled in the demo?", "answer": "No; vector indexing is disabled.", "quote": "Vector indexing is disabled and retrieval uses the lexical backend."},
            {"question": "What API returns the complete schema?", "answer": "The schema is at http://127.0.0.1:8000/docs.", "quote": "The complete API schema is available at `http://127.0.0.1:8000/docs`."},
            {"question": "What format can be exported in the walkthrough?", "answer": "Markdown", "quote": "Export Markdown with `GET /api/review/cases/{case_id}/export?format=md`."}]},
        {"path": "docs/adr/0002-postgres-authoritative-qdrant-derived.md", "questions": [
            {"question": "Which database is authoritative?", "answer": "PostgreSQL.", "quote": "Xem PostgreSQL là authoritative và Qdrant là derived index."},
            {"question": "What is Qdrant's role?", "answer": "It is a derived index.", "quote": "Xem PostgreSQL là authoritative và Qdrant là derived index."},
            {"question": "What HTTP status is used for INDEX_INCOMPATIBLE?", "answer": "503.", "quote": "Lỗi identity không tương thích được ánh xạ thành `INDEX_INCOMPATIBLE`"},
            {"question": "What happens if the manifest is missing?", "answer": "It is treated as legacy and unverified.", "quote": "Manifest vắng mặt cho trạng thái legacy chưa xác minh;"},
            {"question": "Is the concrete rebuild and recovery operation verified?", "answer": "No, it is unverified.", "quote": "Quy trình dựng lại và vận hành khôi phục cụ thể: chưa xác minh."}]}
    ]}
    (root / "sanity.json").write_text(json.dumps(sanity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def make_questions(facts):
    q = []
    def hint(fid):
        index = next(i for i, item in enumerate(facts) if item["fact_id"] == fid)
        f = facts[index]
        return {"doc": f"n30/docs/doc_{index % 30 + 1:03}.md", "heading": f"{f['doc_kind'].title()} requirements"}
    for i, f in enumerate(facts[:32]):
        row = normalize_fact(f)
        q.append({"qid": f"q{i+1:02}", "question": f"{f['subject']} về {f['attribute']} là gì?", "language": "vi", "expected_facts": [{"fact_id": f["fact_id"], "attribute": f["attribute"], "value": f["value"], "unit": f["unit"], "normalised_value_seconds_or_number": row["normalised_value_seconds_or_number"]}], "expected_status": "ANSWERABLE", "must_not_contain": ["999 ngày"], "gold_chunk_hint": hint(f["fact_id"])})
    for i, fid in enumerate(["sec01", "sec02", "sec01", "sec02", "sec01", "sec02"]):
        f = next(f for f in facts if f["fact_id"] == fid); row = normalize_fact(f)
        wrong_attribute = "thời hạn lưu" if f["attribute"] == "thời hạn mật khẩu" else "thời hạn mật khẩu"
        q.append({"qid": f"trap{i+1}", "question": f"90 ngày áp dụng cho thuộc tính nào của {f['subject']}?", "language": "vi", "trap": True, "expected_facts": [{"fact_id": fid, "attribute": f["attribute"], "value": f["value"], "unit": f["unit"], "normalised_value_seconds_or_number": row["normalised_value_seconds_or_number"]}], "expected_status": "ANSWERABLE", "must_not_contain": [wrong_attribute], "gold_chunk_hint": hint(fid)})
    for i in range(6):
        f = facts[i]; row = normalize_fact(f)
        q.append({"qid": f"en{i+1}", "question": f"What is the {f['attribute']} rule for {f['subject']}?", "language": "en", "expected_facts": [{"fact_id": f["fact_id"], "attribute": f["attribute"], "value": f["value"], "unit": f["unit"], "normalised_value_seconds_or_number": row["normalised_value_seconds_or_number"]}], "expected_status": "ANSWERABLE", "must_not_contain": ["999 days"], "gold_chunk_hint": hint(f["fact_id"])})
    for i, (a,b) in enumerate((("bak01","bak02"),("log01","log02"),("bil01","bil02"),("onb01","onb03"))):
        pair=[]
        for fid in (a,b):
            f=next(x for x in facts if x["fact_id"]==fid); pair.append({"fact_id":fid,"attribute":f["attribute"],"value":f["value"],"unit":f["unit"],"normalised_value_seconds_or_number":normalize_fact(f)["normalised_value_seconds_or_number"]})
        q.append({"qid":f"multi{i+1}","question":f"What are the {pair[0]['attribute']} and {pair[1]['attribute']} values?","language":"en","expected_facts":pair,"expected_status":"ANSWERABLE","must_not_contain":[],"gold_chunk_hint":hint(a)})
    for i in range(8):
        q.append({"qid":f"none{i+1}","question":f"{('What is' if i%2 else 'Cho biết')} the retention for biometric voiceprints?","language":"en" if i%2 else "vi","expected_facts":[],"expected_status":"NO_EVIDENCE","must_not_contain":["365 ngày","90 ngày","365 days"],"gold_chunk_hint":None})
    return q

def freeze(root):
    entries = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "FREEZE.json":
            entries[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    (root / "FREEZE.json").write_text(json.dumps({"algorithm":"sha256","files":entries}, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--output-dir", default=str(HERE/"data")); args=parser.parse_args()
    build(args.output_dir); freeze(Path(args.output_dir))
