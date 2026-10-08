"""封面本地磁盘缓存：高频列表/详情共用，避免反复拉源解密。"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Any

from ..paths import ensure_dir

# 7 天；体量上限约 300 个文件 / 200MB，超出按 mtime 淘汰
_TTL_SEC = 7 * 24 * 3600
_MAX_FILES = 300
_MAX_BYTES = 200 * 1024 * 1024


class CoverCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dir = ""

    def bind(self, data_dir: str) -> None:
        self._dir = ensure_dir(os.path.join(data_dir, "cover_cache"))

    def _key(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8", errors="ignore")).hexdigest()

    def _paths(self, key: str) -> tuple[str, str]:
        return (
            os.path.join(self._dir, f"{key}.bin"),
            os.path.join(self._dir, f"{key}.mime"),
        )

    def get(self, url: str) -> tuple[bytes, str] | None:
        if not self._dir or not url:
            return None
        key = self._key(url)
        bin_p, mime_p = self._paths(key)
        try:
            st = os.stat(bin_p)
            if time.time() - st.st_mtime > _TTL_SEC:
                return None
            with open(bin_p, "rb") as fh:
                data = fh.read()
            if not data:
                return None
            mime = "image/jpeg"
            if os.path.isfile(mime_p):
                with open(mime_p, encoding="utf-8") as fh:
                    mime = (fh.read() or mime).strip() or mime
            # 刷新访问时间，便于 LRU
            try:
                os.utime(bin_p, None)
            except OSError:
                pass
            return data, mime
        except OSError:
            return None

    def put(self, url: str, data: bytes, mime: str) -> None:
        if not self._dir or not url or not data:
            return
        key = self._key(url)
        bin_p, mime_p = self._paths(key)
        tmp = bin_p + ".tmp"
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, bin_p)
            with open(mime_p, "w", encoding="utf-8") as fh:
                fh.write((mime or "image/jpeg").strip())
        except OSError:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return
        self._prune()

    def _prune(self) -> None:
        if not self._dir:
            return
        with self._lock:
            try:
                entries: list[tuple[float, int, str]] = []
                total = 0
                for name in os.listdir(self._dir):
                    if not name.endswith(".bin"):
                        continue
                    path = os.path.join(self._dir, name)
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    entries.append((st.st_mtime, st.st_size, path))
                    total += st.st_size
                if len(entries) <= _MAX_FILES and total <= _MAX_BYTES:
                    return
                entries.sort(key=lambda x: x[0])  # oldest first
                while entries and (
                    len(entries) > _MAX_FILES or total > _MAX_BYTES
                ):
                    _mt, size, path = entries.pop(0)
                    total -= size
                    base, _ = os.path.splitext(path)
                    for p in (path, base + ".mime"):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
            except OSError:
                pass

    def stats(self) -> dict[str, Any]:
        if not self._dir or not os.path.isdir(self._dir):
            return {"files": 0, "bytes": 0}
        n = 0
        b = 0
        try:
            for name in os.listdir(self._dir):
                if not name.endswith(".bin"):
                    continue
                n += 1
                try:
                    b += os.path.getsize(os.path.join(self._dir, name))
                except OSError:
                    pass
        except OSError:
            pass
        return {"files": n, "bytes": b}


CoverDisk = CoverCache()
