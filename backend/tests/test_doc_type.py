"""Đợt 3 (19/11): tự phân loại tài liệu khi tải lên — 6 loại chính trong tiêu chí "xong khi" và trường hợp không chắc."""
from app.ingestion.doc_type import DOC_TYPES, classify_document

CONTRACT = """CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc
HỢP ĐỒNG MUA BÁN MÁY CHIẾU
Số: 15/2026/HĐMB
Bên A (Bên mua): Trường Đại học X. Bên B (Bên bán): Công ty TNHH Y.
Điều 1. Đối tượng hợp đồng. Bên B bán cho Bên A 10 máy chiếu.
Điều 2. Giá trị hợp đồng và thanh toán. Hai bên thống nhất giá trị 200.000.000 đồng.
Điều 7. Phạt vi phạm: bên vi phạm chịu phạt 8% giá trị phần nghĩa vụ bị vi phạm."""

REGULATION = """TRƯỜNG ĐẠI HỌC DUY TÂN
QUY CHẾ ĐÀO TẠO ĐẠI HỌC
Chương I. Quy định chung
Điều 1. Phạm vi điều chỉnh: quy chế này áp dụng cho sinh viên hệ chính quy.
Điều 15. Học bổng khuyến khích: sinh viên có điểm trung bình học kỳ từ 3,2 và điểm rèn luyện từ 70."""

INTERNAL_RULES = """NỘI QUY LAO ĐỘNG CÔNG TY MẪU
Mục 3. Nghỉ phép năm: người lao động làm việc đủ 12 tháng được nghỉ phép năm 12 ngày.
Mục 4. Làm thêm giờ: không quá 40 giờ trong một tháng.
Mục 5. Thử việc: không quá 60 ngày."""

TRANSCRIPT = """## Sheet1
STT | MSSV | Họ và tên | ĐTB học kỳ | Điểm rèn luyện | Xếp loại
1 | 2711001 | Nguyễn Văn A | 3,45 | 82 | Giỏi
2 | 2711002 | Trần Thị B | 2,90 | 75 | Khá"""

LEGAL_DOC = """ỦY BAN NHÂN DÂN TỈNH QUẢNG NAM
Số: 12/2020/QĐ-UBND
CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
QUYẾT ĐỊNH
Ban hành quy định về cấp giấy phép xây dựng biển quảng cáo
Căn cứ Luật Tổ chức chính quyền địa phương; Căn cứ Luật Quảng cáo năm 2012;
Điều 1. Ban hành kèm theo Quyết định này quy định về cấp phép.
Điều 3. Quyết định này có hiệu lực kể từ ngày 01/03/2020."""

SPEC = """ĐẶC TẢ YÊU CẦU PHẦN MỀM - Cổng thanh toán PayNhanh
FR-01: Hệ thống shall chống trừ tiền hai lần bằng khóa idempotency.
FR-02: Xác thực chữ ký webhook trước khi xử lý.
NFR-01: Thời gian phản hồi API dưới 300 ms ở phân vị 95."""


def test_six_main_document_types():
    assert classify_document("hd_may_chieu.docx", CONTRACT) == "contract"
    assert classify_document("quy_che_dao_tao.pdf", REGULATION) == "regulation"
    assert classify_document("noi-quy-mau.txt", INTERNAL_RULES) == "internal_rules"
    assert classify_document("diem_k27.xlsx", TRANSCRIPT) == "transcript"
    assert classify_document("qd_12_2020.pdf", LEGAL_DOC) == "legal_doc"
    assert classify_document("srs.md", SPEC) == "software_spec"


def test_file_name_alone_does_not_override_strong_body():
    # tên tệp chung chung, nội dung là hợp đồng
    assert classify_document("tai_lieu_1.docx", CONTRACT) == "contract"


def test_unsure_falls_back_to_other_instead_of_guessing():
    assert classify_document("ghi_chu.txt", "Họp nhóm thứ Ba, nhớ mang laptop.") == "other"
    assert classify_document("empty.txt", "") == "other"


def test_lecture_and_labels_complete():
    lecture = "BÀI GIẢNG CƠ SỞ DỮ LIỆU\nChương 2. Mô hình quan hệ\nMục tiêu bài học: hiểu khóa chính, khóa ngoại.\nVí dụ: bảng SinhVien."
    assert classify_document("csdl_chuong2.pdf", lecture) == "lecture"
    assert set(DOC_TYPES) >= {"contract", "regulation", "internal_rules", "transcript", "legal_doc", "software_spec", "other"}


# ---------------- lưu nhãn, sửa nhãn, tài liệu cũ chưa có nhãn
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.storage.postgres.base import Base
from app.storage.postgres.models import KnowledgeSourceRecord, UserRecord
from app.storage.postgres.runtime import PostgresSourceStore


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.create_function("btrim", 1, lambda v: None if v is None else v.strip()))
    Base.metadata.create_all(engine)
    f = sessionmaker(engine, expire_on_commit=False)
    with f.begin() as s:
        s.add_all([UserRecord(user_id=u, email=f"{u}@x.vn", display_name=u, password_hash="x") for u in ("an", "binh")])
    return f


def test_label_saved_on_upload_and_user_edit_survives_reimport(factory):
    store = PostgresSourceStore(factory, "an")
    sid = store.import_text("hd.docx", CONTRACT)["source_id"]
    assert store.list_sources()[0]["doc_type"] == "contract"
    assert store.set_doc_type(sid, "legal_doc")["doc_type_by"] == "user"
    store.import_text("hd.docx", CONTRACT)  # nạp lại cùng tệp
    assert store.list_sources()[0]["doc_type"] == "legal_doc"


def test_only_uploader_can_edit_and_value_is_checked(factory):
    sid = PostgresSourceStore(factory, "an").import_text("nq.txt", INTERNAL_RULES)["source_id"]
    with pytest.raises(LookupError):
        PostgresSourceStore(factory, "binh").set_doc_type(sid, "other")
    with pytest.raises(ValueError):
        PostgresSourceStore(factory, "an").set_doc_type(sid, "bogus")


def test_old_documents_get_labelled_once_when_listed(factory):
    store = PostgresSourceStore(factory, "an")
    sid = store.import_text("srs.md", SPEC)["source_id"]
    with factory.begin() as s:  # giả lập tài liệu nạp trước đợt 3
        src = s.get(KnowledgeSourceRecord, sid)
        src.display_metadata = {k: v for k, v in src.display_metadata.items() if not k.startswith("doc_type")}
    assert store.list_sources()[0]["doc_type"] == "software_spec"
    with factory() as s:
        assert s.get(KnowledgeSourceRecord, sid).display_metadata["doc_type_by"] == "auto"


def test_internal_policy_not_mistaken_for_legal_doc():
    """P2-2 (20/11): chính sách, quy trình, sổ tay nội bộ của công ty không phải văn bản pháp quy của Nhà nước."""
    policy = "# CHÍNH SÁCH BẢO MẬT THÔNG TIN – CÔNG TY X\nSố: 03/2025/QĐ-X. Quyết định có hiệu lực từ ngày 01/01/2025, thay thế bản cũ.\nMật khẩu tối thiểu 12 ký tự."
    assert classify_document("04_Chinh_sach_bao_mat.md", policy) == "internal_policy"
    assert classify_document("so_tay_nhan_vien.md", "# SỔ TAY NHÂN VIÊN MỚI\nTuần đầu: nhận máy, đọc quy chuẩn.") == "internal_policy"
    assert classify_document("quy_trinh_su_co.md", "# QUY TRÌNH XỬ LÝ SỰ CỐ\n1. Phát hiện\n2. Khoanh vùng") == "internal_policy"
    state = "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nNGHỊ ĐỊNH\nCăn cứ Luật Tổ chức Chính phủ; Số: 13/2023/NĐ-CP. Có hiệu lực từ ngày 01/07/2023."
    assert classify_document("nd_13_2023.pdf", state) == "legal_doc"
    assert classify_document("kien_truc.md", "# KIẾN TRÚC HỆ THỐNG VÀ HẠ TẦNG\nCác dịch vụ chạy trên Kubernetes.") == "software_spec"


def test_stale_auto_labels_are_relabelled_but_user_labels_kept(factory):
    """Đổi luật phân loại (P2-2): nhãn máy gán theo bản cũ được phân loại lại một lần; nhãn người dùng sửa thì giữ."""
    store = PostgresSourceStore(factory, "an")
    policy = "# CHÍNH SÁCH BẢO MẬT\nMật khẩu tối thiểu 12 ký tự, đổi định kỳ."
    old = store.import_text("chinh_sach.md", policy)["source_id"]
    mine = store.import_text("hd.docx", CONTRACT)["source_id"]
    store.set_doc_type(mine, "other")
    with factory.begin() as s:  # giả lập nhãn gán theo luật cũ (chưa có phiên bản)
        src = s.get(KnowledgeSourceRecord, old)
        src.display_metadata = {**{k: v for k, v in src.display_metadata.items() if k != "doc_type_v"}, "doc_type": "legal_doc", "doc_type_by": "auto"}
    labels = {r["source_id"]: r["doc_type"] for r in store.list_sources()}
    assert labels[old] == "internal_policy" and labels[mine] == "other"
