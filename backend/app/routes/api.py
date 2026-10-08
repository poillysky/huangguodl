from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import urllib.request
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from hg_core import (
    CATEGORIES,
    DEFAULT_HEADERS,
    Show,
    build_cover_url,
    decrypt_cover_bytes,
    is_image_bytes,
    sniff_image_mime,
)

from ..auth import require_token
from ..config import Settings, get_settings
from ..services.cover_cache import CoverDisk
from ..services.downloads import (
    _public_task,
    check_follow_tasks,
    find_show,
    run_download,
    set_task_follow,
    show_json,
    start_download,
)
from ..services.state import S

_COVER_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=604800, stale-while-revalidate=86400",
}

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


class DownloadBody(BaseModel):
    title: str = ""
    id: str | None = None
    episodes: list[int] | str | None = None
    cover: bool = True
    out: str | None = None
    workers: int | None = None
    scan_dir: str | None = None
    threshold: float = 0.62
    # True = create and start immediately; default only enqueue
    start: bool = False
    # True = 清完成记录并覆盖本地重下
    force: bool = False
    # True = 任务开启追更（每日只下新增集）
    follow: bool = False


class FollowBody(BaseModel):
    follow: bool = True


class SettingsBody(BaseModel):
    hg_api: str | None = None
    http_proxy: str | None = None
    cover_proxy: str | None = None
    cover_token: str | None = None


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "hg-dl"}


@router.get("/config")
def config(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    assert S.settings is not None
    return {
        "ok": True,
        "categories": [{"value": k, "title": v} for k, v in CATEGORIES.items()],
        "out": S.out_dir,
        "data": S.data_dir,
        "api": S.settings.hg_api,
        "httpProxy": S.settings.http_proxy,
        "coverProxy": S.settings.cover_proxy,
        "scanDir": settings.scan_dir,
        "authRequired": bool((settings.api_token or "").strip()),
    }


@router.get("/settings")
def get_runtime_settings() -> dict[str, Any]:
    assert S.settings is not None
    return {
        "ok": True,
        "hg_api": S.settings.hg_api,
        "http_proxy": S.settings.http_proxy,
        "cover_proxy": S.settings.cover_proxy,
        "cover_token": S.settings.cover_token,
        "out": S.out_dir,
        "data": S.data_dir,
    }


@router.put("/settings")
def put_runtime_settings(body: SettingsBody) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    snap = S.apply_settings(patch)
    return {"ok": True, **snap}


@router.post("/settings/test")
def test_upstream() -> dict[str, Any]:
    """Ping upstream catalog through current proxy."""
    assert S.api is not None
    try:
        shows = S.api.catalog("hot", 1, 3)
        return {
            "ok": True,
            "count": len(shows),
            "sample": [s.title for s in shows[:3]],
            "proxy": S.settings.http_proxy if S.settings else "",
            "api": S.api.base,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"上游不可达: {exc}") from exc


@router.get("/catalog")
def catalog(
    category: str = "hot",
    page: int = 1,
    pageSize: int = 20,
    sort: str = "",
) -> dict[str, Any]:
    assert S.api is not None
    sort_n = (sort or "").strip().lower()
    if sort_n not in ("hot", "new"):
        sort_n = ""
    try:
        shows = S.api.catalog(category, page, pageSize, sort=sort_n or None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"拉目录失败: {exc}") from exc
    for s in shows:
        S.show_index[s.id] = s
    return {
        "items": [show_json(s) for s in shows],
        "category": category,
        "page": page,
        "sort": sort_n or None,
    }


@router.get("/search")
def search(q: str = Query(..., min_length=1), page: int = 1) -> dict[str, Any]:
    assert S.api is not None
    try:
        shows = S.api.search(q.strip(), page)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"搜索失败: {exc}") from exc
    for s in shows:
        S.show_index[s.id] = s
    return {"items": [show_json(s) for s in shows], "keyword": q, "page": page}


class FavoriteBody(BaseModel):
    id: str
    title: str = ""
    cover: str = ""
    total: int = 0
    finished: bool = False
    label: str = ""
    tags: list[str] = []
    hot: int = 0


@router.get("/favorites")
def favorites_list() -> dict[str, Any]:
    items = S.list_favorites()
    return {"items": items, "count": len(items)}


@router.get("/favorites/{vid}")
def favorite_status(vid: str) -> dict[str, Any]:
    return {"id": vid, "favorited": S.is_favorite(vid)}


@router.post("/favorites")
def favorite_add(body: FavoriteBody) -> dict[str, Any]:
    item = S.add_favorite(body.model_dump())
    if not item:
        raise HTTPException(400, "缺少剧目 id")
    return {"ok": True, "item": item, "favorited": True}


@router.delete("/favorites/{vid}")
def favorite_remove(vid: str) -> dict[str, Any]:
    ok = S.remove_favorite(vid)
    return {"ok": ok, "id": vid, "favorited": False}


def _related_shows(show_id: str, detail: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    """猜你喜欢：热门/最新拉一批（常已缓存），按与本剧标签重合度排序。

    不串行打多个上游标签页，避免慢；相关度靠本地标签匹配。
    """
    assert S.api is not None
    want = {
        str(t).strip().lower()
        for t in (detail.get("tags") or [])
        if str(t).strip()
    }
    pool: list = []
    seen = {str(show_id)}
    for cat in ("hot", "new"):
        try:
            for s in S.api.catalog(cat, 1, 36):
                if s.id in seen:
                    continue
                seen.add(s.id)
                S.show_index[s.id] = s
                pool.append(s)
        except Exception:  # noqa: BLE001
            continue

    # 有标签时再补一次搜索（只 1 次），提高同题材比例
    tag = next(iter(want), "")
    if tag:
        try:
            for s in S.api.search(tag, 1)[:20]:
                if s.id in seen:
                    continue
                seen.add(s.id)
                S.show_index[s.id] = s
                pool.append(s)
        except Exception:  # noqa: BLE001
            pass

    def _score(s: Any) -> tuple[int, int]:
        stags = {str(t).strip().lower() for t in (s.tags or []) if str(t).strip()}
        overlap = len(want & stags) if want else 0
        return (overlap, int(s.hot or 0))

    pool.sort(key=_score, reverse=True)
    # 有标签时尽量先出有重合的；不够再用热门补齐
    if want:
        matched = [s for s in pool if _score(s)[0] > 0]
        rest = [s for s in pool if _score(s)[0] == 0]
        chosen = (matched + rest)[:limit]
    else:
        chosen = pool[:limit]
    return [show_json(x) for x in chosen]


@router.get("/show")
def show_detail(id: str = Query(..., min_length=1)) -> dict[str, Any]:
    assert S.api is not None
    try:
        show = find_show(id)
        detail = S.api.detail(show)
        eps = S.api.episodes(show)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"取详情失败: {exc}") from exc

    if isinstance(detail, dict):
        title = str(detail.get("title") or show.title or id)
        cover = str(detail.get("cover") or show.cover or "")
        tags = detail.get("tags") if isinstance(detail.get("tags"), list) else list(show.tags or [])
        tags = [str(t) for t in tags if t]
        finished = bool(detail.get("is_finished")) if "is_finished" in detail else show.finished
        try:
            total = int(detail.get("episode_count") or detail.get("total_episodes") or show.total or len(eps))
        except (TypeError, ValueError):
            total = show.total or len(eps)
        counts = detail.get("counts") if isinstance(detail.get("counts"), dict) else {}
        try:
            hot = int(counts.get("hot") or detail.get("hot") or show.hot or 0)
        except (TypeError, ValueError):
            hot = int(show.hot or 0)
        try:
            score = float(detail.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        desc = str(detail.get("description") or "").strip()
        author = ""
        if isinstance(detail.get("author"), dict):
            author = str(detail["author"].get("name") or "")
        channel = ""
        breadcrumb = detail.get("breadcrumb")
        if isinstance(breadcrumb, list) and breadcrumb:
            channel = str((breadcrumb[0] or {}).get("name") or "")
        show = Show(
            id=str(detail.get("id") or id),
            title=title,
            total=total,
            finished=finished,
            cover=cover,
            tags=tags,
            hot=hot,
        )
        S.show_index[show.id] = show
    else:
        title = show.title or id
        cover = show.cover
        tags = list(show.tags or [])
        finished = show.finished
        total = show.total or len(eps)
        hot = int(show.hot or 0)
        score = 0.0
        desc = ""
        author = ""
        channel = ""
        detail = {}

    # 猜你喜欢走独立接口，避免拖慢详情首屏
    return {
        "id": show.id,
        "title": title,
        "cover": cover,
        "tags": tags,
        "finished": finished,
        "total": total,
        "hot": hot,
        "score": score,
        "description": desc,
        "author": author,
        "channel": channel,
        "episodes": eps,
        "related": [],
        "label": show.label,
    }


@router.get("/related")
@router.get("/show/related")
def show_related(
    id: str = Query(..., min_length=1),
    limit: int = Query(8, ge=1, le=24),
    tags: str = Query(""),
) -> dict[str, Any]:
    """猜你喜欢（可慢加载；优先热门缓存，不再串行打多个上游）。"""
    if S.api is None:
        raise HTTPException(503, "服务未就绪")
    # 不二次拉详情：用索引里的剧 + 前端透传的 tags
    show = S.show_index.get(id) or find_show(id)
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    if not tag_list and show.tags:
        tag_list = [str(t) for t in show.tags if t]
    raw: dict[str, Any] = {"tags": tag_list}
    try:
        items = _related_shows(str(show.id or id), raw, limit=limit)
    except Exception:  # noqa: BLE001
        items = []
    return {"ok": True, "id": str(show.id or id), "items": items}


@router.get("/play")
def play(id: str = Query(..., min_length=1), ep: int = Query(1, ge=1)) -> dict[str, Any]:
    assert S.api is not None
    try:
        show = find_show(id)
        url = S.api.play_url(show, ep)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"取播放地址失败: {exc}") from exc
    if not url:
        raise HTTPException(404, "没有播放地址")
    return {"id": id, "ep": ep, "url": url}


@router.get("/episodes")
def episodes(id: str = Query(..., min_length=1)) -> dict[str, Any]:
    assert S.api is not None
    try:
        show = find_show(id)
        eps = S.api.episodes(show)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"取集数失败: {exc}") from exc
    return {"id": id, "title": show.title or id, "episodes": eps}


@router.post("/download")
def download_ep(body: DownloadBody) -> dict[str, Any]:
    return start_download(body.model_dump())


@router.get("/tasks")
def tasks() -> dict[str, Any]:
    return {"ok": True, "tasks": [_public_task(t) for t in S.all_tasks()[:20]]}


@router.get("/tasks/{tid}")
def task_one(tid: str) -> dict[str, Any]:
    t = S.get_task(tid)
    if not t:
        raise HTTPException(404, "task not found")
    return {"ok": True, "task": _public_task(t)}


@router.post("/tasks/{tid}/start")
def task_start(tid: str) -> dict[str, Any]:
    res = run_download(tid)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error") or "无法开始任务")
    return res


@router.post("/tasks/{tid}/follow")
def task_follow(tid: str, body: FollowBody) -> dict[str, Any]:
    """开启/关闭追更：每日检查新集，只下记录里没有的。"""
    res = set_task_follow(tid, bool(body.follow))
    if not res.get("ok"):
        raise HTTPException(404, res.get("error") or "task not found")
    return res


@router.post("/tasks/follow/check")
def tasks_follow_check() -> dict[str, Any]:
    """立刻检查全部追更任务（手动触发）。"""
    return check_follow_tasks(min_gap=0.0)


@router.delete("/tasks/{tid}")
def task_delete(tid: str) -> dict[str, Any]:
    """只删任务记录，不动 downloads 里的文件与完成记录。"""
    t = S.get_task(tid)
    if not t:
        raise HTTPException(404, "task not found")
    if t.get("status") == "running":
        raise HTTPException(400, "下载中的任务不能删除")
    if not S.drop_task(tid):
        raise HTTPException(404, "task not found")
    return {"ok": True, "id": tid}


@router.get("/tasks/{tid}/events")
async def task_events(tid: str, request: Request) -> EventSourceResponse:
    if S.get_task(tid) is None:
        raise HTTPException(404, "task not found")

    async def gen():
        idx = 0
        t = S.get_task(tid)
        if t:
            yield {
                "event": "snapshot",
                "data": json.dumps(_public_task(t), ensure_ascii=False),
            }
        while True:
            if await request.is_disconnected():
                break
            events = await asyncio.to_thread(S.wait_events, tid, idx, 20.0)
            if not events:
                yield {"event": "ping", "data": "{}"}
                t = S.get_task(tid)
                if t and t.get("status") in ("done", "error"):
                    yield {
                        "event": "snapshot",
                        "data": json.dumps(_public_task(t), ensure_ascii=False),
                    }
                    break
                continue
            for ev in events:
                idx += 1
                yield {
                    "event": ev.get("type", "message"),
                    "data": json.dumps(ev, ensure_ascii=False),
                }
                if ev.get("type") in ("done", "error"):
                    return

    return EventSourceResponse(gen())


def _assert_public_url(url: str) -> None:
    """SSRF 防护：/api/cover 的 url 由调用方给定，必须拒绝内网目标。

    拦截 loopback / 私网 / 链路本地(169.254.x.x 云元数据) / 保留段 / 组播，
    以及非 http(s) 协议（file://、gopher:// 等）。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, "仅支持 http/https 封面地址")
    host = parsed.hostname or ""
    if not host:
        raise HTTPException(400, "封面地址缺少主机名")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise HTTPException(502, f"封面域名无法解析: {exc}") from exc
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not ip.is_global:
            raise HTTPException(400, f"封面地址指向内网，已拒绝（{ip}）")


@router.get("/cover")
def cover_proxy(url: str = Query(..., min_length=1)) -> Response:
    """拉封面：CDN 直下 + 本机 AES 解密；命中 data/cover_cache 则直接返回。"""
    assert S.api is not None and S.settings is not None
    # 先拼成绝对地址，不走远程解密站
    final = build_cover_url(url, S.api.base, "", "")
    if not final:
        raise HTTPException(400, "无封面地址")
    _assert_public_url(final)

    hit = CoverDisk.get(final)
    if hit:
        data, mime = hit
        return Response(
            content=data,
            media_type=mime,
            headers={**_COVER_CACHE_HEADERS, "X-Cover-Cache": "HIT"},
        )

    headers = {
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
        "Referer": f"{S.api.base}/",
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    }
    data = b""
    err = ""
    try:
        req = urllib.request.Request(final, headers=headers)
        with S.api.open(req, timeout=25) as resp:
            data = resp.read()
            ct = (resp.headers.get("Content-Type") or "").lower()
        if not data:
            raise RuntimeError("空响应")
        if ct.startswith("text/html") or data.lstrip()[:1] in (b"{", b"["):
            raise RuntimeError(f"非图片响应({ct or 'unknown'})")
        if not is_image_bytes(data):
            data = decrypt_cover_bytes(data)
        mime = sniff_image_mime(data)
        CoverDisk.put(final, data, mime)
        return Response(
            content=data,
            media_type=mime,
            headers={**_COVER_CACHE_HEADERS, "X-Cover-Cache": "MISS"},
        )
    except Exception as exc:  # noqa: BLE001
        err = str(exc)

    # 兜底：远程封面解密站（多数网络下会失败，但保留兼容）
    alt = build_cover_url(
        url, S.api.base, S.settings.cover_proxy, S.settings.cover_token
    )
    if alt and alt != final:
        try:
            req = urllib.request.Request(alt, headers=headers)
            with S.api.open(req, timeout=25) as resp:
                data = resp.read()
            if data and is_image_bytes(data):
                mime = sniff_image_mime(data)
                CoverDisk.put(final, data, mime)
                return Response(
                    content=data,
                    media_type=mime,
                    headers={**_COVER_CACHE_HEADERS, "X-Cover-Cache": "MISS"},
                )
            if data and not is_image_bytes(data):
                data = decrypt_cover_bytes(data)
                mime = sniff_image_mime(data)
                CoverDisk.put(final, data, mime)
                return Response(
                    content=data,
                    media_type=mime,
                    headers={**_COVER_CACHE_HEADERS, "X-Cover-Cache": "MISS"},
                )
        except Exception as exc:  # noqa: BLE001
            err = f"{err}; 远程解密也失败: {exc}"
    raise HTTPException(502, f"封面失败: {err or 'unknown'}")
