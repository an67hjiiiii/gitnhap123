"""Đợt 10: theo dõi tài liệu mới — tự phát hiện văn bản bị thay thế và cặp câu có thể mâu thuẫn, báo qua chuông."""
from datetime import date

from app.analysis.watch import notify_findings, watch_findings
from app.core.types import SourceChunk


def c(sid, name, text, i=0):
    return SourceChunk(f"{sid}_c{i:04d}", sid, name, text, i)


OLD = c("old", "qd12.md", "UBND TỈNH\nSố: 12/2020/QĐ-UBND\nQUYẾT ĐỊNH\nĐiều 3. Quyết định này có hiệu lực kể từ ngày 01 tháng 3 năm 2020.")
NEW = c("new", "qd99.md", "UBND TỈNH\nSố: 99/2026/QĐ-UBND\nQUYẾT ĐỊNH\nĐiều 5. Quyết định này có hiệu lực kể từ ngày 01 tháng 1 năm 2026 "
        "và thay thế Quyết định số 12/2020/QĐ-UBND.")
RULE_A = c("a", "noi_quy_cu.md", "Người lao động làm thêm giờ không quá 40 giờ trong một tháng theo nội quy công ty.")
RULE_B = c("b", "noi_quy_moi.md", "Người lao động làm thêm giờ không quá 30 giờ trong một tháng theo nội quy công ty.")


def test_new_document_that_replaces_an_old_one_is_reported():
    f = watch_findings("new", [OLD, NEW], date(2026, 11, 19))
    assert f["replaces"] == ["qd12.md"] and f["replaced_by"] is None


def test_uploading_an_outdated_document_is_reported():
    f = watch_findings("old", [OLD, NEW], date(2026, 11, 19))
    assert f["replaced_by"] and "99/2026" in f["replaced_by"]


def test_numbers_that_differ_from_existing_rules_are_flagged_as_possible_conflict():
    f = watch_findings("b", [RULE_A, RULE_B])
    assert f["conflicts"] >= 1 and f["examples"][0]["other"] == "noi_quy_cu.md"


def test_first_document_or_nothing_found_means_no_notification():
    assert watch_findings("a", [RULE_A])["conflicts"] == 0
    quiet = {"replaces": [], "replaced_by": None, "conflicts": 0, "examples": []}
    assert notify_findings(object(), "u", "x.md", quiet) is False
