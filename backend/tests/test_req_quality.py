"""Soát chất lượng yêu cầu (ISO/IEC/IEEE 29148): luật bắt đúng lỗi trên yêu cầu viết kém, không báo nhầm trên tài liệu mẫu viết tốt."""
import asyncio
from pathlib import Path

from app.analysis.req_quality import review_text, suggest_rewrite

SAMPLE = Path(__file__).resolve().parents[2] / "frontend/public/samples/01_Dac_ta_yeu_cau_PayNhanh.md"

WEAK = """
## Yêu cầu
### FR-01 Đăng nhập
- Hệ thống phải cho đăng nhập nhanh chóng và giao diện thân thiện.
### FR-02 Báo cáo
- Hệ thống phải xuất báo cáo và phải gửi email cho quản lý, v.v.
### FR-03 Thông báo
- Hệ thống nên gửi thông báo khi có lỗi. Thời hạn lưu: TBD.
### FR-04 Sao lưu
- Hệ thống luôn luôn sao lưu dữ liệu như trên.
### FR-05 Đăng nhập lại
- Hệ thống phải cho đăng nhập nhanh chóng và giao diện thân thiện.
| NFR-01 | Hiệu năng | Hệ thống phải có hiệu năng cao khi nhiều người dùng đồng thời |
| NFR-02 | Hiệu năng | 95% yêu cầu phản hồi dưới 300 ms ở 200 yêu cầu/giây |
"""


def _rules(result, req_id):
    return {i["rule"] for row in result["requirements"] if row["req_id"] == req_id for i in row["issues"]}


def test_weak_requirements_are_flagged():
    r = review_text(WEAK)
    assert {"vague"} <= _rules(r, "FR-01")
    assert {"compound", "open_list"} <= _rules(r, "FR-02")
    assert {"weak", "tbd"} <= _rules(r, "FR-03")
    assert {"absolute", "reference"} <= _rules(r, "FR-04")
    assert "duplicate" in _rules(r, "FR-05") and "duplicate" in _rules(r, "FR-01")
    assert {"unmeasured", "vague"} <= _rules(r, "NFR-01")
    assert _rules(r, "NFR-02") == set()  # có chỉ tiêu định lượng thì đạt
    s = r["summary"]
    # FR-04 chỉ có mục "lưu ý" (mức thông tin) nên vẫn tính là đạt, cùng NFR-02
    assert s["total"] == 7 and s["clean"] == 2 and s["errors"] == 1 and s["infos"] >= 2
    assert s["by_characteristic"]["unambiguous"] >= 3


def test_each_issue_points_to_evidence_and_standard():
    r = review_text(WEAK)
    issue = next(i for row in r["requirements"] for i in row["issues"] if i["rule"] == "vague")
    assert issue["evidence"].lower() in ("nhanh chóng", "thân thiện") and issue["characteristic"] == "unambiguous"
    assert "29148" in r["standard"] and len(r["rules"]) == 10


def test_well_written_sample_has_almost_no_false_alarms():
    r = review_text(SAMPLE.read_text(encoding="utf-8"))
    assert r["summary"]["total"] >= 17
    assert r["summary"]["errors"] == 0 and r["summary"]["warnings"] == 0


def test_capability_wording_is_not_weak():
    # "có thể" chỉ quyền được làm, không phải lời lẽ khuyến nghị; "PayNhanh" không chứa từ "nhanh"
    r = review_text("### FR-01 Thu hồi khóa\n- Merchant Owner có thể thu hồi khóa trên PayNhanh trong 60 giây.")
    assert _rules(r, "FR-01") == set()


class FakeProvider:
    def __init__(self, reply):
        self.reply = reply


def test_obligations_split_compound_statement():
    from app.analysis.req_quality import obligations
    assert obligations("- Hệ thống phải cho đăng nhập nhanh chóng và giao diện phải thân thiện.") == [
        "Hệ thống phải cho đăng nhập nhanh chóng", "giao diện phải thân thiện"]
    # "và" không mở nghĩa vụ mới thì giữ nguyên câu
    assert obligations("Merchant đăng ký bằng email và số điện thoại.") == ["Merchant đăng ký bằng email và số điện thoại"]


def test_rewrite_covers_obligations_and_rechecks(monkeypatch):
    calls = []
    replies = {
        "Hệ thống phải cho đăng nhập nhanh chóng": {"text": "Hệ thống phải hoàn tất đăng nhập trong [cần xác định: thời gian tối đa] giây.",
                                                    "question": "Thời gian đăng nhập tối đa là bao nhiêu giây?"},
        "giao diện phải thân thiện": {"text": "Giao diện phải thân thiện và đạt 4 trên 5 điểm khảo sát.", "question": "cần xác định"},
    }

    async def fake_call(provider, system, user, schema, max_tokens):
        assert "NEVER invent numbers" in system
        item = user.split("OBLIGATION:\n", 1)[1].split("\n", 1)[0]
        calls.append(item)
        return replies[item], {"input_tokens": 10, "output_tokens": 5, "latency_ms": 100}
    monkeypatch.setattr("app.analysis.req_quality._call", fake_call)
    out = asyncio.run(suggest_rewrite(FakeProvider(None), "FR-01", "Hệ thống phải cho đăng nhập nhanh chóng và giao diện phải thân thiện.",
                                      ["Từ ngữ mơ hồ: nhanh chóng", "Từ ngữ mơ hồ: thân thiện"]))
    assert calls == list(replies)  # mỗi nghĩa vụ một lần gọi, không bỏ ý nào
    assert len(out["rewrites"]) == 2 and out["missing"] == [] and out["input_tokens"] == 20 and out["latency_ms"] == 200
    assert out["open_questions"] == ["Thời gian đăng nhập tối đa là bao nhiêu giây?"]  # câu hỏi cụt bị bỏ
    assert out["new_numbers"] == ["4", "5"]  # số mô hình tự thêm được chỉ ra để người dùng soát
    assert any("thân thiện" in r for r in out["remaining"])  # bản viết lại còn từ mơ hồ thì báo ra
