#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mock_api.py — 模拟黄果 API，用于离线验证 hg_dl.py 的下载链路。

不联网、不碰真实内容。返回结构严格对齐 Widget 脚本里用的字段：
  /api/search?q=&page=      -> {data:{items:[...]}}
  /api/videos?page=&sort=   -> {data:{items:[...]}}
  /api/videos/{id}          -> {data:{title, cover, episodes:[{ep_num,title}]}}
  /api/videos/{id}/play?ep= -> {data:{video_url}}
  /media/ep{N}.mp4          -> 真实字节流，支持 Range（用来验断点续传）

片源是本地生成的确定性数据，不是任何真实内容。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# ---- 虚构剧集目录（刻意用带噪音标签的名字，验证清洗与匹配）----------------
CATALOG = [
    {"id": "1001", "title": "都市逆袭传",       "episode_count": 8,  "is_finished": 1,
     "cover": "/enc/a.jpg"},
    {"id": "1002", "title": "豪门夜色[1080p]", "episode_count": 5,  "is_finished": "0",
     "cover": "/enc/b.jpg"},
    {"id": "1003", "title": "重生之我在都市当高管(国语中字)", "episode_count": 3, "is_finished": False,
     "cover": "/enc/c.jpg"},
    {"id": "1004", "title": "AI短剧·漫改版",     "episode_count": 4,  "is_finished": 1,
     "cover": "/enc/d.jpg"},
    {"id": "1005", "title": "旧剧重播2024",     "episode_count": 2,  "is_finished": 1,
     "cover": "/enc/locked.jpg"},
]

SEARCH_EXTRA = [
    {"id": "2001", "title": "都市修仙传", "episode_count": 6, "is_finished": 1,
     "cover": "/enc/p1.jpg"},
    {"id": "2002", "title": "深夜食堂都市篇", "episode_count": 3, "is_finished": 0,
     "cover": "/enc/p2.jpg"},
]

# 这两部故意不实现 /api/videos/{id} 详情端点（返回 404），
# 用于验证"详情挂了要用列表 total 兜底"的降级路径。
NO_DETAIL = {"2001", "2002"}

EXPECT_TOKEN = "testtoken123"

EP_TITLES = {
    "1001": ["第1集 初入都市", "第2集 面试", "第3集 冲突", "第4集 反转",
             "第5集 布局", "第6集 交锋", "第7集 翻盘", "第8集 结局"],
}


def fake_media_bytes(vid: str, ep: int, size: int = 512 * 1024) -> bytes:
    """确定性伪媒体数据，同一集永远产出同样的字节，方便校验完整性。"""
    seed = f"{vid}:{ep}".encode()
    out = bytearray()
    h = hashlib.sha256(seed).digest()
    while len(out) < size:
        h = hashlib.sha256(h).digest()
        out.extend(h)
    return bytes(out[:size])


def fake_cover_bytes(vid: str, size: int = 24 * 1024) -> bytes:
    """确定性伪 JPEG：以 FFD8FF 开头（真 JPEG magic），后接确定性字节。"""
    seed = f"cover:{vid}".encode()
    out = bytearray(b"\xff\xd8\xff\xe0")
    h = hashlib.sha256(seed).digest()
    while len(out) < size:
        h = hashlib.sha256(h).digest()
        out.extend(h)
    out.extend(b"\xff\xd9")
    return bytes(out)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):        # 静音
        pass

    # -- 工具 ------------------------------------------------------------
    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data: bytes, ctype: str, code: int = 200,
               extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _not_found(self) -> None:
        self._json({"error": "not found"}, 404)

    # -- 路由 ------------------------------------------------------------
    def do_GET(self):                            # noqa: N802
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path

        if p == "/api/search":
            kw = q.get("q", "")
            items = [x for x in CATALOG + SEARCH_EXTRA if kw in x["title"]]
            return self._json({"data": {"items": items}})

        if p == "/api/ranks/hot":
            return self._json({"data": {"items": CATALOG[:3]}})

        if p == "/api/videos":
            items = CATALOG + SEARCH_EXTRA
            tag = q.get("tag")
            if tag:
                items = [x for x in CATALOG if tag.replace("都市", "") in x["title"] or "都市" in x["title"]]
            if q.get("sort") == "new":
                items = list(reversed(items))
            page = int(q.get("page", 1))
            size = int(q.get("page_size", 24))
            start = (page - 1) * size
            return self._json({"data": {"items": items[start:start + size],
                                        "total": len(items)}})

        m = re.fullmatch(r"/api/videos/category/([\w-]+)", p)
        if m:
            slug = m.group(1)
            items = list(CATALOG)
            if slug == "ai-manju":
                items = [x for x in items if "漫" in x["title"]] or items[:1]
            elif slug == "ai-huanlian":
                items = [x for x in items if "换脸" in x["title"]] or items[:1]
            elif slug == "ai-mogai":
                items = [x for x in items if "魔改" in x["title"]] or items[:1]
            if q.get("sort") == "new":
                items = list(reversed(items))
            page = int(q.get("page", 1))
            size = int(q.get("size", q.get("page_size", 24)))
            start = (page - 1) * size
            return self._json({"data": {"items": items[start:start + size],
                                        "pagination": {"page": page, "size": size,
                                                       "total": len(items)}}})

        m = re.fullmatch(r"/api/videos/(\w+)/play", p)
        if m:
            vid, ep = m.group(1), int(q.get("ep", 1))
            show = next((x for x in CATALOG if x["id"] == vid), None)
            if not show or ep > show["episode_count"]:
                return self._json({"data": {}})
            host = self.headers.get("Host", f"127.0.0.1:{self.server.server_port}")
            return self._json({"data": {"video_url": f"http://{host}/media/{vid}_ep{ep}.mp4"}})

        m = re.fullmatch(r"/api/videos/(\w+)", p)
        if m:
            vid = m.group(1)
            if vid in NO_DETAIL:
                return self._not_found()          # 故意 404，验降级
            show = next((x for x in CATALOG if x["id"] == vid), None)
            if not show:
                return self._not_found()
            titles = EP_TITLES.get(vid) or [f"第{i + 1}集" for i in range(show["episode_count"])]
            return self._json({"data": {
                "title": show["title"],
                "cover": show["cover"],
                "description": f"{show['title']} 简介",
                "episodes": [{"ep_num": i + 1, "title": t}
                             for i, t in enumerate(titles[:show["episode_count"]])],
            }})

        # 本机 AES 解不开的密文，必须走 /proxy
        if p == "/enc/locked.jpg":
            return self._bytes(b"\x00" * 64, "application/octet-stream")

        # ---- 原始加密封面（模拟需要代理解密）
        m = re.fullmatch(r"/enc/(\w+)\.jpg", p)
        if m:
            return self._bytes(fake_cover_bytes(m.group(1)), "image/jpeg")

        # ---- 解密代理：/proxy?url=<enc>&token=<t>
        if p == "/proxy":
            target = q.get("url", "")
            token = q.get("token", "")
            # 模拟真实代理的鉴权：token 不对就返回 JSON 错误（而非图片）
            if token != EXPECT_TOKEN:
                return self._json({"error": "invalid token", "got": token}, 403)
            mm = re.search(r"/enc/(\w+)\.jpg", target)
            if not mm:
                return self._json({"error": "unsupported url"}, 400)
            return self._bytes(fake_cover_bytes(mm.group(1)), "image/jpeg")

        # ---- 无封面地址的剧：用于验证降级
        if p == "/enc/none.jpg":
            return self._not_found()

        # ---- 代理返回 HTML 的情况（应被识别为失败而非存成坏图）
        if p == "/proxy/html":
            return self._bytes(b"<html><body>error</body></html>", "text/html")

        m = re.fullmatch(r"/media/(\w+)_ep(\d+)\.mp4", p)
        if m:
            vid, ep = m.group(1), int(m.group(2))
            data = fake_media_bytes(vid, ep)
            rng = self.headers.get("Range")
            if rng:
                mm = re.match(r"bytes=(\d+)-(\d*)", rng)
                start = int(mm.group(1)) if mm else 0
                if start >= len(data):
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{len(data)}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                chunk = data[start:]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers()
                self.wfile.write(chunk)
                return
            self.send_response(200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self._not_found()


def serve(port: int = 0) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8931
    srv = serve(port)
    print(f"mock api listening on http://127.0.0.1:{srv.server_port}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()