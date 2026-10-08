# 不需要往这里放二进制

部署（含 NAS / Docker）请用 pip 依赖 **`imageio-ffmpeg`**，已写在 `backend/requirements.txt`。

```bash
pip install -r backend/requirements.txt
python tools/ensure_ffmpeg.py
```

本目录仅作遗留占位；请勿依赖本机 `apt/brew` 安装的 ffmpeg。
