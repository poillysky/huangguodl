#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
web.py — hg-dl 的本地 Web 界面

后端：标准库 http.server，直接复用 hg_dl 的 HGApi / 下载器，前端是单文件HTML。
只监听 127.0.0.1，不对外暴露。

启动：
    python web.py                    # 默认 http://127.0.0.1:8899
    python web.py --port9000
    python web.py --dir "D:\\剧集"--api https://huangguoai.com
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import posixpath
import re
import socket
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import hg_dl
from hg_dl import (CATEGORIES, Cache, HGApi, Show, fmt_eps, human_size,
                   build_jobs, download, download_cover, parse_ep_filter,
                   print_episodes, print_shows, resolve_show, scan_local,
                   show_from_dict, target_path, already_done, cover_path)

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")

# --------------------------------------------------------------------------
# 全局状态
# --------------------------------------------------------------------------
class State:
    api: HGApi
    out_dir: str
    tasks: dict[str, dict]
    lock: threading.Lock
    alive: bool = True             # 服务是否还在运行，关停时置False 让任务线程收手

    @classmethod
    def init(cls, args: argparse.Namespace) -> None:
        out_dir = os.path.abspath(args.out)
        os.makedirs(out_dir, exist_ok=True)
        cache = Cache(os.path.join(out_dir, hg_dl.CACHE_FILE))
        cls.api = HGApi(args.api, cache=cache,
                        cache_ttl=0 if args.refresh else 1800, timeout=args.timeout)
        cls.out_dir = out_dir
        cls.tasks = {}
        cls.lock = threading.Lock()
        cls.show_index: dict[str, Show] = {}
        cls.cover_proxy = args.cover_proxy
        cls.cover_token = args.cover_token
        cls.scan_dir = args.dir or ""

    @classmethod
    def task(cls, tid: str) -> dict | None:
        with cls.lock:
            return cls.tasks.get(tid)

    @classmethod
    def put(cls, t: dict) -> None:
        with cls.lock:
            cls.tasks[t["id"]] = t
            # 只留最近 30 个任务
            if len(cls.tasks) > 30:
                for k in sorted(cls.tasks, key=lambda x: cls.tasks[x]["created"])[:-30]:
                    cls.tasks.pop(k, None)

    @classmethod
    def all_tasks(cls) -> list[dict]:
        with cls.lock:
            return sorted(cls.tasks.values(), key=lambda t: t["created"], reverse=True)


S = State()


# --------------------------------------------------------------------------
# 业务逻辑
# --------------------------------------------------------------------------
def show_json(s: Show) -> dict:
    return {"id": s.id, "title": s.title, "total": s.total,
            "finished": s.finished, "cover": s.cover, "label": s.label}


def get_catalog(category: str, page: int, page_size: int = 24) -> dict:
    shows = S.api.catalog(category, page, page_size)
    for s in shows:
        S.show_index[s.id] = s
    return {"items": [show_json(s) for s in shows], "category": category, "page": page}


def get_search(q: str, page: int = 1) -> dict:
    shows = S.api.search(q, page)
    for s in shows:
        S.show_index[s.id] = s
    return {"items": [show_json(s) for s in shows], "keyword": q, "page": page}


def find_show(tid: str) -> Show:
    """按 id 找剧。走本地缓存的目录，不额外打接口。"""
    if tid in S.show_index:
        return S.show_index[tid]
    for cat in ("hot", "new"):
        try:
            for s in S.api.catalog(cat, 1):
                S.show_index[s.id] = s
        except Exception:                              # noqa: BLE001
            continue
        if tid in S.show_index:
            break
    return S.show_index.get(tid, Show(id=tid, title=""))


def get_episodes(tid: str) -> dict:
    show = find_show(tid)
    eps = S.api.episodes(show)
    return {"id": tid, "title": show.title or tid, "episodes": eps}


def post_download(body: dict) -> dict:
    title = str(body.get("title") or "").strip()
    eps_sel = body.get("episodes") or []
    if isinstance(eps_sel, str):
        eps_sel = parse_ep_filter(eps_sel) or []
    ep_filter = set(int(x) for x in eps_sel) if eps_sel else None
    with_cover = bool(body.get("cover", True))
    out_dir = os.path.abspath(body.get("out") or S.out_dir)
    workers = max(1, min(8, int(body.get("workers") or 3)))
    scan_dir = body.get("scan_dir") or ""

    show, score, cands = S.api.match(title, float(body.get("threshold") or 0.62))
    if not show:
        return {"ok": False,
                "error": "未匹配到剧名",
                "candidates": [{"id": c.id, "title": c.title} for c in cands]}

    eps = S.api.episodes(show)
    local_map = scan_local(scan_dir) if scan_dir and os.path.isdir(scan_dir) else {}
    jobs, have = build_jobs(show, eps, ep_filter=ep_filter, local_map=local_map,
                            out_dir=out_dir)

    tid = f"t{int(time.time() * 1000) % 10 ** 10}"
    task = {
        "id": tid, "created": time.time(), "status": "running",
        "title": show.title, "vid": show.id, "out": out_dir,
        "cover": with_cover, "score": score,
        "total": len(eps), "have": have,
        "plan": [j.ep for j in jobs],
        "done": 0, "fail": 0, "coverNote": "",
        "items": [{"ep": j.ep, "status": "pending", "note": "", "path": j.path} for j in jobs],
    }
    S.put(task)

    def work() -> None:
        try:
            if with_cover:
                good, note = download_cover(show, S.api, out_dir, _CoverArgs(S))
                task["coverNote"] = note
                task["coverOk"] = good
            import concurrent.futures as futures
            with futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {pool.submit(download, j, S.api, out_dir, timeout=60, retries=3): j
                        for j in jobs}
                for fut in futures.as_completed(futs):
                    j = fut.result()
                    for it in task["items"]:
                        if it["ep"] == j.ep:
                            it["status"] = j.status
                            it["note"] = j.note
                            if j.path:
                                it["path"] = j.path
                            break
                    if j.status == "ok":
                        task["done"] += 1
                    elif j.status == "fail":
                        task["fail"] += 1
            task["status"] = "done"
        except Exception as exc:                       # noqa: BLE001
            task["status"] = "error"
            task["error"] = f"{exc}"
            task["trace"] = traceback.format_exc()[-1500:]
        finally:
            try:
                S.api.cache.save()
            except Exception:                          # noqa: BLE001
                pass

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "task": task}


class _CoverArgs:
    """给 download_cover 传参的轻量壳。"""
    def __init__(self, st: State):
        self.cover_proxy = st.cover_proxy
        self.cover_token = st.cover_token
        self.timeout = 30


def safe_under(root: str, path: str) -> str | None:
    """确保 path 是 root 之下的**文件**，防目录穿越。

    root 自身不算合法结果 —— 调用方都是要读文件的，拿到目录会导致后续
    打开失败或误判为"存在"。
    """
    try:
        rp = os.path.realpath(root)
        p = os.path.realpath(path)
        if p == rp or not p.startswith(rp + os.sep):
            return None
        return p
    except OSError:
        return None


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "hg-dl"

    def log_message(self, fmt: str, *args) -> None:      # 静音
        pass

    # -- 响应工具 --------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str,
              extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _err(self, code: int, msg: str) -> None:
        self._json({"ok": False, "error": msg}, code)

    def _static(self, path: str) -> None:
        rel = posixpath.normpath(path.lstrip("/")) or "index.html"
        if rel == "." or rel.startswith(".."):
            return self._err(403, "forbidden")
        full = os.path.realpath(os.path.join(HERE, rel))
        if safe_under(HERE, full) is None:
            return self._err(403, "forbidden")
        if not os.path.isfile(full):
            return self._err(404, "not found")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)

    # -- 路由 ------------------------------------------------------------
    def do_GET(self) -> None:                            # noqa: N802
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        p = u.path

        if p in ("/", "/index.html"):
            return self._static("index.html")
        if p == "/api/config":
            return self._json({
                "ok": True,
                "categories": [{"value": k, "title": v} for k, v in CATEGORIES.items()],
                "out": S.out_dir, "api": S.api.base,
                "coverProxy": S.cover_proxy, "scanDir": S.scan_dir,
            })
        if p == "/api/catalog":
            try:
                return self._json(get_catalog(q.get("category", "hot"),
                                              int(q.get("page", 1)),
                                              int(q.get("pageSize", 24))))
            except Exception as exc:                   # noqa: BLE001
                return self._err(502, f"拉目录失败: {exc}")
        if p == "/api/search":
            kw = q.get("q", "").strip()
            if not kw:
                return self._err(400, "关键词为空")
            try:
                return self._json(get_search(kw, int(q.get("page", 1))))
            except Exception as exc:                   # noqa: BLE001
                return self._err(502, f"搜索失败: {exc}")
        if p == "/api/episodes":
            try:
                return self._json(get_episodes(q.get("id", "")))
            except Exception as exc:                   # noqa: BLE001
                return self._err(502, f"取集数失败: {exc}")
        if p == "/api/local":
            root = q.get("dir") or S.scan_dir or S.out_dir
            m = scan_local(root)
            return self._json({"ok": True, "dir": root,
                               "shows": [{"title": k, "eps": sorted(v) if v else []}
                                         for k, v in list(m.items())[:200]]})
        if p == "/api/tasks":
            return self._json({"ok": True, "tasks": S.all_tasks()[:20]})
        if p == "/api/cover":
            # 代理封面给 <img> 用
            raw = q.get("url", "")
            url = hg_dl.build_cover_url(raw, S.api.base, S.cover_proxy, S.cover_token)
            if not url:
                return self._err(400, "无封面地址")
            try:
                hdrs = {"User-Agent": hg_dl.DEFAULT_HEADERS["User-Agent"],
                        "Referer": f"{S.api.base}/",
                        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
                req = urllib.request.Request(url, headers=hdrs)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = resp.read()
                    ct = resp.headers.get("Content-Type") or "image/jpeg"
            except Exception as exc:                   # noqa: BLE001
                return self._err(502, f"封面代理失败: {exc}")
            if not data or ct.split(";")[0] in ("text/html", "application/json"):
                return self._err(502, "代理未返回图片")
            return self._send(200, data, ct, {"Cache-Control": "max-age=600"})
        if p == "/api/file":
            # 预览已下载的封面/视频（限制在输出目录内）
            tgt = q.get("path", "")
            real = safe_under(S.out_dir, tgt)
            if real is None or not os.path.isfile(real):
                return self._err(404, "文件不存在或越界")
            ctype = mimetypes.guess_type(real)[0] or "application/octet-stream"
            size = os.path.getsize(real)
            rng = self.headers.get("Range")
            m = re.match(r"bytes=(\d+)-(\d*)", rng) if rng else None
            if m:
                start = int(m.group(1))
                with open(real, "rb") as fh:
                    fh.seek(start)
                    chunk = fh.read()
                return self._send(206, chunk, ctype,
                                  {"Content-Range": f"bytes {start}-{start + len(chunk) - 1}/{size}",
                                   "Accept-Ranges": "bytes"})
            with open(real, "rb") as fh:
                return self._send(200, fh.read(), ctype, {"Accept-Ranges": "bytes"})
        return self._static(p)

    def do_POST(self) -> None:                           # noqa: N802
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return self._err(400, "非法 JSON")

        if u.path == "/api/download":
            try:
                return self._json(post_download(body))
            except Exception as exc:                   # noqa: BLE001
                return self._err(500, f"启动下载失败: {exc}")
        if u.path == "/api/cover-only":
            title = str(body.get("title") or "").strip()
            out_dir = os.path.abspath(body.get("out") or S.out_dir)
            show, score, cands = S.api.match(title, float(body.get("threshold") or 0.62))
            if not show:
                return self._json({"ok": False, "error": "未匹配到剧名",
                                   "candidates": [{"id": c.id, "title": c.title} for c in cands]})
            good, note = download_cover(show, S.api, out_dir, _CoverArgs(S))
            S.api.cache.save()
            return self._json({"ok": True, "title": show.title,
                               "good": good, "note": note,
                               "path": cover_path(show, out_dir)})
        return self._err(404, "not found")


# --------------------------------------------------------------------------
# 启动
# --------------------------------------------------------------------------
def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="hg-dl 本地 Web 界面")
    ap.add_argument("--host", default="127.0.0.1", help="只建议本机")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--api", default=hg_dl.DEFAULT_API)
    ap.add_argument("--out", default=".", help="默认下载目录")
    ap.add_argument("--dir", default="", help="用于对比已有集的本地目录")
    ap.add_argument("--cover-proxy", default=hg_dl.DEFAULT_COVER_PROXY)
    ap.add_argument("--cover-token", default=hg_dl.DEFAULT_COVER_TOKEN)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--no-browser", action="store_true", help="不自动开浏览器")
    args = ap.parse_args(argv)

    State.init(args)

    port = args.port
    for _ in range(20):
        if port_available(args.host, port):
            break
        port += 1
    else:
        print("找不到可用端口", file=sys.stderr)
        return 1

    if not os.path.isfile(INDEX):
        print(f"缺少前端文件: {INDEX}", file=sys.stderr)
        return 1

    httpd = ThreadingHTTPServer((args.host, port), Handler)
    url = f"http://{args.host}:{port}"
    print(f"""
  hg-dl Web 已启动
  ─────────────────────────────────
  地址      {url}
  API       {args.api}
  下载到    {State.out_dir}
  本地对照  {args.dir or '(未设置)'}
  封面代理  {args.cover_proxy or '(直连)'}

  只监听本机。按 Ctrl+C 停止。
""")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())