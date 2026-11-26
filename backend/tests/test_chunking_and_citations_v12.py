"""Kiểm thử hồi quy V12: Parser DOCX/PDF, chia đoạn Structure-Aware và truy vết Citation / lọc NO_EVIDENCE."""
from __future__ import annotations

import asyncio
import io
import json
import zipfile

from app.core.citations import resolve_citations
from app.core.types import ProviderResult, RunMetrics, SourceChunk, Task, Usage
from app.ingestion.documents import extract_document
from app.research.registry import use_pack
from app.research.worker import execute_task
from app.retrieval.text import chunk_text, make_chunks

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _zip(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_docx_preserves_soft_breaks_lists_and_splits_glued_bullets():
    doc = (
        f'<w:document {W}><w:body>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>1. Chính sách Nghỉ phép năm</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>- Nhân viên đủ 12 tháng hưởng 12 ngày phép năm có nguyên lương.- Cộng thâm niên: cứ đủ 4 năm cộng thêm 1 ngày.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Dòng một</w:t><w:br/><w:t>Dòng hai</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Mục danh sách tự động</w:t></w:r></w:p>'
        '</w:body></w:document>'
    )
    out = extract_document(_zip({"word/document.xml": doc}), "hr.docx")
    assert "nguyên lương.\n- Cộng thâm niên:" in out.text
    assert "Dòng một\nDòng hai" in out.text
    assert "- Mục danh sách tự động" in out.text


def test_structure_aware_chunking_keeps_headings_and_table_headers():
    doc = (
        "QUY CHẾ NHÂN SỰ, CHẤM CÔNG & PHÚC LỢI VIETCORE AI (PHIÊN BẢN 2026)\n\n"
        "# 1. Chính sách Nghỉ phép năm và Cộng thâm niên\n\n"
        + "\n".join(f"- Quy định phép năm chi tiết số {i}: áp dụng cho toàn thể nhân viên chính thức đủ thâm niên." for i in range(1, 6))
        + "\n\n# 2. Quy định Chấm công & Phụ cấp chuyên cần\n\n"
        + "\n".join(f"- Quy định chấm công số {i}: giờ làm hành chính và mức trừ phụ cấp đi muộn vượt ngưỡng." for i in range(1, 6))
        + "\n\n# 3. Khung Thưởng KPI Cuối năm\n\n"
        + "Xếp loại KPI | Thang điểm | Thưởng KPI | Phân bổ\n"
        + "\n".join(f"Bậc {i} | {50 + i} - {55 + i} điểm | {i * 0.5} tháng lương gross | 10% nhân sự công ty" for i in range(1, 18))
    )
    chunks = chunk_text(doc, max_chars=700)
    assert len(chunks) >= 4
    # Mục 2 phải mở đầu bằng tiêu đề của chính nó, không mồ côi
    sec2 = [c for c in chunks if "Quy định chấm công số 1" in c]
    assert sec2 and "# 2. Quy định Chấm công" in sec2[0]
    # Không nhồi chung Mục 2 và Mục 3 vào cùng một đoạn
    assert not any("Quy định chấm công số 1" in c and "# 3. Khung Thưởng KPI" in c for c in chunks)
    # Bảng KPI bị tách thành nhiều đoạn thì MỌI đoạn chứa hàng bảng phải giữ dòng tiêu đề cột
    kpi_chunks = [c for c in chunks if "Bậc 15 |" in c or "Bậc 1 |" in c]
    assert len(kpi_chunks) >= 2
    for kc in kpi_chunks:
        assert "Xếp loại KPI | Thang điểm | Thưởng KPI | Phân bổ" in kc


def test_make_chunks_attaches_estimated_tokens_and_section_heading():
    chunks = make_chunks("quy_che.md", "# 1. Nghỉ phép năm\n\nNhân viên hưởng 12 ngày nghỉ phép mỗi năm.")
    assert len(chunks) == 1
    assert chunks[0].provenance["estimated_tokens"] > 0
    assert chunks[0].provenance["section_heading"] == "1. Nghỉ phép năm"


def test_resolve_citations_recovers_missing_citation_and_blocks_no_evidence():
    fin_chunk = SourceChunk(
        chunk_id="src_aaaa1111_c0000",
        source_id="src_aaaa1111",
        source_name="02_Bao_Cao_Tai_Chinh.xlsx",
        text="## Ket_Qua_KD_Q4_2025\nChỉ tiêu | Q4/2025\nTổng doanh thu thuần | 18.000 triệu VNĐ\nLợi nhuận trước thuế | 6.000 triệu VNĐ",
        index=0,
    )
    hr_chunk = SourceChunk(
        chunk_id="src_bbbb2222_c0000",
        source_id="src_bbbb2222",
        source_name="01_Quy_Che_Nhan_Su.docx",
        text="# 1. Chính sách Nghỉ phép năm\nNhân viên được hưởng 12 ngày phép năm.",
        index=0,
    )

    # 1. Mô hình quên ghi citation nhưng câu trả lời chứa số liệu chính xác của Excel -> tự truy vết đúng fin_chunk
    valid, invalid = resolve_citations(
        [],
        [fin_chunk, hr_chunk],
        "Tổng doanh thu thuần Q4/2025 là 18.000 triệu VNĐ và lợi nhuận trước thuế là 6.000 triệu VNĐ.",
    )
    assert valid == ["src_aaaa1111_c0000"]
    assert invalid == []

    # 2. Mô hình bọc ngoặc thừa và sai hoa/thường -> chuẩn hóa khớp
    valid2, invalid2 = resolve_citations(["[SRC_AAAA1111_C0000]"], [fin_chunk, hr_chunk], "Doanh thu 18.000 triệu VNĐ")
    assert valid2 == ["src_aaaa1111_c0000"]
    assert invalid2 == []

    # 3. Worker trả NO_EVIDENCE dù điền nhầm citation -> phải xóa sạch citations để không gắn nhầm Nguồn tham chiếu
    class _StubProvider:
        supports_per_call_output_tokens = False

        async def generate(self, system: str, user: str) -> ProviderResult:
            return ProviderResult(
                text=json.dumps({
                    "status": "NO_EVIDENCE",
                    "answer": "Tài liệu không đề cập đến bảo hiểm sức khỏe cho người thân.",
                    "citations": ["src_bbbb2222_c0000"],
                    "missing_information": ["bảo hiểm sức khỏe cho người thân"],
                }),
                usage=Usage(input_tokens=10, output_tokens=10),
            )

    with use_pack("office"):
        res = asyncio.run(
            execute_task(
                _StubProvider(),
                Task(task_id="T2", domain="hr", goal="Kiểm tra bảo hiểm sức khỏe người thân"),
                [hr_chunk],
                RunMetrics(),
                product=True,
            )
        )
    assert res.status == "NO_EVIDENCE"
    assert res.citations == []


def test_apply_calc_with_percent_and_step_rules():
    from app.core.answer_checks import apply_calc_with_values

    txt = (
        "Phạt tiến độ [[= 0.5% * 10 * 240000000 ]] VNĐ; "
        "trần [[= 8% * 240000000 ]] VNĐ; "
        "học bổng [[= 120% * 15 * 950000 ]] VNĐ; "
        "gói khám [[= 12 * 2800000 * (1 - 15%) ]] VNĐ; "
        "cước [[= 28000 + ((3.5 - 2) / 0.5) * 4500 ]] VNĐ; "
        "chia phần trăm [[= 100 / 20% ]]."
    )
    rendered, computed = apply_calc_with_values(txt)
    assert "**12.000.000**" in rendered
    assert "**19.200.000**" in rendered
    assert "**17.100.000**" in rendered
    assert "**28.560.000**" in rendered
    assert "**41.500**" in rendered
    assert "**500**" in rendered
    assert "28560000" in computed
    assert "12000000" in computed


def test_finish_respects_worker_computed_numbers_and_catches_english_thousand_hallucination():
    from app.core.answer_checks import finish

    sources = "Gói GK-NC giá 2.800.000 VNĐ/người, nhóm từ 10 người giảm 15%. Số người: 12."
    ans_ok, bad_ok = finish(
        "Tổng chi phí sau ưu đãi cho 12 nhân viên là **28.560.000** VNĐ.",
        sources,
        extra_known={"28560000"},
    )
    assert bad_ok == []
    assert "Cần kiểm tra lại" not in ans_ok

    ans_bad, bad_nums = finish(
        "Mức học bổng là 1,080,000 VNĐ.",
        "Học phí 950.000 VNĐ/tín chỉ, 15 tín chỉ.",
    )
    assert "1080000" in bad_nums
    assert "1.08" not in bad_nums
    assert "Cần kiểm tra lại" in ans_bad


def test_unsupported_articles_accepts_numbered_sections_but_flags_wrong_legal_article():
    from app.core.answer_checks import unsupported_articles

    policy_src = "# 1. Chính sách Nghỉ phép\nNội dung...\n# 2. Thời giờ làm việc\nNội dung...\n# 3. Khung thưởng KPI"
    assert unsupported_articles("Theo Điều 1 và Điều 3 của quy chế.", policy_src) == []

    legal_src = "Điều 14. Nghĩa vụ bảo mật thông tin."
    assert unsupported_articles("Theo Điều 3 khoản 5 của hợp đồng.", legal_src) == ["3"]
    assert unsupported_articles("Theo Điều 14 của hợp đồng.", legal_src) == []


def test_resolve_citations_supplements_missing_second_document_without_false_positive():
    from app.core.citations import resolve_citations

    c_policy = SourceChunk(
        chunk_id="src_tm01_c0000",
        source_id="src_tm01",
        source_name="TM_01_Chinh_Sach_Doi_Tra.docx",
        index=0,
        text="Thiết bị điện tử VietMart Mall được đổi trả trong 15 ngày. Hoàn tiền Ví VietMartPay trong 24 giờ.",
    )
    c_ship = SourceChunk(
        chunk_id="src_tm02_c0001",
        source_id="src_tm02",
        source_name="TM_02_Bang_Cuoc_Van_Chuyen.xlsx",
        index=1,
        text="Hàng hóa thất lạc có khai giá: bồi thường 100% giá trị đơn hàng tối đa 20.000.000 VNĐ. Không khai giá tối thiểu 200.000 VNĐ.",
    )
    c_unrelated = SourceChunk(
        chunk_id="src_hr01_c0000",
        source_id="src_hr01",
        source_name="01_Quy_Che_Nhan_Su.docx",
        index=0,
        text="Nhân viên làm đủ 12 tháng hưởng 12 ngày phép năm, phụ cấp chuyên cần 1.500.000 VNĐ/tháng.",
    )
    answer = (
        "Đổi trả thiết bị điện tử trong 15 ngày, hoàn tiền Ví VietMartPay trong 24 giờ. "
        "Đơn hàng thất lạc có khai giá được bồi thường 100% tối đa 20.000.000 VNĐ (không khai giá tối thiểu 200.000 VNĐ)."
    )
    valid, invalid = resolve_citations(["src_tm01_c0000"], [c_policy, c_ship, c_unrelated], answer)
    assert "src_tm01_c0000" in valid
    assert "src_tm02_c0001" in valid
    assert "src_hr01_c0000" not in valid
    assert invalid == []


def test_unsupported_articles_handles_chunk_prefix_before_section_heading():
    from app.core.answer_checks import unsupported_articles

    ev = "[src_ea1e20917539e1d5_c0002] # 2. Thời giờ Làm việc và Phụ cấp chuyên cần\nNội dung...\n[src_ea1e20917539e1d5_c0003] # 3. Khung Thưởng KPI"
    assert unsupported_articles("Theo Điều 2 và Điều 3 của quy chế.", ev) == []


def test_detect_unanchored_entities_and_worker_anti_hallucination_guard():
    import asyncio
    from app.core.answer_checks import detect_unanchored_entities
    from app.core.types import ProviderResult, RunMetrics, Task, Usage
    from app.research.registry import use_pack
    from app.research.worker import execute_task

    ev_text = "Gói khám tổng quát nâng cao GK-NC: 2.800.000 VNĐ, gồm 24 hạng mục xét nghiệm sinh hóa và siêu âm."
    missing_mri = detect_unanchored_entities("Phòng khám có chụp MRI 3.0 Tesla và giá bao nhiêu?", ev_text)
    assert any("MRI" in x for x in missing_mri)

    missing_law = detect_unanchored_entities("Mức phạt rò rỉ dữ liệu theo Nghị định 13 là bao nhiêu?", "Điều 2. Phạt chậm tiến độ 0,5%/ngày.")
    assert any("Nghị định 13" in x for x in missing_law)

    assert detect_unanchored_entities("Gói GK-NC giá bao nhiêu?", ev_text) == []

    class HallucinatingWorkerProvider:
        supports_per_call_output_tokens = False

        async def generate(self, system: str, user: str):
            return ProviderResult(
                text='{"status":"COMPLETE","answer":"Phòng khám An Tâm cung cấp dịch vụ chụp MRI 3.0 Tesla với giá 2.800.000 VNĐ.","citations":["src_yt02_c0000"],"missing_information":[]}',
                usage=Usage(input_tokens=80, output_tokens=30),
            )

    chunk = SourceChunk(
        chunk_id="src_yt02_c0000",
        source_id="src_yt02",
        source_name="YT_02_Bang_Gia.xlsx",
        index=0,
        text=ev_text,
    )
    task = Task(task_id="T2", goal="Kiểm tra dịch vụ chụp cộng hưởng từ MRI 3.0 Tesla và giá", domain="analyst")
    with use_pack("office"):
        res = asyncio.run(execute_task(HallucinatingWorkerProvider(), task, [chunk], RunMetrics(), product=True))
    assert res.status == "NO_EVIDENCE"
    assert res.citations == []
    assert "không chứa thông tin" in res.answer.casefold()


def test_worker_guard_blocks_silent_clause_substitution_and_vanilla_no_evidence_stays_clean():
    import asyncio
    from app.core.types import ProviderResult, RunMetrics, Task, Usage
    from app.research.registry import use_pack
    from app.research.vanilla import answer_vanilla
    from app.research.worker import execute_task

    # Case 1: Worker trả lời bằng Điều 2 phạt chậm tiến độ mà không nhắc chữ 'Nghị định 13'
    class SubstitutorProvider:
        supports_per_call_output_tokens = False

        async def generate(self, system: str, user: str):
            return ProviderResult(
                text='{"status":"COMPLETE","answer":"Điều 2. Nếu Bên B chậm bàn giao hệ thống thì chịu phạt 0,5%/ngày.","citations":["src_hd01_c0002"],"missing_information":[]}',
                usage=Usage(input_tokens=60, output_tokens=25),
            )

    chunk = SourceChunk(
        chunk_id="src_hd01_c0002",
        source_id="src_hd01",
        source_name="HD_01.docx",
        index=2,
        text="Điều 2. Phạt vi phạm tiến độ 0,5%/ngày, tối đa 8% giá trị hợp đồng.",
    )
    task = Task(task_id="T2", goal="Mức phạt rò rỉ dữ liệu cá nhân theo Nghị định 13 trong hợp đồng", domain="analyst")
    with use_pack("office"):
        res = asyncio.run(execute_task(SubstitutorProvider(), task, [chunk], RunMetrics(), product=True))
    assert res.status == "NO_EVIDENCE"
    assert res.citations == []

    # Case 2: Vanilla NO_EVIDENCE không bao giờ gắn banner 'Cần kiểm tra lại' hay 'Lưu ý căn cứ'
    class NoEvVerboseProvider:
        supports_per_call_output_tokens = False

        async def generate(self, system: str, user: str):
            return ProviderResult(
                text='{"status":"NO_EVIDENCE","answer":"Tài liệu hiện có không cung cấp mã số thuế theo Điều 398 Bộ luật Dân sự 2015.","citations":[],"missing_information":["mã số thuế"]}',
                usage=Usage(input_tokens=50, output_tokens=25),
            )

    res2 = asyncio.run(answer_vanilla(NoEvVerboseProvider(), "Mã số thuế của công ty là gì?", [chunk], RunMetrics(), product=True))
    assert res2.status == "NO_EVIDENCE"
    assert res2.citations == []
    assert "Cần kiểm tra lại" not in res2.answer
    assert "Lưu ý căn cứ" not in res2.answer


def test_round4_regressions_prose_typo_ast_intermediates_and_bilingual_law_ref():
    from app.core.answer_checks import detect_unanchored_entities, finish
    from app.core.citations import resolve_citations

    # 1. Typo 1 ký tự trong prose không biến thành invalid citation khi mảng citations đã hợp lệ
    c2 = SourceChunk(chunk_id="src_f33e387389e096b2_c0002", source_id="s1", source_name="hr.docx", index=2, text="Miễn trừ 2 lần, quá 15 phút trừ 150.000 VNĐ.")
    valid, invalid = resolve_citations(
        ["src_f33e387389e096b2_c0002"],
        [c2],
        "Quy tắc từ [src_f33e387389e0096b2_c0002] cho biết trừ 450.000 VNĐ.",
    )
    assert valid == ["src_f33e387389e096b2_c0002"]
    assert invalid == []

    # 2. Giá trị trung gian trong AST [[= 28000 + ((3.5 - 2) / 0.5) * 4500 ]] (1.5, 3, 13500) được công nhận
    ans, bad = finish(
        "Tổng cước là [[= 28000 + ((3.5 - 2) / 0.5) * 4500 ]] VNĐ.\nTrọng lượng vượt quá 2 kg: **1,5 kg**, tổng phụ phí: **13.500 VNĐ**.",
        "Cước cơ bản (<= 2 kg): 28.000 VNĐ. Phụ phí mỗi 0,5 kg vượt thêm: 4.500 VNĐ. Kiện hàng nặng 3,5 kg.",
    )
    assert bad == []
    assert "**41.500**" in ans
    assert "Cần kiểm tra lại" not in ans

    # 3. Song ngữ Decree 13 <-> Nghị định 13
    missing = detect_unanchored_entities("Determine penalty under Decree 13 in contract", "Điều 2. Phạt chậm tiến độ 0,5%/ngày.")
    assert missing == ["Nghị Định 13"] or any("13" in m for m in missing)
    assert detect_unanchored_entities("Determine penalty under Decree 13", "Điều 5. Thực hiện theo Nghị định 13/2023 về bảo vệ dữ liệu.") == []


def test_round5_grounded_citation_pruning_and_thinking_leak_repair():
    import asyncio
    from app.core.citations import resolve_citations
    from app.core.types import ProviderResult, RunMetrics, Usage
    from app.research.vanilla import answer_vanilla

    # 1. Pruning loại bỏ chunk Quy chế Nhân sự bị cite nhầm khi câu trả lời chỉ nói về doanh thu/lợi nhuận Excel
    c_hr = SourceChunk(
        chunk_id="src_hr_c0000",
        source_id="hr",
        source_name="01_Quy_Che_Nhan_Su_VietCore_2026.docx",
        index=0,
        text="QUY CHẾ NHÂN SỰ, CHẤM CÔNG & PHÚC LỢI VIETCORE AI (PHIÊN BẢN 2026). Phòng Hành chính - Nhân sự.",
    )
    c_fin = SourceChunk(
        chunk_id="src_fin_c0000",
        source_id="fin",
        source_name="02_Bao_Cao_Tai_Chinh_Q4_2025_VietCore.xlsx",
        index=0,
        text="Tổng doanh thu thuần Quý IV/2025 của VietCore AI đạt 18.000 triệu VNĐ, lợi nhuận trước thuế đạt 6.000 triệu VNĐ.",
    )
    valid, invalid = resolve_citations(
        ["src_hr_c0000", "src_fin_c0000"],
        [c_hr, c_fin],
        "Tổng doanh thu thuần và lợi nhuận trước thuế Quý IV/2025 là 18.000 triệu VNĐ và 6.000 triệu VNĐ.",
    )
    assert valid == ["src_fin_c0000"]
    assert invalid == []

    # 2. Thinking Loop Leak ('Wait, let me recheck...') kích hoạt Self-Repair sạch sẽ
    class LeakyThenCleanProvider:
        supports_per_call_output_tokens = False

        def __init__(self):
            self.calls = 0

        async def generate(self, system: str, user: str):
            self.calls += 1
            if self.calls == 1:
                return ProviderResult(
                    text='{"status":"PARTIAL","answer":"Bị trừ 300.000 VNĐ. Wait, let me recheck the evidence. So for 5 times it is 450.000.","citations":["src_hr_c0002"],"missing_information":["model output truncated"]}',
                    usage=Usage(input_tokens=80, output_tokens=60),
                )
            return ProviderResult(
                text='{"status":"COMPLETE","answer":"Mức trừ phụ cấp chuyên cần là [[= (5 - 2) * 150000 ]] VNĐ.","citations":["src_hr_c0002"],"missing_information":[]}',
                usage=Usage(input_tokens=90, output_tokens=30),
            )

    c_rule = SourceChunk(
        chunk_id="src_hr_c0002",
        source_id="hr",
        source_name="01_Quy_Che.docx",
        index=2,
        text="Miễn trừ tối đa 2 lần/tháng. Từ lần vi phạm thứ 3 trở đi bị trừ 150.000 VNĐ mỗi lần.",
    )
    prov = LeakyThenCleanProvider()
    res = asyncio.run(answer_vanilla(prov, "Đi muộn 5 lần bị trừ bao nhiêu?", [c_rule], RunMetrics(), product=True))
    assert prov.calls == 2
    assert res.status == "COMPLETE"
    assert "450.000" in res.answer
    assert "Wait, let me" not in res.answer


def test_round6_pure_refusal_partial_worker_normalized_to_no_evidence():
    import asyncio
    from app.core.types import ProviderResult, RunMetrics, Task, Usage
    from app.research.registry import use_pack
    from app.research.worker import execute_task

    class PartialPureRefusalProvider:
        supports_per_call_output_tokens = False

        async def generate(self, system: str, user: str):
            return ProviderResult(
                text='{"status":"PARTIAL","answer":"Chính sách bảo hiểm sức khỏe cho người thân nhân viên và mức phụ cấp ăn trưa hằng tháng năm 2026 không được đề cập trong các tài liệu VietCore AI hiện có.","citations":["src_hr_c0000"],"missing_information":["phụ cấp ăn trưa"]}',
                usage=Usage(input_tokens=60, output_tokens=30),
            )

    c_hr = SourceChunk(chunk_id="src_hr_c0000", source_id="hr", source_name="01_Quy_Che.docx", index=0, text="Quy chế nhân sự VietCore AI.")
    task = Task(task_id="t2", goal="Chính sách bảo hiểm sức khỏe người thân và phụ cấp ăn trưa 2026", domain="hr")
    with use_pack("office"):
        res = asyncio.run(execute_task(PartialPureRefusalProvider(), task, [c_hr], RunMetrics(), product=True))
    assert res.status == "NO_EVIDENCE"
    assert res.citations == []


def test_round8_zero_topic_anchor_blocks_fabricated_dormitory_and_allows_real_topics():
    from app.core.answer_checks import is_task_topic_unanchored

    ev_edu = (
        "Quy chế đào tạo tín chỉ 2026: Học bổng Loại Xuất sắc yêu cầu GPA >= 3,60 và điểm rèn luyện >= 90. "
        "Học phí CNTT-AI: 950.000 VNĐ/tín chỉ. Chuẩn đầu ra ngoại ngữ tối thiểu Bậc 3/6 (IELTS 4.5 / TOEIC 500)."
    )
    # Chủ đề vắng mặt 100% -> True (chặn bịa số)
    assert is_task_topic_unanchored(
        "Determine dormitory fee; Nghĩa vụ: Mức phí ở ký túc xá sinh viên mỗi tháng và lịch thi lại kỳ Hè 2026 là ngày nào?",
        ev_edu,
    ) is True
    # Chủ đề có thật trong tài liệu -> False (không false positive)
    assert is_task_topic_unanchored(
        "Find language standard; Nghĩa vụ: Chuẩn đầu ra ngoại ngữ tối thiểu để tốt nghiệp là gì?",
        ev_edu,
    ) is False
    assert is_task_topic_unanchored(
        "Check scholarship; Nghĩa vụ: Điều kiện GPA và điểm rèn luyện cho học bổng Xuất sắc là gì?",
        ev_edu,
    ) is False


def test_round9_law_code_year_in_refusal_sentence_not_flagged():
    from app.core.answer_checks import finish

    ans, bad = finish(
        "1. Chi phí bổ sung: **2.400.000** VNĐ.\n2. Hợp đồng không quy định mức phạt theo Nghị định 13/2023/NĐ-CP, không có trong hợp đồng này.",
        "Phí bổ sung 120.000 VNĐ/tài khoản. Số lượng: 20.",
        extra_known={"2400000"},
    )
    assert bad == []
    assert "Cần kiểm tra lại" not in ans
