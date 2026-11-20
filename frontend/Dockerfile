# Giao diện OrchestrIQ Studio cho máy chủ: build bằng Node rồi phục vụ bằng nginx (chuyển /api sang backend).
FROM node:22-alpine AS build
WORKDIR /src
# chạy thật 20/11: npm ci lỗi ENETUNREACH vì Node ưu tiên IPv6 mà mạng Docker không có IPv6 → ưu tiên IPv4, thử lại khi mạng chập chờn
ENV NODE_OPTIONS=--dns-result-order=ipv4first
COPY package.json package-lock.json ./
RUN npm ci --fetch-retries=5 --fetch-retry-mintimeout=5000
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
