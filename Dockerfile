# 单一镜像：前端 + FastAPI + 系统 ffmpeg
# 前端阶段固定在构建机原生架构，避免为 arm64 目标在慢速模拟里跑 npm
FROM --platform=$BUILDPLATFORM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --prefer-offline --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && ffmpeg -version | head -n 1

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY packages/core /app/packages/core
COPY backend/app /app/backend/app
COPY --from=frontend /fe/dist /app/static

ENV PYTHONPATH=/app/packages/core:/app/backend
ENV OUT_DIR=/data/downloads
ENV DATA_DIR=/data/config
ENV STATIC_DIR=/app/static
ENV HG_FFMPEG=/usr/bin/ffmpeg
ENV HOST=0.0.0.0
ENV PORT=8080

WORKDIR /app/backend
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
