from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any

# packages/core on path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_CORE = os.path.join(_ROOT, "packages", "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from hg_core import Cache, HGApi, Show  # noqa: E402
from hg_core.sources import (  # noqa: E402
    HuangdouSource,
    HuangguoSource,
    SourceRegistry,
    YeguoSource,
)

from ..config import Settings
from ..paths import (
    CACHE_NAME,
    FAVORITES_NAME,
    TASKS_NAME,
    ensure_dir,
    migrate_runtime_files,
)
from .completions import C
from .cover_cache import CoverDisk
from .runtime_settings import R


def _atomic_write_json(path: str, data: Any) -> None:
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class AppState:
    def __init__(self) -> None:
        self.settings: Settings | None = None
        # SourceRegistry facade (catalog/search/detail/play); .huangguo_api for HGApi
        self.api: SourceRegistry | None = None
        self.registry: SourceRegistry | None = None
        self.out_dir: str = ""
        self.data_dir: str = ""
        self.show_index: dict[str, Show] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.favorites: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.event_conds: dict[str, threading.Condition] = {}
        self._persist_timer: threading.Timer | None = None

    def init(self, settings: Settings) -> None:
        self.settings = settings
        out = ensure_dir(settings.out_dir)
        data = ensure_dir(settings.data_dir)
        self.out_dir = out
        self.data_dir = data
        migrate_runtime_files(data, out)
        R.bind(data, {
            "hg_api": settings.hg_api,
            "http_proxy": settings.http_proxy,
            "cover_proxy": settings.cover_proxy,
            "cover_token": settings.cover_token,
            "huangdou_api": settings.huangdou_api,
            "yeguo_api": settings.yeguo_api,
            "sources_enabled": settings.sources_enabled,
        })
        self._merge_default_sources(settings)
        self._rebuild_api()
        self.show_index = {}
        self.events = {}
        self.event_conds = {}
        self.tasks = self._load_tasks()
        self.favorites = self._load_favorites()
        C.bind(data)
        CoverDisk.bind(data)
        # 用历史任务 ok/exist 补全完成记录（只增不减）
        try:
            C.ingest_task_items(list(self.tasks.values()))
        except Exception:  # noqa: BLE001
            pass

    def _tasks_path(self) -> str:
        return os.path.join(self.data_dir, TASKS_NAME)

    def _load_tasks(self) -> dict[str, dict[str, Any]]:
        path = self._tasks_path()
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}
        items = raw.get("tasks") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return {}
        out: dict[str, dict[str, Any]] = {}
        for t in items:
            if not isinstance(t, dict) or not t.get("id"):
                continue
            tid = str(t["id"])
            # 重启后不能恢复半截 running：打回排队，便于手动再开
            if t.get("status") == "running":
                t = dict(t)
                t["status"] = "queued"
                t["error"] = ""
                t["note"] = "服务重启，已重新排队"
            out[tid] = t
            self.events.setdefault(tid, [])
            self.event_conds.setdefault(tid, threading.Condition())
        return out

    def _persist_tasks_unlocked(self) -> None:
        if not self.data_dir:
            return
        payload = {
            "saved": time.time(),
            "tasks": sorted(
                self.tasks.values(),
                key=lambda t: float(t.get("created") or 0),
                reverse=True,
            )[:30],
        }
        try:
            _atomic_write_json(self._tasks_path(), payload)
        except OSError:
            pass

    def persist_tasks(self) -> None:
        with self.lock:
            self._persist_tasks_unlocked()

    def persist_tasks_soon(self, delay: float = 0.4) -> None:
        """合并频繁的分集进度写入。"""
        with self.lock:
            if self._persist_timer is not None:
                self._persist_timer.cancel()

            def _fire() -> None:
                self.persist_tasks()

            self._persist_timer = threading.Timer(delay, _fire)
            self._persist_timer.daemon = True
            self._persist_timer.start()

    def _favorites_path(self) -> str:
        return os.path.join(self.data_dir, FAVORITES_NAME)

    def _load_favorites(self) -> dict[str, dict[str, Any]]:
        path = self._favorites_path()
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}
        items = raw.get("items") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return {}
        out: dict[str, dict[str, Any]] = {}
        for it in items:
            if not isinstance(it, dict) or not it.get("id"):
                continue
            sid = str(it["id"]).strip()
            if not sid:
                continue
            out[sid] = dict(it)
            out[sid]["id"] = sid
        return out

    def _persist_favorites_unlocked(self) -> None:
        if not self.data_dir:
            return
        payload = {
            "saved": time.time(),
            "items": sorted(
                self.favorites.values(),
                key=lambda x: float(x.get("added") or 0),
                reverse=True,
            ),
        }
        try:
            _atomic_write_json(self._favorites_path(), payload)
        except OSError:
            pass

    @staticmethod
    def _normalize_favorite(body: dict[str, Any]) -> dict[str, Any] | None:
        sid = str(body.get("id") or "").strip()
        if not sid:
            return None
        title = str(body.get("title") or sid).strip() or sid
        tags = body.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        return {
            "id": sid,
            "title": title,
            "cover": str(body.get("cover") or ""),
            "total": int(body.get("total") or 0),
            "finished": bool(body.get("finished")),
            "label": str(body.get("label") or ""),
            "tags": [str(t) for t in tags if t],
            "hot": int(body.get("hot") or 0),
            "added": float(body.get("added") or time.time()),
        }

    def list_favorites(self) -> list[dict[str, Any]]:
        with self.lock:
            return sorted(
                (dict(v) for v in self.favorites.values()),
                key=lambda x: float(x.get("added") or 0),
                reverse=True,
            )

    def is_favorite(self, sid: str) -> bool:
        with self.lock:
            return str(sid) in self.favorites

    def add_favorite(self, body: dict[str, Any]) -> dict[str, Any] | None:
        item = self._normalize_favorite(body)
        if not item:
            return None
        with self.lock:
            prev = self.favorites.get(item["id"])
            if prev and prev.get("added"):
                item["added"] = float(prev["added"])
            self.favorites[item["id"]] = item
            self._persist_favorites_unlocked()
            return dict(item)

    def remove_favorite(self, sid: str) -> bool:
        sid = str(sid or "").strip()
        if not sid:
            return False
        with self.lock:
            if sid not in self.favorites:
                return False
            self.favorites.pop(sid, None)
            self._persist_favorites_unlocked()
            return True

    def _merge_default_sources(self, settings: Settings) -> None:
        """旧 settings.json 可能缺少新接入片源或 API 地址，与出厂默认合并。"""
        snap = R.snapshot()
        factory = [
            x.strip().lower()
            for x in (settings.sources_enabled or "").split(",")
            if x.strip()
        ]
        current = [
            x.strip().lower()
            for x in str(snap.get("sources_enabled") or "").split(",")
            if x.strip()
        ]
        if not factory:
            return
        factory_set = set(factory)
        current_set = set(current)
        patch: dict[str, Any] = {}
        if factory_set - current_set:
            order = {name: i for i, name in enumerate(factory)}
            merged = sorted(factory_set | current_set, key=lambda x: order.get(x, 99))
            patch["sources_enabled"] = ",".join(merged)
        active = factory_set | current_set
        if "yeguo" in active and not str(snap.get("yeguo_api") or "").strip():
            patch["yeguo_api"] = settings.yeguo_api
        if "huangdou" in active and not str(snap.get("huangdou_api") or "").strip():
            patch["huangdou_api"] = settings.huangdou_api
        if patch:
            R.update(patch)

    def _rebuild_api(self) -> None:
        assert self.settings is not None
        snap = R.snapshot()
        proxy = str(snap.get("http_proxy") or "")
        cache = Cache(os.path.join(self.data_dir, CACHE_NAME))
        hg = HGApi(
            snap.get("hg_api") or self.settings.hg_api,
            cache=cache,
            cache_ttl=self.settings.cache_ttl,
            timeout=20,
            proxy=proxy,
        )
        enabled_raw = str(
            snap.get("sources_enabled") or self.settings.sources_enabled or "huangguo"
        )
        enabled = {
            x.strip().lower()
            for x in enabled_raw.replace("，", ",").split(",")
            if x.strip()
        }
        if not enabled:
            enabled = {"huangguo"}

        reg = SourceRegistry()
        if "huangguo" in enabled:
            reg.register(HuangguoSource(hg))
        if "huangdou" in enabled:
            reg.register(
                HuangdouSource(
                    str(snap.get("huangdou_api") or self.settings.huangdou_api or ""),
                    timeout=20,
                    proxy=proxy,
                )
            )
        if "yeguo" in enabled:
            reg.register(
                YeguoSource(
                    str(snap.get("yeguo_api") or self.settings.yeguo_api or ""),
                    timeout=20,
                    proxy=proxy,
                )
            )
        # always keep at least 黄果 so downloads don't hard-fail
        if not reg.list_sources():
            reg.register(HuangguoSource(hg))

        self.registry = reg
        self.api = reg
        self.settings.cover_proxy = str(snap.get("cover_proxy") or "")
        self.settings.cover_token = str(snap.get("cover_token") or "")
        self.settings.hg_api = str(snap.get("hg_api") or self.settings.hg_api)
        self.settings.http_proxy = proxy
        self.settings.huangdou_api = str(
            snap.get("huangdou_api") or self.settings.huangdou_api or ""
        )
        self.settings.yeguo_api = str(
            snap.get("yeguo_api") or self.settings.yeguo_api or ""
        )
        self.settings.sources_enabled = ",".join(
            s["name"] for s in reg.list_sources()
        )

    def apply_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        snap = R.update(patch)
        self._rebuild_api()
        self.show_index.clear()
        cache = self.api.cache if self.api else None
        if cache is not None and getattr(cache, "data", None) is not None:
            cache.data = {
                k: v for k, v in cache.data.items()
                if not (k.startswith("cat:") or k.startswith("search:"))
            }
        return snap

    def put_task(self, task: dict[str, Any]) -> None:
        with self.lock:
            self.tasks[task["id"]] = task
            self.events.setdefault(task["id"], [])
            self.event_conds.setdefault(task["id"], threading.Condition())
            if len(self.tasks) > 30:
                for k in sorted(self.tasks, key=lambda x: self.tasks[x]["created"])[:-30]:
                    self.tasks.pop(k, None)
                    self.events.pop(k, None)
                    self.event_conds.pop(k, None)
            self._persist_tasks_unlocked()

    def get_task(self, tid: str) -> dict[str, Any] | None:
        with self.lock:
            t = self.tasks.get(tid)
            return dict(t) if t else None

    def drop_task(self, tid: str) -> bool:
        with self.lock:
            if tid not in self.tasks:
                return False
            self.tasks.pop(tid, None)
            self.events.pop(tid, None)
            self.event_conds.pop(tid, None)
            self._persist_tasks_unlocked()
            return True

    @staticmethod
    def _is_noop_task(t: dict[str, Any]) -> bool:
        """无实际下载内容的空任务（全已存在却建了卡）。"""
        plan = t.get("plan") or []
        done = int(t.get("done") or 0)
        fail = int(t.get("fail") or 0)
        items = t.get("items") or []
        pending = sum(1 for it in items if it.get("status") in ("pending", "fail"))
        if plan or pending or fail:
            return False
        if done <= 0 and t.get("status") in ("done", "queued", "error"):
            return True
        return False

    def all_tasks(self) -> list[dict[str, Any]]:
        with self.lock:
            dirty = False
            for tid, t in list(self.tasks.items()):
                if self._is_noop_task(t):
                    self.tasks.pop(tid, None)
                    self.events.pop(tid, None)
                    self.event_conds.pop(tid, None)
                    dirty = True
            if dirty:
                self._persist_tasks_unlocked()
            return sorted(
                (dict(t) for t in self.tasks.values()),
                key=lambda t: t["created"],
                reverse=True,
            )

    def push_event(self, tid: str, event: dict[str, Any]) -> None:
        with self.lock:
            cond = self.event_conds.get(tid)
            evs = self.events.get(tid)
            if evs is None:
                return
            evs.append(event)
        if cond:
            with cond:
                cond.notify_all()

    def wait_events(self, tid: str, after: int, timeout: float = 25.0) -> list[dict[str, Any]]:
        with self.lock:
            cond = self.event_conds.get(tid)
            if cond is None:
                return []
        with cond:
            if after >= len(self.events.get(tid, [])):
                cond.wait(timeout=timeout)
        with self.lock:
            evs = self.events.get(tid, [])
            return list(evs[after:])


S = AppState()
