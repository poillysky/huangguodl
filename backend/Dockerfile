FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
# imageio-ffmpeg 随 pip 带平台二进制；构建时预热，避免容器首次下载
RUN pip install --no-cache-dir -r /app/backend/requirements.txt \
    && python -c "import imageio_ffmpeg; p=imageio_ffmpeg.get_ffmpeg_exe(); print('ffmpeg', p)"

COPY packages/core /app/packages/core
COPY backend/app /app/backend/app

ENV PYTHONPATH=/app/packages/core:/app/backend
ENV OUT_DIR=/data/downloads
ENV DATA_DIR=/data/config
ENV HOST=0.0.0.0
ENV PORT=8000
# 不依赖宿主机 ffmpeg；如需覆盖才设 HG_FFMPEG

WORKDIR /app/backend
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
