"""A5 regressions and a standalone, question-aware DEV scorer.

Run directly with --build-dev5 to reconstruct and label the eight removed
sentences from six DEV questions; otherwise score the resulting JSONL.
"""
import asyncio
import csv
import difflib
import json
from pathlib import Path
import re
import sys

import pytest

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chat.answer_guard import AnswerChecker, guard_answer


@pytest.mark.parametrize("question,answer,source,keep", [
    ("Bảo lưu 36 tháng được không?", "Không thể bảo lưu 36 tháng.",
     "Thời hạn bảo lưu tối đa là 24 tháng.", True),
    ("Bảo lưu 36 tháng được không?", "Bảo lưu được 48 tháng.",
     "Thời hạn bảo lưu tối đa là 24 tháng.", False),
    ("Bảo lưu 24 tháng được không?", "Bảo lưu được 2 năm.", "Quy định về bảo lưu.", True),
    ("Bảo lưu 2 năm được không?", "Bảo lưu được 24 tháng.", "Quy định về bảo lưu.", True),
    (None, "Bảo lưu được 1 năm.", "Bảo lưu được 12 tháng.", True),
    (None, "Bảo lưu được 12 tháng.", "Bảo lưu được 1 năm.", True),
    (None, "Phiên hết hạn sau 60 phút.", "Phiên hết hạn sau 1 giờ.", True),
    (None, "Phiên hết hạn sau 1 giờ.", "Phiên hết hạn sau 60 phút.", True),
    ("Thời hạn 6 ngày?", "The period is 6 days.", "Quy định thời hạn.", True),
    ("The period is 6 days?", "Thời hạn là 6 ngày.", "Quy định thời hạn.", True),
    ("Thời hạn 2 hours?", "Thời hạn là 120 phút.", "Quy định thời hạn.", True),
    ("Thời hạn 120 minutes?", "Thời hạn là 2 giờ.", "Quy định thời hạn.", True),
    ("Thời hạn 6 ngày?", "Thời hạn là 6 giờ.", "Quy định thời hạn.", False),
    ("Đề án 89 hỗ trợ ai?", "Đề án 89 hỗ trợ giảng viên.", "Đề án hỗ trợ giảng viên.", True),
    (None, "Đề án 89 hỗ trợ giảng viên.", "Đối tượng tham gia Đề án 89 là giảng viên.", True),
    ("Đề án 89 hỗ trợ ai?", "Đề án 98 hỗ trợ giảng viên.", "Đề án hỗ trợ giảng viên.", False),
    ("Có 98 hồ sơ cho Đề án 89?", "Đề án 98 hỗ trợ giảng viên.", "Đề án hỗ trợ giảng viên.", False),
    (None, "Nghị định 99 áp dụng cho trường.", "Căn cứ NGHỊ ĐỊNH SỐ 99, trường phải thực hiện.", True),
    (None, "Nghị định 98 áp dụng cho trường.", "Nghị định 99 có 98 hồ sơ.", False),
    ("Có áp dụng ngày 15/5/2026?", "Thông tư có hiệu lực ngày 15 tháng 5 năm 2026.",
     "Thông tư có hiệu lực từ ngày 1/1/2027.", True),
    ("Có áp dụng ngày 15/5/2026?", "Thông tư có hiệu lực ngày 16/5/2026.",
     "Thông tư có hiệu lực từ ngày 1/1/2027.", False),
    ("Mã 429 là gì?", "Mã là 429.", "Mã lỗi của hệ thống.", True),
    ("Mã 429 là gì?", "Mã là 500.", "Mã lỗi của hệ thống.", False),
    ("Thông tư có hiệu lực ngày 15/5/2026?",
     "Sau ngày 15/5/2026, Thông tư có hiệu lực.",
     "Thông tư này có hiệu lực thi hành kể từ ngày 15 tháng 5 năm 2026.", True),
])
@pytest.mark.parametrize("mode", ["drop", "mark"])
def test_a5_values(monkeypatch, question, answer, source, keep, mode):
    monkeypatch.setenv("GUARD_MODE", mode)
    result = guard_answer(answer, status="COMPLETE", evidence_texts=[source], question=question)
    assert bool(result.removed_claims) is not keep
    if keep:
        assert result.answer == answer and result.notes == []


def test_question_does_not_supply_negation_or_calculation_evidence():
    result = guard_answer("Phiên không hết hạn sau 30 phút.", status="COMPLETE",
                          evidence_texts=["Phiên hết hạn sau 30 phút."],
                          question="Phiên không hết hạn sau 30 phút?")
    assert result.removed_claims and "NEGATION_CONFLICT_DROPPED" in result.notes
    result = guard_answer("Bảo lưu được 60 tháng.", status="COMPLETE",
                          evidence_texts=["Quy định bảo lưu."],
                          question="Bảo lưu 24 tháng hay 36 tháng?")
    assert result.removed_claims


def test_static_guard_passes_question():
    result = AnswerChecker.guard("Không thể bảo lưu 36 tháng.", status="COMPLETE",
                                 evidence_texts=["Thời hạn bảo lưu tối đa là 24 tháng."],
                                 question="Bảo lưu 36 tháng được không?")
    assert not result.removed_claims


def test_vanilla_passes_original_question(monkeypatch):
    from app.core.types import ProviderResult, RunMetrics, SourceChunk
    from app.research.vanilla import answer_vanilla

    monkeypatch.setenv("ANSWER_LLM_VERIFY", "0")
    question = "Bảo lưu 36 tháng được không?"

    class Provider:
        async def generate(self, **kwargs):
            return ProviderResult(json.dumps({"status": "COMPLETE", "answer": "Không thể bảo lưu 36 tháng.",
                                              "citations": ["c1"]}))

    class Checker(AnswerChecker):
        @staticmethod
        def guard(answer, **kwargs):
            assert kwargs["question"] == question
            return AnswerChecker.guard(answer, **kwargs)

    result = asyncio.run(answer_vanilla(Provider(), question,
                         [SourceChunk("c1", "s1", "source.txt", "Thời hạn bảo lưu tối đa là 24 tháng.", 0)],
                         RunMetrics(), checker=Checker()))
    assert result.status == "COMPLETE"
    assert "Không thể bảo lưu 36 tháng." in result.answer


def _norm(text):
    return re.sub(r"\s+", " ", text.split("Nguồn:")[0]).strip()


def build_dev5(root, *, write=True):
    """Use only the disclosed DEV logs, never holdout input."""
    logs = [json.loads(line) for line in (root / "lo_truy_hoi/guard_log_full4.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    results = [json.loads(line) for line in (root / "lo_truy_hoi/dev_run4/results.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    with (root / "bo_cau_hoi/dev.csv").open(encoding="utf-8-sig", newline="") as handle:
        questions = {row["id"]: row["cau_hoi"] for row in csv.DictReader(handle)}
    with (root / "lo_truy_hoi/m4_phan_loai.csv").open(encoding="utf-8-sig", newline="") as handle:
        ids = [row["id"] for row in csv.DictReader(handle) if row["nhan"] == "guard"]
    reasons = {
        "L1_9": [("keep", "Nguồn cho phép AI hỗ trợ có kiểm soát, minh bạch, tuân thủ liêm chính; không mâu thuẫn với câu trả lời.")],
        "L1_26": [("keep", "Đề án 89 có trong câu hỏi và bằng chứng; nguồn cho phép giảng viên cơ hữu thể thao nhận hỗ trợ học thạc sĩ theo điều kiện.")],
        "L1_40": [("keep", "Điều 52 nêu hiệu lực từ 15/5/2026 và thay thế Thông tư 12/2017; câu hỏi cũng có ngày này.")],
        "L1_42": [("keep", "Nguồn ghi giấy chứng nhận có điều kiện có giá trị 02 năm kể từ ngày cấp."),
                  ("drop", "Nguồn yêu cầu cải tiến và đề nghị đánh giá lại trong không quá 02 năm; câu trả lời chuyển thành sau khi hết thời hạn."),
                  ("keep", "Điều 45: hết hạn 24 tháng mà không đáp ứng yêu cầu thì giấy chứng nhận hết hiệu lực, kiểm định lại từ đầu.")],
        "L2_56": [("keep", "Điều 5 ghi trình độ đại học, ít nhất 02 năm kinh nghiệm từ trưởng khoa/phòng/ban ở cùng trình độ hoặc cao hơn.")],
        "L2_80": [("keep", "Năm 2023 và 2026 có trong câu hỏi; nguồn quy định thời hạn đạt giải không quá 03 năm và ưu tiên khi không dùng tuyển thẳng.")],
    }
    cases = []
    for case_id in ids:
        result = next(row for row in results if row["id"] == case_id)
        score, index = max((difflib.SequenceMatcher(None, _norm(result["answer"]), _norm(log["answer_out"])).ratio(), i)
                           for i, log in enumerate(logs))
        assert score == 1.0, (case_id, score)
        log = logs[index]
        assert len(log["removed"]) == len(reasons[case_id])
        for claim_index, (sentence, (expect, reason)) in enumerate(zip(log["removed"], reasons[case_id]), 1):
            cases.append(dict(id=case_id, claim_index=claim_index, question=questions[case_id], answer=sentence,
                              evidence=log["evidence"], cited=log["cited"], expect=expect, reason=reason,
                              answer_before_guard=log["answer_in"], log_line=index + 1, match_ratio=score))
    data = "\r\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\r\n"
    if write:
        (root / "dev5_cases.jsonl").write_bytes(data.encode("utf-8"))
    return data


def score_dev5(path, *, data=None):
    groups = {}
    passed = total = 0
    for line in (data if data is not None else path.read_text(encoding="utf-8")).splitlines():
        case = json.loads(line)
        result = guard_answer(case["answer"], status="COMPLETE", evidence_texts=case["evidence"],
                              cited_texts=case.get("cited"), question=case["question"])
        removed = bool(result.removed_claims) or any(note.startswith("ANSWER_REPLACED") for note in result.notes)
        flagged = any(note.startswith("FLAG_") for note in result.notes)
        intact = not removed and all(_norm(row) in _norm(result.answer) for row in case["answer"].splitlines() if row.strip()) \
            and case["answer"].count("\n") <= result.answer.count("\n")
        good = intact and not flagged if case["expect"] == "keep" else removed
        groups[case["id"]] = groups.get(case["id"], True) and good
        passed += good
        total += 1
        print(case["id"], case["claim_index"], case["expect"], "PASS" if good else "FAIL", result.notes)
    print(f"DEV5 sentences={passed}/{total}; questions={sum(groups.values())}/{len(groups)}")


if __name__ == "__main__":
    root = Path(r"D:\CAP1-Orchestration\work\p3")
    data = None
    if "--build-dev5" in sys.argv:
        build_dev5(root)
    if "--dev5-in-memory" in sys.argv:
        data = build_dev5(root, write=False)
    score_dev5(root / "dev5_cases.jsonl", data=data)
