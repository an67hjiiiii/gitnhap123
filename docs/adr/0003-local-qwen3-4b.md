# ADR 0003: Qwen3:4B local qua Ollama

## Context

Ollama provider mặc định model `qwen3:4b`, có thể cấu hình qua
`LOCAL_LLM_MODEL`; endpoint mặc định là Ollama local.
Các pipeline cần output có cấu trúc để xử lý máy đọc được.

## Decision

Dùng Qwen3:4B local qua Ollama làm model mặc định của provider.
Payload chat đặt `think: false` và `stream: false`.
Với các tác vụ nhận diện trong provider, yêu cầu JSON qua `format: "json"`;
với lời gọi structured, truyền JSON schema trong `format`.
Timeout mặc định của provider là 180 giây.

## Consequences

Gói không kèm model; cần Ollama cài model tại máy vận hành.
Gọi Ollama được thực hiện tuần tự trong từng request của provider; giới hạn
đồng thời toàn hệ thống: chưa xác minh.
Đo đạc được báo cáo ngoài repository về cold start khoảng 10–16 giây và
warm call khoảng 4–5 giây: chưa xác minh tại đây, chỉ tham khảo.
Điều kiện C cần tối thiểu 4 lần gọi theo yêu cầu thử nghiệm; bằng chứng
triển khai hoặc cấu hình cho yêu cầu này: chưa xác minh.

## Status

Accepted cho cấu hình provider; số đo và yêu cầu condition C nêu trên
chưa được xác minh bằng repository.

