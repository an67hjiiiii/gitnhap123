"""Sửa sau vòng đo 1 office-eval-v1 (Đợt 8 Văn phòng 3D, 23/11)."""
from app.analysis.skill_router import is_multi_part, route_skill
from app.core.answer_checks import apply_calc
from app.core.types import SourceChunk
from app.ingestion.doc_type import _fold
from app.research.agent_selection import select_agents
from app.retrieval.source_focus import focus_sources


def chunk(name, title):
    return SourceChunk(chunk_id=name, source_id=name, source_name=name, text=f"# {title}\n...", index=0)


DOCS = [chunk("Noi_quy_lao_dong_MAU.md", "NỘI QUY LAO ĐỘNG CÔNG TY CỔ PHẦN MINH AN (TÀI LIỆU MẪU)"),
        chunk("Quy_che_lam_viec_2024_MAU.md", "QUY CHẾ LÀM VIỆC CỦA CÔNG TY CỔ PHẦN MINH AN (TÀI LIỆU MẪU)"),
        chunk("Quy_che_lam_viec_2026_MAU.md", "QUY CHẾ LÀM VIỆC CỦA CÔNG TY CỔ PHẦN MINH AN (TÀI LIỆU MẪU)"),
        chunk("01_Dac_ta_yeu_cau_PayNhanh.md", "ĐẶC TẢ YÊU CẦU PHẦN MỀM – CỔNG THANH TOÁN PAYNHANH")]


def test_named_document_is_focused_and_year_picks_version():
    assert focus_sources("Theo nội quy, tạm ứng 7 triệu thì ai duyệt?", DOCS, None) == ["Noi_quy_lao_dong_MAU.md"]
    assert focus_sources("Theo quy chế 2026, nghỉ ốm 3 ngày cần giấy gì?", DOCS, None) == ["Quy_che_lam_viec_2026_MAU.md"]
    assert set(focus_sources("So với quy chế 2024, quy chế 2026 đổi gì?", DOCS, None)) == {"Quy_che_lam_viec_2024_MAU.md", "Quy_che_lam_viec_2026_MAU.md"}


def test_no_focus_when_unsure_or_generic_words():
    assert focus_sources("Mỗi học kỳ đăng ký tối đa bao nhiêu tín chỉ?", DOCS, None) is None
    assert focus_sources("Bên A chậm thanh toán 10 ngày bị phạt bao nhiêu?", DOCS, None) is None  # "thanh toán" là từ chung
    # câu nhiều vế chỉ nêu một tài liệu: vế còn lại có thể ở tài liệu khác
    assert focus_sources("Theo quy chế 2026 công tác ngoài tỉnh được bao nhiêu, và hóa đơn nộp trong bao lâu?", DOCS, None) is None


def test_multi_part_questions_skip_single_skill():
    q = "Nghỉ phép 4 ngày thì ai duyệt, còn làm thêm ngày lễ được trả bao nhiêu phần trăm?"
    assert is_multi_part(_fold(q)) and route_skill(q, ["internal_rules"]) is None
    assert not is_multi_part(_fold("Tạm ứng 7 triệu đồng thì ai duyệt?"))


def test_floor_division_for_every_full_n_years():
    assert apply_calc("[[= 12 + 6//5 ]]") == "**13**"


def test_keyword_agent_keeps_its_slot_in_office_pack():
    sel = select_agents("Tổng ngân sách và tổng số tiền đã chi của chiến dịch quý IV là bao nhiêu?", None, pack="office")
    assert "marketing" in sel["agents"]


def test_bare_expression_after_equals_is_computed():
    assert apply_calc("Phạt = 0.005*10*120000000 đồng") == "Phạt = 0.005*10*120000000 = **6.000.000** đồng"
    assert apply_calc("Ngày 15/01 = hạn chót") == "Ngày 15/01 = hạn chót"
    assert apply_calc("[[= 12.000.000 × 1,5 ]]") == "**18.000.000**"
