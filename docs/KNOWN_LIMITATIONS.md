# Known limitations

- Gói không chứa Ollama model; `06_check_ollama.ps1` kiểm tra hoặc pull
  `qwen3:4b` từ Ollama local.
- Qdrant là embedded/local derived index. PostgreSQL vẫn là authoritative.
- Demo corpus là fixture không chuẩn tắc, dùng cho Midterm demo.
- Không bao gồm OCR, DOCX/PPTX, image-only PDF, cloud provider hoặc Sprint 4.
