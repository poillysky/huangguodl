from __future__ import annotations

import concurrent.futures as futures
import os
import threading
import time
import traceback
from typing import Any

from hg_core import (
    Job,
    Show,
    already_done,
    cover_path,
    download,
    download_cover,
    ensure_emby_metadata,
    parse_ep_filter,
    remove_episode_media,
    show_dir,
    target_path,
)
from hg_core.ids import DEFAULT_SOURCE, make_key, parse_key

from .completions import C
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


def _adapter_for(show: Show) -> Any:
    """Resolve per-source adapter for play/cover download."""
    assert S.api is not None
    if hasattr(S.api, "source_for"):
        return S.api.source_for(show)
    return S.api


def _download_guarded(job: Any, api: Any, out_dir: str, *, force: bool = False) -> Any:
    with _ep_semaphore():
        adapter = _adapter_for(job.show) if hasattr(job, "show") else api
        return download(job, adapter, out_dir, timeout=60, retries=3, force=force)


class _CoverArgs:
    def __init__(self) -> None:
        assert S.settings is not None
        self.cover_proxy = S.settings.cover_proxy
        self.cover_token = S.settings.cover_token
        self.timeout = 30


def _index_show(s: Show) -> None:
    """Index by composite key and bare id (huangguo only, for legacy links)."""
    key = s.key if getattr(s, "source", None) else make_key(DEFAULT_SOURCE, s.id)
    S.show_index[key] = s
    if (getattr(s, "source", None) or DEFAULT_SOURCE) == DEFAULT_SOURCE:
        S.show_index[s.id] = s


def show_json(s: Show) -> dict[str, Any]:
    src = getattr(s, "source", None) or DEFAULT_SOURCE
    key = s.key if hasattr(s, "key") else make_key(src, s.id)
    return {
        "id": key,  # public id is always source:native
        "nativeId": s.id,
        "source": src,
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
    tid = str(tid or "").strip()
    if tid in S.show_index:
        return S.show_index[tid]
    src_name, nid = parse_key(tid)
    # also try bare native under that source
    alt = make_key(src_name, nid)
    if alt in S.show_index:
        return S.show_index[alt]

    for cat in ("hot", "new"):
        try:
            for s in S.api.catalog(cat, 1, source=src_name):
                _index_show(s)
        except Exception:  # noqa: BLE001
            continue
        if tid in S.show_index or alt in S.show_index:
            break
    if tid in S.show_index:
        return S.show_index[tid]
    if alt in S.show_index:
        return S.show_index[alt]

    # 直链进详情：用对应片源详情补一条
    try:
        stub = Show(id=nid, title="", source=src_name)
        raw = S.api.detail(stub)
        show = None
        if isinstance(raw, dict):
            src = S.api.source_for(stub)
            if hasattr(src, "_to_show"):
                show = src._to_show(raw)
            elif S.api.huangguo_api and src_name == DEFAULT_SOURCE:
                show = S.api.huangguo_api._to_show(raw)
            if show is None and raw.get("title"):
                show = Show(
                    id=str(raw.get("id") or nid),
                    title=str(raw.get("title") or nid),
                    source=src_name,
                    cover=str(raw.get("cover") or ""),
                    total=int(raw.get("episode_count") or raw.get("total") or 0),
                )
        if show:
            show.source = src_name
            _index_show(show)
            return show
    except Exception:  # noqa: BLE001
        pass
    return Show(id=nid or tid, title="", source=src_name)


def _plan_by_records(
    show: Show,
    eps: list[dict[str, Any]],
    *,
    ep_filter: set[int] | None,
    out_dir: str,
    force: bool = False,
) -> tuple[list[Job], list[int]]:
    """按完成记录规划待下集；force 时清记录并删本地后全部重下。"""
    vid = show.key if hasattr(show, "key") else show.id
    done = set() if force else C.done_eps(vid)
    jobs: list[Job] = []
    have: list[int] = []
    for e in eps:
        n = int(e["n"])
        if ep_filter and n not in ep_filter:
            continue
        ext = os.path.splitext(e.get("url", "") or "")[1] or ".mp4"
        path = target_path(show, n, ext, out_dir)
        if force:
            C.unmark(vid, n)
            remove_episode_media(show, n, out_dir, ext)
            jobs.append(
                Job(
                    show=show,
                    ep=n,
                    ep_title=str(e.get("title") or ""),
                    preset_url=str(e.get("url") or ""),
                    path=path,
                )
            )
            continue
        if n in done:
            have.append(n)
            continue
        jobs.append(
            Job(
                show=show,
                ep=n,
                ep_title=str(e.get("title") or ""),
                preset_url=str(e.get("url") or ""),
                path=path,
            )
        )
    return jobs, have


def _show_vid(show: Show) -> str:
    return show.key if hasattr(show, "key") else make_key(
        getattr(show, "source", None) or DEFAULT_SOURCE, show.id
    )


def _mark_item_done(show: Show, ep: int) -> None:
    C.mark(_show_vid(show), ep, title=show.title)


def start_download(body: dict[str, Any]) -> dict[str, Any]:
    """创建下载任务（默认排队，不自动跑）。body.start=true 时立刻开始。

    以完成记录为准跳过；force=true 时清记录并覆盖本地重下。
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
    threshold = float(body.get("threshold") or 0.62)
    auto_start = bool(body.get("start", False))
    force = bool(body.get("force", False))
    follow = bool(body.get("follow", False))

    show = None
    score = 1.0
    cands: list[Any] = []
    if vid:
        found = find_show(vid)
        src_name, nid = parse_key(vid)
        if found.id:
            nid = found.id
            src_name = getattr(found, "source", None) or src_name
        show = Show(
            id=nid,
            title=(found.title or title or nid).strip(),
            total=int(found.total or 0),
            finished=bool(found.finished),
            cover=found.cover or "",
            tags=list(found.tags or []),
            hot=int(found.hot or 0),
            source=src_name,
        )
    if not show:
        if not title:
            return {"ok": False, "error": "缺少剧名或 id"}
        show, score, cands = S.api.match(title, threshold)
        if not show:
            return {
                "ok": False,
                "error": "未匹配到剧名",
                "candidates": [show_json(c) for c in cands],
            }

    _index_show(show)
    eps = S.api.episodes(show)
    jobs, have = _plan_by_records(
        show, eps, ep_filter=ep_filter, out_dir=out_dir, force=force,
    )

    # 同剧已有排队/下载中：直接复用
    for existing in S.all_tasks():
        if existing.get("vid") == _show_vid(show) and existing.get("status") in (
            "queued",
            "running",
        ):
            if follow and not existing.get("follow"):
                existing["follow"] = True
                S.put_task(existing)
            return {
                "ok": True,
                "reused": True,
                "taskId": existing["id"],
                "task": _public_task(existing),
                "message": "已有进行中的任务",
            }

    # 追更：同剧已有完成任务时，把新增集并入该任务
    if jobs and not force:
        for existing in list(S.all_tasks()):
            if existing.get("vid") != _show_vid(show):
                continue
            if existing.get("status") not in ("done", "error", "queued"):
                continue
            if existing.get("status") == "queued":
                continue
            merged = _merge_new_eps_into_task(existing, show, jobs, eps, out_dir)
            if merged is not None:
                if follow:
                    merged["follow"] = True
                S.put_task(merged)
                msg = f"已并入原任务，新增 {len(jobs)} 集"
                if auto_start and merged.get("status") == "queued":
                    kicked = run_download(str(merged["id"]))
                    if not kicked.get("ok"):
                        return kicked
                    return {
                        "ok": True,
                        "taskId": merged["id"],
                        "task": kicked.get("task") or _public_task(merged),
                        "message": msg,
                        "merged": True,
                    }
                return {
                    "ok": True,
                    "taskId": merged["id"],
                    "task": _public_task(merged),
                    "message": msg,
                    "merged": True,
                }

    if not jobs and follow:
        for existing in list(S.all_tasks()):
            if existing.get("vid") == _show_vid(show):
                existing["follow"] = True
                S.put_task(existing)
                return {
                    "ok": True,
                    "reused": True,
                    "taskId": existing["id"],
                    "task": _public_task(existing),
                    "message": "已开启追更，当前无新增集",
                }

    poster = cover_path(show, out_dir)
    poster_ok = os.path.isfile(poster) and os.path.getsize(poster) > 1024
    if not jobs and (poster_ok or not with_cover) and not follow:
        return {
            "ok": True,
            "skipped": True,
            "taskId": None,
            "task": None,
            "message": "完成记录显示已全部下过，未新建任务",
        }

    # 强制重下或新建：清掉同剧旧完成/失败卡（追更任务会保留由上面 merge 处理）
    if force or jobs:
        for existing in list(S.all_tasks()):
            if existing.get("vid") == _show_vid(show) and existing.get("status") in (
                "done",
                "error",
            ):
                if existing.get("follow") and not force and not jobs:
                    continue
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
                "note": "记录已有",
                "path": target_path(show, n, ".mp4", out_dir),
            })
        else:
            j = next((x for x in jobs if x.ep == n), None)
            if j:
                items.append({
                    "ep": j.ep,
                    "status": "pending",
                    "note": "覆盖重下" if force else "",
                    "path": j.path,
                })
    # 仅追更且当前无新增：仍建一条空计划任务，方便挂追更开关
    if not items and follow:
        for e in eps:
            n = int(e["n"])
            items.append({
                "ep": n,
                "status": "ok",
                "note": "记录已有",
                "path": target_path(show, n, ".mp4", out_dir),
            })
            have.append(n)

    task: dict[str, Any] = {
        "id": tid,
        "created": time.time(),
        "status": "queued" if jobs else "done",
        "title": show.title,
        "vid": _show_vid(show),
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
        "follow": follow,
        "followCheckedAt": 0.0,
        "forceOnce": force,
        "items": items,
    }
    S.put_task(task)
    S.push_event(tid, {"type": "queued", "task": _public_task(task)})

    msg = None
    if force and jobs:
        msg = f"将覆盖重下 {len(jobs)} 集"
    elif have and jobs:
        msg = f"记录已有 {len(have)} 集已跳过，将补下 {len(jobs)} 集"
    elif jobs and not have:
        msg = f"将下载 {len(jobs)} 集"
    elif follow and not jobs:
        msg = "已开启追更，当前无新增集"

    if auto_start and jobs:
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


def _merge_new_eps_into_task(
    task: dict[str, Any],
    show: Show,
    jobs: list[Job],
    eps: list[dict[str, Any]],
    out_dir: str,
) -> dict[str, Any] | None:
    """把新增 Job 并入已有任务；无待下集返回 None。"""
    if not jobs:
        return None
    by_item = {int(it["ep"]): it for it in (task.get("items") or [])}
    changed = False
    for j in jobs:
        it = by_item.get(j.ep)
        if it is None:
            task.setdefault("items", []).append({
                "ep": j.ep,
                "status": "pending",
                "note": "追更新增",
                "path": j.path,
            })
            by_item[j.ep] = task["items"][-1]
            changed = True
        elif it.get("status") in ("ok", "exist", "fail"):
            it["status"] = "pending"
            it["note"] = "追更新增" if it.get("status") in ("ok", "exist") else ""
            it["path"] = j.path
            changed = True

    # 远端已有、记录也有、任务里还没有的集补成 ok
    recorded = C.done_eps(_show_vid(show))
    for e in eps:
        n = int(e["n"])
        if n in by_item:
            continue
        if n in recorded:
            task.setdefault("items", []).append({
                "ep": n,
                "status": "ok",
                "note": "记录已有",
                "path": target_path(show, n, ".mp4", out_dir),
            })
            by_item[n] = task["items"][-1]

    plan = [
        int(it["ep"])
        for it in (task.get("items") or [])
        if it.get("status") not in ("ok", "exist")
    ]
    if not plan or not changed:
        return None
    task["plan"] = plan
    task["total"] = max(int(task.get("total") or 0), len(eps))
    task["have"] = [
        int(it["ep"])
        for it in (task.get("items") or [])
        if it.get("status") in ("ok", "exist")
    ]
    task["done"] = len(task["have"])
    task["fail"] = sum(
        1 for it in (task.get("items") or []) if it.get("status") == "fail"
    )
    task["status"] = "queued"
    task["error"] = ""
    task["forceOnce"] = False
    return task


def set_task_follow(tid: str, follow: bool) -> dict[str, Any]:
    task = S.get_task(tid)
    if not task:
        return {"ok": False, "error": "任务不存在"}
    task["follow"] = bool(follow)
    if follow and not task.get("followCheckedAt"):
        task["followCheckedAt"] = 0.0
    S.put_task(task)
    return {"ok": True, "task": _public_task(task)}


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
    force = bool(task.get("forceOnce"))
    plan = [int(x) for x in (task.get("plan") or [])]
    ep_filter = set(plan) if plan else None

    try:
        eps = S.api.episodes(show)
        jobs, _have = _plan_by_records(
            show, eps, ep_filter=ep_filter, out_dir=out_dir, force=force,
        )
    except Exception as exc:  # noqa: BLE001
        with _run_lock:
            _running_ids.discard(tid)
        task["status"] = "error"
        task["error"] = str(exc)
        S.put_task(task)
        return {"ok": False, "error": str(exc), "task": _public_task(task)}

    by_ep = {j.ep: j for j in jobs}
    for it in task.get("items") or []:
        n = int(it["ep"])
        j = by_ep.get(n)
        path = (j.path if j else "") or target_path(show, n, ".mp4", out_dir)
        it["path"] = path
        done_set = C.done_eps(_show_vid(show))
        if not force and n in done_set:
            it["status"] = "ok"
            it["note"] = it.get("note") or "记录已有"
            continue
        if n in by_ep:
            it["status"] = "pending"
            if force:
                it["note"] = "覆盖重下"
            elif not it.get("note"):
                it["note"] = ""
        elif n in done_set:
            it["status"] = "ok"
            it["note"] = "记录已有"
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
                good, note = download_cover(
                    show, _adapter_for(show), out_dir, _CoverArgs()
                )
                task["coverNote"] = note
                task["coverOk"] = good
                S.push_event(tid, {"type": "cover", "ok": good, "note": note})
            with futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {
                    pool.submit(
                        _download_guarded, j, S.api, out_dir, force=force,
                    ): j
                    for j in pending_jobs
                }
                for fut in futures.as_completed(futs):
                    j = fut.result()
                    if j.status in ("ok", "exist"):
                        check = j.path or target_path(show, j.ep, ".mp4", out_dir)
                        if not already_done(check):
                            j.status, j.note = "fail", j.note or "落盘无效"
                        else:
                            _mark_item_done(show, j.ep)
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
            task["forceOnce"] = False
            task["plan"] = []
            task["have"] = [
                int(it["ep"])
                for it in (task.get("items") or [])
                if it.get("status") in ("ok", "exist")
            ]
            S.put_task(task)
            S.push_event(tid, {"type": "done", "task": _public_task(task)})
        except Exception as exc:  # noqa: BLE001
            task["status"] = "error"
            task["error"] = str(exc)
            task["trace"] = traceback.format_exc()[-1500:]
            task["forceOnce"] = False
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


def check_follow_tasks(*, min_gap: float = 0.0) -> dict[str, Any]:
    """检查开启追更的任务，只排队下载记录里没有的新集。

    min_gap>0 时跳过距上次检查不足间隔的任务（后台日更用）。
    """
    assert S.api is not None and S.settings is not None
    checked = 0
    enqueued = 0
    started = 0
    errors: list[str] = []
    now = time.time()
    for task in list(S.all_tasks()):
        if not task.get("follow"):
            continue
        if task.get("status") == "running":
            continue
        last = float(task.get("followCheckedAt") or 0)
        if min_gap > 0 and last > 0 and (now - last) < min_gap:
            continue
        vid = str(task.get("vid") or "").strip()
        if not vid:
            continue
        checked += 1
        try:
            show = find_show(vid)
            if not show.title:
                src_name, nid = parse_key(vid)
                show = Show(
                    id=nid or vid,
                    title=str(task.get("title") or nid or vid),
                    total=int(task.get("total") or 0),
                    source=src_name,
                )
            # 刷新详情 finished / total
            try:
                detail = S.api.detail(show)
                if isinstance(detail, dict):
                    src = S.api.source_for(show)
                    s2 = None
                    if hasattr(src, "_to_show"):
                        s2 = src._to_show(detail)
                    elif S.api.huangguo_api:
                        s2 = S.api.huangguo_api._to_show(detail)
                    if s2:
                        s2.source = getattr(show, "source", None) or DEFAULT_SOURCE
                        show = s2
                        _index_show(show)
            except Exception:  # noqa: BLE001
                pass
            eps = S.api.episodes(show)
            out_dir = os.path.abspath(task.get("out") or S.out_dir)
            jobs, _have = _plan_by_records(
                show, eps, ep_filter=None, out_dir=out_dir, force=False,
            )
            task["followCheckedAt"] = now
            task["total"] = len(eps)
            if not jobs:
                S.put_task(task)
                continue
            merged = _merge_new_eps_into_task(task, show, jobs, eps, out_dir)
            if not merged:
                # 任务里没有 items 时直接补
                for j in jobs:
                    task.setdefault("items", []).append({
                        "ep": j.ep,
                        "status": "pending",
                        "note": "追更新增",
                        "path": j.path,
                    })
                task["plan"] = [j.ep for j in jobs]
                task["status"] = "queued"
                task["error"] = ""
                merged = task
            S.put_task(merged)
            enqueued += len(merged.get("plan") or [])
            kicked = run_download(str(merged["id"]))
            if kicked.get("ok"):
                started += 1
            else:
                errors.append(
                    f"{merged.get('title')}: {kicked.get('error') or '无法开始'}"
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{task.get('title') or vid}: {exc}")
            try:
                task["followCheckedAt"] = now
                S.put_task(task)
            except Exception:  # noqa: BLE001
                pass
    return {
        "ok": True,
        "checked": checked,
        "enqueued": enqueued,
        "started": started,
        "errors": errors,
    }


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
        "follow": bool(task.get("follow")),
        "followCheckedAt": float(task.get("followCheckedAt") or 0),
        "items": items_out,
    }
