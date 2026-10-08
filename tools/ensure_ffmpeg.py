"""Verify pip-bundled ffmpeg (imageio-ffmpeg) is available.

NAS / Docker 部署只依赖 pip，不要求宿主机安装 ffmpeg。

Usage:
  pip install -r backend/requirements.txt
  python tools/ensure_ffmpeg.py
  python tools/ensure_ffmpeg.py --print
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def resolve_ffmpeg() -> str:
    for env_key in ("HG_FFMPEG", "FFMPEG"):
        v = (os.environ.get(env_key) or "").strip()
        if v and os.path.isfile(v):
            return v
    try:
        import imageio_ffmpeg  # type: ignore
    except ImportError as exc:
        raise FileNotFoundError(
            "缺少 imageio-ffmpeg。请执行：pip install -r backend/requirements.txt"
        ) from exc
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    if not exe or not os.path.isfile(exe):
        raise FileNotFoundError("imageio-ffmpeg 未提供 ffmpeg 二进制，请重装该包")
    return exe


def probe(exe: str) -> str:
    flags: dict = {}
    if sys.platform == "win32":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.run(
        [exe, "-version"],
        capture_output=True,
        text=True,
        timeout=15,
        **flags,
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr or "ffmpeg -version failed")
    line = (p.stdout or "").splitlines()[0] if p.stdout else exe
    return line.strip()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Check imageio-ffmpeg bundled binary for hg-dl"
    )
    ap.add_argument("--print", action="store_true", help="only print path")
    args = ap.parse_args()
    try:
        exe = resolve_ffmpeg()
        ver = probe(exe)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.print:
        print(exe)
    else:
        print(f"OK  {exe}")
        print(f"    {ver}")
        print("    (from imageio-ffmpeg / pip dependency — OK for NAS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
