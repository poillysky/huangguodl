# 单一镜像：前端 + FastAPI + 静态 ffmpeg（比 apt 全家桶瘦，amd64 稳）
FROM --platform=$BUILDPLATFORM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --prefer-offline --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 官方静态构建，体积远小于 apt ffmpeg 依赖树
FROM mwader/static-ffmpeg:7.1 AS ffmpeg

FROM python:3.12-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
RUN chmod +x /usr/local/bin/ffmpeg && ffmpeg -version | head -n 1

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY packages/core /app/packages/core
COPY backend/app /app/backend/app
COPY --from=frontend /fe/dist /app/static

ENV PYTHONPATH=/app/packages/core:/app/backend
ENV OUT_DIR=/data/downloads
ENV DATA_DIR=/data/config
ENV STATIC_DIR=/app/static
ENV HG_FFMPEG=/usr/local/bin/ffmpeg
ENV HOST=0.0.0.0
ENV PORT=8080

WORKDIR /app/backend
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
