"""分集完成记录：以记录为准判断「已下载」，不依赖本地文件是否还在。"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from ..paths import COMPLETED_NAME, ensure_dir


def _atomic_write_json(path: str, data: Any) -> None:
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class Completions:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path = ""
        # vid -> {"title": str, "eps": {str(ep): {"at": float}}}
        self._shows: dict[str, dict[str, Any]] = {}

    def bind(self, data_dir: str) -> None:
        ensure_dir(data_dir)
        self._path = os.path.join(data_dir, COMPLETED_NAME)
        loaded: dict[str, dict[str, Any]] = {}
        try:
            with open(self._path, encoding="utf-8") as fh:
                raw = json.load(fh)
            shows = raw.get("shows") if isinstance(raw, dict) else None
            if isinstance(shows, dict):
                for vid, body in shows.items():
                    if not isinstance(body, dict):
                        continue
                    eps_raw = body.get("eps") or {}
                    if not isinstance(eps_raw, dict):
                        continue
                    eps: dict[str, Any] = {}
                    for k, v in eps_raw.items():
                        try:
                            int(k)
                        except (TypeError, ValueError):
                            continue
                        at = float(v.get("at") or 0) if isinstance(v, dict) else float(v or 0)
                        eps[str(int(k))] = {"at": at}
                    loaded[str(vid)] = {
                        "title": str(body.get("title") or ""),
                        "eps": eps,
                    }
        except (OSError, ValueError, TypeError):
            loaded = {}
        with self._lock:
            self._shows = loaded

    def _persist_unlocked(self) -> None:
        if not self._path:
            return
        try:
            _atomic_write_json(
                self._path,
                {"saved": time.time(), "shows": self._shows},
            )
        except OSError:
            pass

    def done_eps(self, vid: str) -> set[int]:
        vid = str(vid or "").strip()
        if not vid:
            return set()
        # legacy bare id ↔ huangguo:id
        alts = [vid]
        if vid.startswith("huangguo:"):
            alts.append(vid.split(":", 1)[1])
        elif ":" not in vid:
            alts.append(f"huangguo:{vid}")
        with self._lock:
            out: set[int] = set()
            for key in alts:
                body = self._shows.get(key) or {}
                eps = body.get("eps") or {}
                for k in eps:
                    try:
                        out.add(int(k))
                    except (TypeError, ValueError):
                        pass
            return out

    def has(self, vid: str, ep: int) -> bool:
        return int(ep) in self.done_eps(vid)

    def mark(
        self,
        vid: str,
        ep: int,
        *,
        title: str = "",
        at: float | None = None,
    ) -> None:
        vid = str(vid or "").strip()
        if not vid:
            return
        ep_s = str(int(ep))
        with self._lock:
            body = self._shows.setdefault(vid, {"title": "", "eps": {}})
            if title:
                body["title"] = title
            eps = body.setdefault("eps", {})
            eps[ep_s] = {"at": float(at if at is not None else time.time())}
            self._persist_unlocked()

    def unmark(self, vid: str, ep: int) -> None:
        vid = str(vid or "").strip()
        if not vid:
            return
        ep_s = str(int(ep))
        with self._lock:
            body = self._shows.get(vid)
            if not body:
                return
            eps = body.get("eps") or {}
            if ep_s in eps:
                eps.pop(ep_s, None)
                self._persist_unlocked()

    def clear_eps(self, vid: str, eps: list[int] | set[int] | None = None) -> None:
        """清除某剧的完成记录；eps=None 表示整剧。"""
        vid = str(vid or "").strip()
        if not vid:
            return
        with self._lock:
            body = self._shows.get(vid)
            if not body:
                return
            if eps is None:
                body["eps"] = {}
            else:
                cur = body.get("eps") or {}
                for n in eps:
                    cur.pop(str(int(n)), None)
            self._persist_unlocked()

    def ingest_task_items(self, tasks: list[dict[str, Any]]) -> int:
        """从历史任务 items 补齐记录（ok/exist）。返回新写入条数。"""
        n_new = 0
        with self._lock:
            for t in tasks:
                vid = str(t.get("vid") or "").strip()
                if not vid:
                    continue
                title = str(t.get("title") or "")
                body = self._shows.setdefault(vid, {"title": title, "eps": {}})
                if title and not body.get("title"):
                    body["title"] = title
                eps = body.setdefault("eps", {})
                for it in t.get("items") or []:
                    if not isinstance(it, dict):
                        continue
                    if it.get("status") not in ("ok", "exist"):
                        continue
                    try:
                        ep_s = str(int(it["ep"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if ep_s not in eps:
                        eps[ep_s] = {"at": float(t.get("created") or time.time())}
                        n_new += 1
            if n_new:
                self._persist_unlocked()
        return n_new


C = Completions()
