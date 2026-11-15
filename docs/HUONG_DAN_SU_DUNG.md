# Hướng dẫn sử dụng OrchestrIQ Studio

OrchestrIQ Studio là nền tảng đa tác tử (Multi-Agent RAG) chạy hoàn toàn trên máy của bạn. Ba tác tử chuyên môn (Cơ sở dữ liệu, API và kiến trúc, Bảo mật) đọc tài liệu kỹ thuật của dự án và giúp nhóm phát triển phần mềm: hỏi đáp có dẫn nguồn, truy vết yêu cầu, sinh thiết kế, rà soát bảo mật, phát hiện mâu thuẫn và đánh giá chất lượng có kiểm định thống kê. Tài liệu và câu hỏi không rời khỏi máy.

Cài đặt và chạy: xem `docs/HUONG_DAN_CHAY_DU_AN.md`.

## Bắt đầu trong 5 phút

1. Đăng nhập, vào **Không gian làm việc**, tạo một không gian cho dự án (ví dụ "Cổng thanh toán").
2. Tải tài liệu lên (PDF có lớp chữ, Markdown, TXT, SQL; tối đa 2 MB mỗi tệp) hoặc bấm **⋯ → Nạp tài liệu mẫu** để có bộ 7 tài liệu của một cổng thanh toán giả định (PayNhanh): đặc tả yêu cầu, thiết kế CSDL, đặc tả API, chính sách bảo mật, quy trình sự cố, kiến trúc, sổ tay kỹ sư.
3. Thử lần lượt các mục ở thanh bên trái. Mọi chức năng đều chạy được trên bộ tài liệu mẫu.

## Các chức năng

**Mở Studio:** lần đầu vào trong một phiên trình duyệt có màn mở đầu ngắn (Robot C27 chào và ba tác tử sáng lần lượt); bấm hoặc nhấn phím bất kỳ để vào ngay. Ở mỗi trang, Robot C27 ở góc dưới bên phải giới thiệu trang đó làm gì, bạn được gì và bắt đầu thế nào (tự mở ở lần đầu, các lần sau bấm vào robot để xem lại).

**Thao tác nhanh:** nhấn **Ctrl + K** (macOS: ⌘ + K) hoặc ô **Tìm nhanh** trên thanh bên để mở bảng lệnh: gõ tên trang, cuộc trò chuyện gần đây hoặc thao tác (cuộc trò chuyện mới, nạp bộ tài liệu mẫu) rồi nhấn Enter. Nút **mặt trời / mặt trăng** ở cuối thanh bên chuyển giao diện sáng hoặc tối; lựa chọn được nhớ trên trình duyệt đó.

### 1. Không gian làm việc: hỏi đáp có dẫn nguồn
- **Hỏi nhanh**: trả lời ngắn trong vài giây, mỗi ý có nút nguồn mở đúng đoạn tài liệu gốc. Hỏi tiếp được, hệ thống nhớ ngữ cảnh cuộc trò chuyện: câu hỏi tiếp nối ngắn ("Mất bao lâu?", "Còn hoàn tiền thì sao?", "Làm sao cho an toàn?") được hiểu theo câu hỏi ngay trước, và câu trả lời ghi rõ *Hiểu tiếp theo: "…"*. Câu trước chỉ dùng để hiểu ý, không bao giờ được tính là nguồn.
- **Phân tích (A/B/C)**: C là điều phối đầy đủ (lập kế hoạch có kiểm tra, chia việc cho tác tử, phân bổ ngữ cảnh). Nút **8 bước** cho xem từng bước hệ thống đã làm; **Theo tác tử** cho xem phần của từng tác tử.
- Khi kế hoạch của cách C không qua bước tự kiểm tra, lượt đó vẫn được ghi lại và hệ thống tự trả lời lại bằng Hỏi nhanh.
- Câu hỏi chỉ tìm trong tài liệu của không gian đang mở. Khi đến từ **Hồ sơ tài liệu → Hỏi ngay**, khung hỏi ghi "Chỉ hỏi trong <tài liệu>"; bấm **Hỏi cả kho** để bỏ giới hạn.
- **Kiểm chứng** (dưới mỗi câu trả lời có bằng chứng): đối chiếu từng câu với các đoạn tài liệu lượt đó đã đọc, tô màu *Có căn cứ* / *Cần kiểm tra* / *Chưa thấy căn cứ*, kèm nút mở đoạn khớp nhất. Chạy tại máy, không gọi mô hình; câu diễn đạt lại có thể bị xếp "Cần kiểm tra", đây là công cụ hỗ trợ đọc, không phải kết luận đúng sai.
- **👍 / 👎**: đánh giá câu trả lời; khi chọn 👎 có thể ghi góp ý. Bấm lại để bỏ đánh giá. Tỷ lệ hữu ích hiện ở trang Tổng quan; quản trị viên xem câu hỏi, câu trả lời và góp ý đã đánh giá ở **Cơ sở dữ liệu → Phản hồi người dùng**.
- **Đọc to**: trình duyệt đọc câu trả lời thành tiếng (cần giọng đọc tiếng Việt cài trong máy; nếu không có, trình duyệt dùng giọng mặc định).
- **Hỏi bằng giọng nói**: bấm nút micro rồi nói; khi hỏi bằng giọng nói, câu trả lời được đọc to tự động. Nhận dạng giọng nói do trình duyệt thực hiện: Chrome và Edge có thể gửi âm thanh lên máy chủ của họ để nhận dạng, nên không dùng cho nội dung mật. Trình duyệt không hỗ trợ thì nút micro không hiện.
- **Báo cáo**: mô hình cục bộ viết câu trả lời và các đoạn tài liệu đã dùng thành báo cáo có cấu trúc (tóm tắt, các mục, khuyến nghị, nguồn tham khảo lấy từ đoạn thật), tải **Word (.docx)**, **PDF** (mở hộp thoại in, chọn *Lưu thành PDF*) hoặc .md. Mất khoảng 10–60 giây; báo cáo cần người kiểm tra trước khi dùng chính thức.
- Màn hình đầu hiện **Gợi ý từ hồ sơ tài liệu** khi tài liệu trong không gian đã được lập hồ sơ. Chưa có gợi ý thì có nút **Gợi ý câu hỏi nên hỏi về <tài liệu>** (ưu tiên tài liệu vừa nạp).
- Ngay sau khi nạp tài liệu, hệ thống kiểm tra chất lượng và báo nếu tài liệu trùng tài liệu khác, quá ít nội dung, lỗi mã hóa hoặc không đọc được chữ.

### 2. Truy vết yêu cầu
**Giải quyết:** đặc tả có hàng chục yêu cầu; dò tay xem thiết kế đã đáp ứng chưa mất nhiều giờ và hay sót.
1. Chọn tài liệu đặc tả và các tài liệu thiết kế, bấm **Trích yêu cầu**. Hệ thống nhận các dòng bắt đầu bằng mã FR-, NFR-, UC-, REQ-, BR-, SR-, SEC-.
2. Bấm **Kiểm tra**: mỗi yêu cầu được giao cho tác tử đúng chuyên môn, tìm đoạn liên quan và kết luận *Đã đáp ứng / Một phần / Chưa có trong thiết kế* kèm điểm đã có, điểm còn thiếu và trích dẫn.
3. Duyệt lại từng dòng ở cột **Người duyệt**, rồi **Lưu báo cáo**, **Xuất CSV** (mở được bằng Excel) hoặc **Xuất Markdown**.

Quy tắc trung thực (tự động): kết luận "đáp ứng" phải có trích dẫn hợp lệ; còn điểm thiếu thì chỉ là "một phần"; yêu cầu có con số (300 ms, 99,9%, 5 năm) thì đoạn được trích phải chứa đủ các con số đó.

### 3. Gói thiết kế kỹ thuật
**Giải quyết:** biến một yêu cầu tính năng thành thiết kế CSDL, API và bảo mật nhất quán, bám quy ước sẵn có của dự án.
1. Nhập yêu cầu tính năng (hoặc chọn ví dụ), chọn tài liệu tham chiếu, bấm **Tạo gói thiết kế**.
2. Quy trình 5 bước chạy liên tiếp, mỗi bước ghi thời gian và token: phân tích ý chính → tác tử CSDL → tác tử API → tác tử Bảo mật → kiểm tra độ phủ. Mỗi tác tử tìm tài liệu riêng và ưu tiên đoạn tác tử trước chưa dùng (phân bổ ngữ cảnh có xét trùng lặp).
3. Xem từng tab: bảng và cột, endpoint, biện pháp bảo mật và phân quyền. Mỗi mục ghi rõ **Có căn cứ** (kèm đoạn tài liệu) hay **Đề xuất mới**.
4. Tab **Bản nháp xuất**: SQL (PostgreSQL) và OpenAPI 3.0 đã chuẩn hóa cú pháp, sao chép hoặc tải tệp. Xuất toàn bộ gói ra Markdown hoặc lưu lại.

### 4. Rà soát bảo mật
**Giải quyết:** rà soát tài liệu thiết kế theo 32 tiêu chí chọn lọc từ OWASP ASVS 4.0.3 (xác thực, phiên, kiểm soát truy cập, đầu vào, mật mã, nhật ký, bảo vệ dữ liệu, truyền tải, API, SSRF, cấu hình).
- Chọn tài liệu cần rà soát, bấm **Kiểm tra**. Kết luận: *Đạt / Đạt một phần / Chưa thấy biện pháp*, kèm trích dẫn.
- Mỗi tiêu chí có thuật ngữ cốt lõi (ví dụ HttpOnly, HSTS); đoạn được trích không chứa thuật ngữ đó thì không được kết luận "Đạt".
- Danh mục chọn lọc để rà soát tài liệu, không thay thế đánh giá chứng nhận ASVS đầy đủ.

### 5. Kiểm tra mâu thuẫn
**Giải quyết:** tài liệu do nhiều người viết hay nói khác nhau về cùng một quy định (thời gian khóa tài khoản, thời hạn lưu nhật ký, giới hạn tần suất).
1. Chọn từ hai tài liệu trở lên, bấm **Tìm cặp nghi vấn**: hệ thống quét các câu có tính quy định và ghép cặp câu cùng chủ đề nhưng khác con số hoặc khác phủ định (không dùng mô hình, chạy ngay).
2. Bấm **Để tác tử xét**: mỗi cặp được kết luận *Mâu thuẫn / Nhất quán / Chưa xác nhận*. Chỉ xung đột con số có thật trong hai câu và cùng phạm vi mới được tự xác nhận là mâu thuẫn; các trường hợp khác hiện ra để người duyệt quyết.

### 6. Phòng đánh giá
**Giải quyết:** chứng minh bằng số liệu cách làm nào tốt hơn (chất lượng, token, độ trễ), đúng phương pháp thực nghiệm.
1. **Bộ câu hỏi**: soạn câu hỏi kèm ý chính cần có (hoặc nạp bộ mẫu PayNhanh 10 câu để chạy thử). Lưu bộ câu hỏi để dùng lại.
2. **Chạy thực nghiệm**: chọn điều kiện (A, B, C và các biến thể bỏ thành phần C-P, C-N, C-O), số lần lặp, tài liệu. Các điều kiện chạy xen kẽ theo từng câu; mọi lượt lưu vết như một lượt nghiên cứu; dừng giữa chừng rồi chạy tiếp được.
3. **Chấm mù**: người chấm thấy câu trả lời đã xáo trộn, không biết của phương pháp nào, chấm 1–5 theo Đúng, Đủ ý, Có căn cứ. Nhiều người chấm dùng tên riêng.
4. **Kết quả**: theo từng điều kiện có tỷ lệ hoàn thành, độ trễ, token, số lần gọi mô hình, độ phủ ý chính tự động và điểm người chấm; so sánh cặp theo câu hỏi bằng kiểm định Wilcoxon, khoảng tin cậy 95%, cỡ hiệu ứng (rank-biserial, Cohen's dz). Xuất CSV dữ liệu thô và JSON đầy đủ.

Lưu ý phương pháp: bộ chính thức nên có ít nhất 20 câu, ý chính do nhóm viết, tách phần held-out; độ phủ tự động chỉ là chỉ số phụ, kết luận chất lượng dựa trên điểm người chấm.

### 7. Hồ sơ tài liệu
Chọn một tài liệu rồi bấm **Lập hồ sơ**. Phần chạy tại máy xong trong vài giây; phần do mô hình cục bộ viết mất khoảng nửa phút đến một phút. Hồ sơ được lưu, lần sau mở lại ngay. **Đọc toàn văn** và **Sơ đồ tư duy** dùng được ngay, không cần lập hồ sơ.
- **Đọc toàn văn**: xem toàn bộ tài liệu. Bôi đen một từ hoặc một đoạn khó hiểu rồi bấm **Giải thích**: mô hình cục bộ giải thích bằng lời dễ hiểu, kèm ví dụ, dựa trên đoạn xung quanh. Cột bên phải liệt kê **tài liệu liên quan**; bấm vào để đọc tiếp tài liệu đó, **Quay lại** để về tài liệu trước.
- **Sơ đồ tư duy**: hai cách. *Theo cấu trúc* dựng ngay từ đề mục và gạch đầu dòng, đúng thứ tự gốc, chạy tại máy. *AI tóm lược* để mô hình cục bộ gom ý thành 4–7 nhánh chủ đề và nối các ý liên quan giữa các nhánh bằng nét đứt (khoảng 20–40 giây, được lưu để mở lại). Kéo để di chuyển, Ctrl + cuộn (hoặc nút +/−) để phóng to, bấm nút tròn để thu/mở nhánh, bấm một nút để xem vị trí và **Xem đoạn nguồn**. Tải **PNG** hoặc **SVG**, xem **toàn màn hình**.
- **Kiểm tra cả kho** (góc phải trên): điểm chất lượng từng tài liệu, các cặp tài liệu gần như trùng nhau, tài liệu không đọc được chữ (bản scan), quá ngắn, lỗi mã hóa, thiếu đề mục.
- **Tổng quan**: tóm tắt, ý chính, loại tài liệu; số từ, đoạn, đề mục, mã yêu cầu.
- **Thuật ngữ**: lấy định nghĩa có sẵn trong tài liệu (nhãn *Trong tài liệu*); từ kỹ thuật lặp lại mà tài liệu chưa định nghĩa thì mô hình giải thích dựa trên câu ngữ cảnh (nhãn *Mô hình giải thích*, cần người duyệt).
- **Câu hỏi gợi ý**: câu hỏi trả lời được từ tài liệu, kèm đoạn chứa câu trả lời; **Hỏi ngay** chuyển sang Không gian làm việc và chỉ hỏi trong tài liệu đó.
- **Liên quan**: tài liệu cùng chủ đề (độ trùng từ ngữ) và các từ chung; bấm tên hoặc **Đọc toàn văn** để mở tài liệu đó.
- **Chất lượng & riêng tư**: điểm chất lượng (quá ngắn, lỗi mã hóa, đoạn trùng, trùng tài liệu khác, thiếu đề mục) và danh sách email, số điện thoại, CCCD/CMND, số tài khoản, số thẻ (kiểm tra Luhn), khóa bí mật. Giá trị chỉ hiện dạng đã che; **Tải bản đã che** tải tệp thay mỗi giá trị bằng [ĐÃ CHE].
- **So sánh phiên bản**: chọn bản mới (nạp thành tài liệu riêng); hệ thống so từng dòng (thêm, bỏ, sửa, kèm đề mục) và mô hình tóm tắt thay đổi. Nếu hai tài liệu giống nhau dưới 30% sẽ có cảnh báo có thể không phải hai phiên bản. Tải danh sách thay đổi dạng CSV.
- Tải hồ sơ dạng **Word**, **PDF** hoặc **.md** để gửi cho người khác.

### 8. Tổng quan
Số liệu sử dụng thật của tài khoản: số tài liệu, số lượt hỏi và phân tích, tỷ lệ đủ bằng chứng, token và thời gian trả lời trung bình, tỷ lệ hữu ích từ 👍/👎, lượt chạy theo cách trả lời, tài liệu được trích dẫn nhiều nhất, báo cáo đã lưu. Chưa có dữ liệu thì hiện "Chưa đo"/"Chưa có".
- **Chủ đề được hỏi nhiều**: cụm từ trong câu hỏi 7 ngày qua, so với 7 ngày trước (mũi tên tăng/giảm, "mới"). Từ ghép tiếng Việt được tách theo cách viết trong kho tài liệu.
- **Lượt hỏi mỗi ngày** trong 14 ngày và **Tài liệu chưa được dùng** (chưa được trích dẫn trong các lượt gần nhất).
**Nhật ký hoạt động** ghi thao tác: nạp/xóa tài liệu, đặt câu hỏi, chạy công cụ phân tích, lập hồ sơ, so sánh, lưu/xóa báo cáo, đánh giá câu trả lời (không ghi nội dung câu hỏi). Tải nhật ký dạng CSV.

### 9. Thực nghiệm
So sánh nhanh A/B/C trên một câu hỏi: trạng thái, độ trễ, token, số lệnh gọi mô hình, số nhiệm vụ và tác tử, token ngữ cảnh, số đoạn truy xuất/giữ/loại, % CPU toàn máy, RAM backend/GPU. Xem nhật ký mọi lượt chạy và cấu hình đang chạy (`config_hash` để tái lập).

### 10. Chấm mù
Đánh giá chất lượng bằng người chấm độc lập, không biết câu trả lời do cách nào (A, B hay C) tạo ra.
- **Người tạo đợt**: chạy một lượt ở Phòng đánh giá rồi lưu, vào **Chấm mù → Tạo đợt chấm**, chọn lượt đánh giá đó, nhận **mã 6 ký tự** và gửi cho người chấm. Người tạo đợt không chấm được đợt của mình (để giữ tính mù).
- **Người chấm** (tài khoản riêng): **Chấm mù → nhập mã → Bắt đầu chấm**. Mỗi câu: đánh dấu các ý chính câu trả lời có nêu đúng; chấm Đúng, Đủ ý, Có căn cứ, Hữu ích từ 1 đến 5; đánh dấu nếu có thông tin sai hoặc bịa; ghi chú nếu cần. Thứ tự câu được xáo riêng cho từng người; sửa lại điểm lúc nào cũng được.
- **Kết quả**: điểm theo từng cách, so sánh C với các cách khác theo cặp câu hỏi (Wilcoxon, Cohen dz), độ đồng thuận giữa người chấm (Krippendorff alpha) và mức khớp giữa người chấm với máy chấm ý chính tự động. Tải CSV. Lượt chạy thất bại không đưa cho người chấm; khi so sánh được tính điểm thấp nhất.
- Cần ít nhất 2 người chấm để có độ đồng thuận; nên thống nhất cách chấm trên vài câu thử trước.

### 11. Chất lượng yêu cầu
Soát từng yêu cầu có mã (FR-01, NFR-02, UC-03...) theo các đặc tính của ISO/IEC/IEEE 29148: rõ nghĩa, kiểm chứng được, đơn nhất, đầy đủ, khả thi, không trùng, đúng quy ước viết.
- Chọn tài liệu đặc tả → **Soát chất lượng**. Kết quả có ngay (không gọi mô hình), cùng tài liệu luôn cho cùng kết quả.
- Mỗi vấn đề chỉ ra đúng cụm chữ (được tô vàng trong nội dung), thuộc đặc tính nào và cách sửa. Ba mức: **Lỗi** (còn TBD), **Cảnh báo** (từ mơ hồ, yêu cầu chất lượng thiếu con số, gộp nhiều nghĩa vụ, "nên"/should, liệt kê "v.v.", trùng yêu cầu khác), **Lưu ý** (từ tuyệt đối, câu quá dài, "như trên"). Yêu cầu "đạt" là không có lỗi và cảnh báo.
- Bấm một nhóm ở **Vấn đề theo đặc tính** để lọc. Tải CSV, lưu báo cáo.
- **Đề xuất viết lại** (gọi mô hình cục bộ): yêu cầu được tách thành từng nghĩa vụ bằng luật, mô hình viết lại từng nghĩa vụ. Mô hình bị cấm tự đặt con số; chỗ cần số được để trống dạng `[cần xác định: ...]` kèm câu hỏi cho tác giả. Bản viết lại được soát lại bằng cùng bộ luật: còn từ mơ hồ thì báo ra, số nào mô hình tự thêm được tô đỏ. Đây là gợi ý, người viết vẫn phải duyệt.
- Giới hạn: luật dựa trên từ ngữ nên không hiểu nghĩa sâu (ví dụ không biết hai yêu cầu mâu thuẫn nhau; việc đó thuộc **Kiểm tra mâu thuẫn**). Trên tài liệu mẫu PayNhanh (20 yêu cầu, viết tốt) không có báo động nhầm; trên tài liệu khác có thể có, nên đọc lý do trước khi sửa.

### 12. Người dùng (chỉ quản trị viên)
Tạo tài khoản cho nhân viên (để trống mật khẩu thì hệ thống tạo mật khẩu tạm, chỉ hiện một lần), cấp/bỏ quyền quản trị, khóa tài khoản khi người dùng nghỉ việc (bị đăng xuất ngay, dữ liệu giữ nguyên), đặt lại mật khẩu tạm, đăng xuất mọi phiên. Không thể tự hạ quyền hay tự khóa mình; hệ thống luôn giữ ít nhất một quản trị viên đang hoạt động. Mọi thao tác được ghi vào nhật ký hoạt động.

## Báo cáo đã lưu
Mọi chức năng phân tích có nút **Lưu báo cáo** và ô **Mở báo cáo đã lưu**. Báo cáo lưu trong cơ sở dữ liệu cục bộ, chỉ chủ tài khoản xem được.

## Giới hạn cần biết
- Hệ thống chưa nhận dạng chữ trong ảnh (OCR): PDF dạng ảnh scan được báo là không đọc được chữ.
- Mô hình cục bộ qwen3:4b có thể kết luận sai; các quy tắc trung thực hạ bớt kết luận thiếu căn cứ nhưng người dùng vẫn cần duyệt.
- Tìm kiếm trong các chức năng phân tích dùng BM25 kết hợp vector; hỏi đáp A/B/C dùng truy xuất gốc của phương pháp nghiên cứu.
- Thời gian chạy phụ thuộc máy: trên máy thử (GPU khoảng 4 GB bộ nhớ dùng cho mô hình), truy vết 20 yêu cầu mất khoảng 2 phút, gói thiết kế dưới 1 phút, rà soát 32 tiêu chí khoảng 2 phút.
