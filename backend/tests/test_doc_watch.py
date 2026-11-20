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


def test_replacement_is_not_reported_as_conflict():
    """Chạy thật 19/11: QĐ 99/2026 thay thế QĐ 12/2020, ngày hiệu lực khác nhau bị đếm là "có thể mâu thuẫn"."""
    from app.analysis.watch import replacement_pairs

    f = watch_findings("new", [OLD, NEW], date(2026, 11, 19))
    assert f["replaces"] == ["qd12.md"] and f["conflicts"] == 0
    docs = [("old", "qd12.md", OLD.text), ("new", "qd99.md", NEW.text)]
    assert replacement_pairs(docs) == {frozenset({"old", "new"})}


def test_judge_endpoint_turns_contradiction_between_replacing_docs_into_superseded():
    import asyncio  # noqa: F401
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.analysis import build_router
    from app.core.types import ProviderResult, Usage

    class P:
        async def generate_structured(self, **kw):
            body = '{"verdict":"CONTRADICTION","severity":"HIGH","same_subject":true,"value_a":"01/03/2020","value_b":"01/01/2026","explanation":"x"}'
            return ProviderResult(text=body, usage=Usage(1, 1), request_id="r", model="m")

        async def generate(self, **kw):
            return await self.generate_structured()

    store = SimpleNamespace(chunks=lambda ids: [OLD, NEW])
    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u"}, owner_pipeline=lambda user, *a: SimpleNamespace(source_store=store),
                                    session_factory=lambda: None, provider_factory=lambda: P()))
    st = lambda c, sid: {"sid": sid, "source_id": c.source_id, "source_name": c.source_name, "chunk_id": c.chunk_id, "text": c.text}
    r = TestClient(app).post("/api/studio/consistency/judge", json={"a": st(OLD, "S1"), "b": st(NEW, "S2")}).json()
    assert r["verdict"] == "UNRELATED" and "superseded" in r["flags"]
