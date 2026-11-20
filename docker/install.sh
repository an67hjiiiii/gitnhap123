#!/usr/bin/env bash
# Bộ cài OrchestrIQ Studio cho máy chủ Linux có Docker (đợt 10): kiểm tra phần cứng, tạo docker/.env, bật hệ thống, tải mô hình.
# Dùng (trong thư mục gốc dự án):
#   bash docker/install.sh               # cài (Ollama chạy trong Docker)
#   bash docker/install.sh --dry-run     # chỉ kiểm tra, không đổi gì
# Không tải phần mềm nào ngoài ảnh Docker của dự án và mô hình Ollama; Docker phải cài sẵn.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DRY=0; WEB_PORT=8080
for a in "$@"; do case "$a" in --dry-run) DRY=1 ;; --port=*) WEB_PORT="${a#*=}" ;; esac; done
step() { printf '\n== %s\n' "$1"; }

step "1/5 Kiểm tra Docker"
command -v docker >/dev/null || { echo "Chưa có Docker. Cài Docker Engine rồi chạy lại."; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker chưa chạy hoặc tài khoản chưa có quyền dùng Docker."; exit 1; }
echo "Docker sẵn sàng."

step "2/5 Kiểm tra phần cứng và gợi ý mô hình"
RAM_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 0)
CPU=$(nproc 2>/dev/null || echo "?")
VRAM_GB=0
if command -v nvidia-smi >/dev/null; then
  VRAM_GB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | awk '{s+=$1} END {printf "%d", s/1024}')
fi
echo "RAM: ${RAM_GB} GB · CPU: ${CPU} luồng · GPU NVIDIA: ${VRAM_GB} GB VRAM"
MODEL="qwen3:4b"  # mô hình mặc định đã được nhóm kiểm thử
[ "$RAM_GB" -lt 8 ] && echo "Cảnh báo: RAM dưới 8 GB, qwen3:4b sẽ chậm; nên dùng máy từ 16 GB RAM."
if [ "$VRAM_GB" -ge 12 ] && [ "$DRY" -eq 0 ]; then
  read -r -p "Máy có GPU từ 12 GB VRAM. Dùng qwen3:8b (tốt hơn, chưa được nhóm kiểm thử)? (c/K) " ans
  case "$ans" in c|C) MODEL="qwen3:8b" ;; esac
fi
echo "Mô hình sẽ dùng: $MODEL"

step "3/5 Tạo cấu hình docker/.env"
ENV_FILE="$HERE/.env"
if [ -f "$ENV_FILE" ]; then echo "Đã có docker/.env, giữ nguyên."
elif [ "$DRY" -eq 1 ]; then echo "(thử) Sẽ tạo docker/.env với mật khẩu CSDL ngẫu nhiên."
else
  PW=$(LC_ALL=C tr -dc 'A-HJ-NP-Za-km-z2-9' </dev/urandom | head -c 24)
  umask 077
  printf 'POSTGRES_PASSWORD=%s\nWEB_PORT=%s\nOLLAMA_BASE_URL=http://ollama:11434\nCOOKIE_SECURE=false\nLOCAL_LLM_MODEL=%s\n' "$PW" "$WEB_PORT" "$MODEL" >"$ENV_FILE"
  echo "Đã tạo docker/.env (mật khẩu CSDL ngẫu nhiên, không in ra màn hình)."
fi

COMPOSE=(docker compose -f "$HERE/docker-compose.server.yml" --profile ollama)
step "4/5 Bật hệ thống"
if [ "$DRY" -eq 1 ]; then echo "(thử) ${COMPOSE[*]} up -d --build"; else "${COMPOSE[@]}" up -d --build; fi

step "5/5 Tải mô hình và chờ sẵn sàng"
if [ "$DRY" -eq 1 ]; then echo "(thử) ollama pull $MODEL ; ollama pull nomic-embed-text"; exit 0; fi
"${COMPOSE[@]}" exec -T ollama ollama pull "$MODEL"
"${COMPOSE[@]}" exec -T ollama ollama pull nomic-embed-text
for _ in $(seq 1 60); do curl -fs "http://localhost:$WEB_PORT/api/health" >/dev/null && break; sleep 3; done
echo "Xong. Mở http://<máy chủ>:$WEB_PORT ; tạo tài khoản đầu tiên rồi cấp quyền quản trị (scripts/dev/make-admin.ps1 hoặc lệnh SQL trong tài liệu chạy)."
