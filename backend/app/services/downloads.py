from __future__ import annotations

import concurrent.futures as futures
import os
import threading
import time
import traceback
from typing import Any

from hg_core import (
    Show,
    already_done,
    build_jobs,
    cover_path,
    download,
    download_cover,
    ensure_emby_metadata,
    parse_ep_filter,
    scan_local,
    show_dir,
    target_path,
)

from .state import S

_run_lock = threading.Lock()
_running_ids: set[str] = set()
_ep_sema: threading.Semaphore | None = None
_ep_sema_n = 0


def _ep_semaphore() -> threading.Semaphore:
    """跨任务共享的分集下载并发闸。"""
    global _ep_sema, _ep_sema_n
    n = 4
    if S.settings is not None:
        n = max(1, min(16, int(S.settings.max_global_workers)))
    if _ep_sema is None or _ep_sema_n != n:
        _ep_sema = threading.Semaphore(n)
        _ep_sema_n = n
    return _ep_sema


def _download_guarded(job: Any, api: Any, out_dir: str) -> Any:
    with _ep_semaphore():
        return download(job, api, out_dir, timeout=60, retries=3)


class _CoverArgs:
    def __init__(self) -> None:
        assert S.settings is not None
        self.cover_proxy = S.settings.cover_proxy
        self.cover_token = S.settings.cover_token
        self.timeout = 30


def show_json(s: Show) -> dict[str, Any]:
    return {
        "id": s.id,
        "title": s.title,
        "total": s.total,
        "finished": s.finished,
        "cover": s.cover,
        "label": s.label,
        "tags": list(s.tags or []),
        "hot": int(s.hot or 0),
    }


def find_show(tid: str) -> Show:
    assert S.api is not None
    if tid in S.show_index:
        return S.show_index[tid]
    for cat in ("hot", "new"):
        try:
            for s in S.api.catalog(cat, 1):
                S.show_index[s.id] = s
        except Exception:  # noqa: BLE001
            continue
        if tid in S.show_index:
            break
    if tid in S.show_index:
        return S.show_index[tid]
    # 直链进详情时列表里可能没有，用详情接口补一条
    try:
        raw = S.api.detail(Show(id=tid, title=""))
        show = S.api._to_show(raw) if isinstance(raw, dict) else None
        if show:
            S.show_index[show.id] = show
            return show
    except Exception:  # noqa: BLE001
        pass
    return Show(id=tid, title="")


def start_download(body: dict[str, Any]) -> dict[str, Any]:
    """创建下载任务（默认排队，不自动跑）。body.start=true 时立刻开始。

    本地完整集跳过；残缺/假文件会删掉后重下（覆盖原路径）。
    """
    assert S.api is not None and S.settings is not None
    title = str(body.get("title") or "").strip()
    vid = str(body.get("id") or body.get("vid") or "").strip()
    eps_sel = body.get("episodes") or []
    if isinstance(eps_sel, str):
        eps_sel = list(parse_ep_filter(eps_sel) or [])
    ep_filter = set(int(x) for x in eps_sel) if eps_sel else None
    with_cover = bool(body.get("cover", True))
    out_dir = os.path.abspath(body.get("out") or S.out_dir)
    workers = max(1, min(8, int(body.get("workers") or S.settings.workers)))
    scan_dir = body.get("scan_dir") or S.settings.scan_dir or ""
    threshold = float(body.get("threshold") or 0.62)
    auto_start = bool(body.get("start", False))

    show = None
    score = 1.0
    cands: list[Any] = []
    if vid:
        found = find_show(vid)
        # find_show 总会带回 id；标题空时用任务里的剧名补上
        show = Show(
            id=vid,
            title=(found.title or title or vid).strip(),
            total=int(found.total or 0),
            finished=bool(found.finished),
            cover=found.cover or "",
            tags=list(found.tags or []),
            hot=int(found.hot or 0),
        )
    if not show:
        if not title:
            return {"ok": False, "error": "缺少剧名或 id"}
        show, score, cands = S.api.match(title, threshold)
        if not show:
            return {
                "ok": False,
                "error": "未匹配到剧名",
                "candidates": [{"id": c.id, "title": c.title} for c in cands],
            }

    S.show_index[show.id] = show
    eps = S.api.episodes(show)
    local_map = scan_local(scan_dir) if scan_dir and os.path.isdir(scan_dir) else {}
    jobs, have = build_jobs(
        show, eps, ep_filter=ep_filter, local_map=local_map,
        out_dir=out_dir,
    )

    # 同剧已有排队/下载中：直接复用，不叠一张空卡
    for existing in S.all_tasks():
        if existing.get("vid") == show.id and existing.get("status") in (
            "queued",
            "running",
        ):
            return {
                "ok": True,
                "reused": True,
                "taskId": existing["id"],
                "task": _public_task(existing),
                "message": "已有进行中的任务",
            }

    poster = cover_path(show, out_dir)
    poster_ok = os.path.isfile(poster) and os.path.getsize(poster) > 1024
    # 仅当本地媒体完整（残缺/假 mp4 不算）才跳过；旧「已完成」记录不挡重下
    if not jobs and (poster_ok or not with_cover):
        return {
            "ok": True,
            "skipped": True,
            "taskId": None,
            "task": None,
            "message": "本地已全部存在，未新建任务",
        }

    # 同剧旧的完成/失败记录：本地还缺货时清掉，避免列表里「已完成」误导
    if jobs:
        for existing in list(S.all_tasks()):
            if existing.get("vid") == show.id and existing.get("status") in (
                "done",
                "error",
            ):
                S.drop_task(str(existing["id"]))

    tid = f"t{int(time.time() * 1000) % 10**10}"
    have_set = set(have)
    items: list[dict[str, Any]] = []
    for e in eps:
        n = int(e["n"])
        if ep_filter and n not in ep_filter:
            continue
        if n in have_set:
            items.append({
                "ep": n,
                "status": "ok",
                "note": "已存在",
                "path": target_path(show, n, ".mp4", out_dir),
            })
        else:
            j = next((x for x in jobs if x.ep == n), None)
            if j:
                items.append({
                    "ep": j.ep,
                    "status": "pending",
                    "note": "",
                    "path": j.path,
                })
    task: dict[str, Any] = {
        "id": tid,
        "created": time.time(),
        "status": "queued",
        "title": show.title,
        "vid": show.id,
        "out": out_dir,
        "folder": os.path.basename(show_dir(show, out_dir)),
        "cover": with_cover,
        "workers": workers,
        "score": score,
        "total": len(eps),
        "have": have,
        "plan": [j.ep for j in jobs],
        "done": len(have),
        "fail": 0,
        "coverNote": "",
        "coverOk": None,
        "items": items,
    }
    S.put_task(task)
    S.push_event(tid, {"type": "queued", "task": _public_task(task)})

    msg = None
    if have and jobs:
        msg = f"本地完整 {len(have)} 集已跳过，将补下 {len(jobs)} 集"
    elif jobs and not have:
        msg = f"将下载 {len(jobs)} 集（含残缺重下）"

    if auto_start:
        kicked = run_download(tid)
        if not kicked.get("ok"):
            return kicked
        return {
            "ok": True,
            "taskId": tid,
            "task": kicked.get("task") or _public_task(task),
            "message": msg,
        }

    return {"ok": True, "taskId": tid, "task": _public_task(task), "message": msg}


def run_download(tid: str) -> dict[str, Any]:
    """手动开始（或重试）排队中的任务。"""
    assert S.api is not None and S.settings is not None
    task = S.get_task(tid)
    if not task:
        return {"ok": False, "error": "任务不存在"}

    max_pt = max(1, min(8, int(S.settings.max_parallel_tasks)))
    with _run_lock:
        if tid in _running_ids or task.get("status") == "running":
            return {"ok": True, "task": _public_task(task)}
        if task.get("status") not in ("queued", "error"):
            return {"ok": False, "error": f"当前状态不可开始: {task.get('status')}"}
        if len(_running_ids) >= max_pt:
            return {
                "ok": False,
                "error": f"同时进行的任务已达上限（{max_pt}），请等当前下载结束再开",
            }
        _running_ids.add(tid)
        task["status"] = "running"
        task["error"] = ""
        S.put_task(task)

    show = find_show(str(task.get("vid") or ""))
    if not show or not show.id:
        with _run_lock:
            _running_ids.discard(tid)
        task["status"] = "error"
        task["error"] = "找不到剧目"
        S.put_task(task)
        return {"ok": False, "error": task["error"], "task": _public_task(task)}

    out_dir = os.path.abspath(task.get("out") or S.out_dir)
    workers = max(1, min(8, int(task.get("workers") or S.settings.workers)))
    with_cover = bool(task.get("cover", True))
    plan = [int(x) for x in (task.get("plan") or [])]
    ep_filter = set(plan) if plan else None

    try:
        eps = S.api.episodes(show)
        jobs, _have = build_jobs(
            show, eps, ep_filter=ep_filter, local_map={},
            out_dir=out_dir,
        )
    except Exception as exc:  # noqa: BLE001
        with _run_lock:
            _running_ids.discard(tid)
        task["status"] = "error"
        task["error"] = str(exc)
        S.put_task(task)
        return {"ok": False, "error": str(exc), "task": _public_task(task)}

    # 同步 items 路径；磁盘不完整的「ok」一律打回重下
    by_ep = {j.ep: j for j in jobs}
    for it in task.get("items") or []:
        n = int(it["ep"])
        j = by_ep.get(n)
        path = (j.path if j else "") or target_path(show, n, ".mp4", out_dir)
        it["path"] = path
        if it.get("status") in ("ok", "exist") and already_done(path):
            it["status"] = "exist" if it.get("status") == "exist" else "ok"
            continue
        if n in by_ep:
            it["status"] = "pending"
            it["note"] = ""
        elif already_done(path):
            it["status"] = "ok"
            it["note"] = "已存在"
        else:
            it["status"] = "pending"
            it["note"] = ""

    task["done"] = sum(
        1 for it in task.get("items") or [] if it.get("status") in ("ok", "exist")
    )
    task["fail"] = 0
    S.put_task(task)
    S.push_event(tid, {"type": "started", "task": _public_task(task)})

    pending_jobs = [
        by_ep[it["ep"]]
        for it in task.get("items") or []
        if it.get("status") not in ("ok", "exist") and it["ep"] in by_ep
    ]

    def work() -> None:
        try:
            plot = ""
            try:
                detail = S.api.detail(show)
                if isinstance(detail, dict):
                    plot = str(
                        detail.get("description")
                        or detail.get("plot")
                        or detail.get("vod_content")
                        or ""
                    ).strip()
                    tags = detail.get("tags")
                    if isinstance(tags, list) and tags:
                        show.tags = [str(t) for t in tags if t]
            except Exception:  # noqa: BLE001
                pass
            try:
                ensure_emby_metadata(show, out_dir, plot=plot)
            except Exception:  # noqa: BLE001
                pass
            if with_cover and not task.get("coverOk"):
                good, note = download_cover(show, S.api, out_dir, _CoverArgs())
                task["coverNote"] = note
                task["coverOk"] = good
                S.push_event(tid, {"type": "cover", "ok": good, "note": note})
            with futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {
                    pool.submit(_download_guarded, j, S.api, out_dir): j
                    for j in pending_jobs
                }
                for fut in futures.as_completed(futs):
                    j = fut.result()
                    # exist 也算完成；假成功（无有效文件）打成失败
                    if j.status in ("ok", "exist"):
                        check = j.path or target_path(show, j.ep, ".mp4", out_dir)
                        if not already_done(check):
                            j.status, j.note = "fail", j.note or "落盘无效"
                    for it in task["items"]:
                        if it["ep"] == j.ep:
                            it["status"] = j.status
                            it["note"] = j.note
                            if j.path:
                                it["path"] = j.path
                            break
                    if j.status in ("ok", "exist"):
                        task["done"] += 1
                    elif j.status == "fail":
                        task["fail"] += 1
                    S.push_event(tid, {
                        "type": "episode",
                        "ep": j.ep,
                        "status": j.status,
                        "note": j.note,
                        "done": task["done"],
                        "fail": task["fail"],
                    })
                    S.persist_tasks_soon()
            task["status"] = "done"
            S.put_task(task)
            S.push_event(tid, {"type": "done", "task": _public_task(task)})
        except Exception as exc:  # noqa: BLE001
            task["status"] = "error"
            task["error"] = str(exc)
            task["trace"] = traceback.format_exc()[-1500:]
            S.put_task(task)
            S.push_event(tid, {"type": "error", "error": str(exc)})
        finally:
            with _run_lock:
                _running_ids.discard(tid)
            try:
                if S.api and S.api.cache:
                    S.api.cache.save()
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "task": _public_task(task)}


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    """Drop absolute paths for API responses (keep ep status)."""
    out = str(task.get("out") or "")
    folder = str(task.get("folder") or "")
    if not folder and out and task.get("title"):
        folder = os.path.basename(show_dir(Show(id="", title=str(task["title"])), out))
    items_out = []
    for it in task.get("items", []):
        rel = ""
        p = str(it.get("path") or "")
        if p and out:
            try:
                rel = os.path.relpath(p, out).replace("\\", "/")
                if rel.startswith(".."):
                    rel = os.path.basename(p)
            except ValueError:
                rel = os.path.basename(p)
        elif p:
            rel = os.path.basename(p)
        items_out.append({
            "ep": it["ep"],
            "status": it["status"],
            "note": it["note"],
            "file": rel,
        })
    return {
        "id": task["id"],
        "created": task["created"],
        "status": task["status"],
        "title": task["title"],
        "vid": task["vid"],
        "folder": folder,
        "cover": task.get("cover"),
        "score": task.get("score"),
        "total": task.get("total"),
        "have": task.get("have"),
        "plan": task.get("plan"),
        "done": task.get("done"),
        "fail": task.get("fail"),
        "coverNote": task.get("coverNote"),
        "coverOk": task.get("coverOk"),
        "error": task.get("error"),
        "items": items_out,
    }
