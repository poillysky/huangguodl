# 单一镜像：前端静态资源 + FastAPI（同进程、同端口）
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt \
    && python -c "import imageio_ffmpeg; p=imageio_ffmpeg.get_ffmpeg_exe(); print('ffmpeg', p)"

COPY packages/core /app/packages/core
COPY backend/app /app/backend/app
COPY --from=frontend /fe/dist /app/static

ENV PYTHONPATH=/app/packages/core:/app/backend
ENV OUT_DIR=/data/downloads
ENV DATA_DIR=/data/config
ENV STATIC_DIR=/app/static
ENV HOST=0.0.0.0
ENV PORT=8080

WORKDIR /app/backend
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
