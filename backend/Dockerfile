# Backend OrchestrIQ Studio cho máy chủ (dùng cùng docker/docker-compose.server.yml).
# Cùng phiên bản Python với máy phát triển (3.12) để kết quả kiểm thử còn đúng.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

# Mặc định giống scripts/dev/start-backend.ps1; compose ghi đè DATABASE_URL, OLLAMA_BASE_URL, COOKIE_SECURE.
ENV APP_STORAGE_BACKEND=postgres APP_ENV=production PROVIDER=ollama LOCAL_LLM_MODEL=qwen3:4b IMPLEMENTATION_PROFILE=m2 \
    PRODUCT_CONDITION=C MAX_OUTPUT_TOKENS=700 TASK_PLAN_MAX_OUTPUT_TOKENS=1400 VECTOR_BACKEND=qdrant VECTOR_INDEX_BACKEND=qdrant \
    VECTOR_INDEX_PATH=/data/qdrant CONTEXT_POLICY=adaptive_qwen EMBEDDING_BACKEND=ollama VECTOR_COLLECTION=domain_nomic

# chạy bằng người dùng thường, không phải root
RUN useradd --create-home --uid 10001 app && mkdir -p /data/qdrant && chown -R app /data /app
USER app
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
# cập nhật bảng trước rồi mới nhận yêu cầu; một tiến trình vì Qdrant nhúng chỉ cho một tiến trình mở thư mục chỉ mục
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
