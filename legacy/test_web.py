#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_web.py — web.py 后端接口测试

真起 HTTP 服务、真发请求打各接口。数据源是本地 mock_api，不联网、不下载真实内容。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TESTS = os.path.join(ROOT, "tests")
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)
sys.path.insert(0, HERE)

import mock_api                                        # noqa: E402
import hg_dl                                            # noqa: E402
import web                                              # noqa: E402

MOCK = mock_api.serve()
BASE = f"http://127.0.0.1:{MOCK.server_port}"
OUT = tempfile.mkdtemp(prefix="hgweb_")
SRV: ThreadingHTTPServer | None = None
ROOT = ""


def req(path: str, data: dict | None = None, raw: bytes | None = None) -> tuple[int, bytes, str]:
    url = ROOT + path
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif raw is not None:
        body = raw
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=body, headers=headers,
                               method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")


def code_only(path: str) -> int:
    """只看状态码的便捷版。"""
    return req(path)[0]


def js(path: str, data: dict | None = None) -> tuple[int, dict]:
    code, body, _ = req(path, data)
    try:
        return code, json.loads(body.decode("utf-8"))
    except ValueError:
        return code, {"_raw": body[:200].decode("utf-8", "replace")}


def setUpModule() -> None:
    global SRV, ROOT
    web.State.init(argparse_ns())
    SRV = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=SRV.serve_forever, daemon=True).start()
    ROOT = f"http://127.0.0.1:{SRV.server_address[1]}"


def tearDownModule() -> None:
    if SRV:
        SRV.shutdown()
        SRV.server_close()
    shutil.rmtree(OUT, ignore_errors=True)
    MOCK.shutdown()


def argparse_ns():
    import argparse
    return argparse.Namespace(
        out=OUT, api=BASE, dir="", refresh=False, timeout=15,
        cover_proxy=f"{BASE}/proxy", cover_token=mock_api.EXPECT_TOKEN)


class TestPages(unittest.TestCase):
    def test_index_served(self):
        code, body, ct = req("/")
        self.assertEqual(code, 200)
        self.assertIn("text/html", ct)
        h = body.decode("utf-8")
        self.assertIn("hg-dl", h)
        self.assertIn("id=\"grid\"", h)
        self.assertIn("id=\"deps\"", h)
        self.assertIn("/api/download", h)

    def test_missing_static_404(self):
        self.assertEqual(code_only("/nope.html"), 404)

    def test_static_traversal_blocked(self):
        for evil in ("/../hg_dl.py", "/../../etc/passwd", "/..%2f..%2fwin.ini"):
            self.assertIn(code_only(evil), (403, 404), evil)


class TestConfig(unittest.TestCase):
    def test_config(self):
        code, d = js("/api/config")
        self.assertEqual(code, 200)
        self.assertTrue(d["ok"])
        self.assertEqual(d["out"], os.path.abspath(OUT))
        cats = {c["value"] for c in d["categories"]}
        self.assertIn("hot", cats)
        self.assertIn("tag:dushi", cats)
        self.assertEqual(len(cats), len(hg_dl.CATEGORIES))

    def test_token_not_leaked_to_browser(self):
        """封面 token 不该出现在任何前端可见的响应里。"""
        code, body, _ = req("/api/config")
        self.assertNotIn(mock_api.EXPECT_TOKEN.encode(), body)
        code, body, _ = req("/")
        self.assertNotIn(b"coverToken", body)


class TestCatalog(unittest.TestCase):
    def test_catalog(self):
        code, d = js("/api/catalog?category=hot&page=1")
        self.assertEqual(code, 200)
        self.assertTrue(d["items"])
        self.assertIn("id", d["items"][0])
        self.assertIn("title", d["items"][0])
        self.assertIn("total", d["items"][0])

    def test_catalog_tag(self):
        code, d = js("/api/catalog?category=tag:dushi")
        self.assertEqual(code, 200)

    def test_search(self):
        code, d = js("/api/search?q=" + urllib.parse.quote("都市"))
        self.assertEqual(code, 200)
        self.assertTrue(d["items"])

    def test_search_empty_kw_400(self):
        code, d = js("/api/search?q=")
        self.assertEqual(code, 400)
        self.assertFalse(d["ok"])

    def test_show_index_populated(self):
        js("/api/catalog?category=hot")
        code, d = js("/api/episodes?id=1001")
        self.assertEqual(code, 200)
        self.assertEqual(len(d["episodes"]), 8)
        self.assertEqual(d["title"], "都市逆袭传")

    def test_episodes_degrade_404_detail(self):
        """2001 没有详情端点，应降级用 total 兜底而不是 500。"""
        code, d = js("/api/episodes?id=2001")
        self.assertEqual(code, 200)
        self.assertEqual(len(d["episodes"]), 6)


class TestCoverProxy(unittest.TestCase):
    def test_cover_via_proxy(self):
        code, body, ct = req("/api/cover?url=" + urllib.parse.quote("/enc/a.jpg"))
        self.assertEqual(code, 200)
        self.assertIn("image", ct)
        self.assertEqual(body[:4], b"\xff\xd8\xff\xe0")

    def test_cover_bad_token_502(self):
        """token 错时返回 502，且响应是 JSON 不是坏图。"""
        old = web.S.cover_token
        web.S.cover_token = "WRONG"
        try:
            code, body, _ = req("/api/cover?url=" + urllib.parse.quote("/enc/a.jpg"))
            self.assertEqual(code, 502)
            self.assertNotEqual(body[:2], b"\xff\xd8")
        finally:
            web.S.cover_token = old

    def test_cover_empty_url_400(self):
        code, _ = js("/api/cover?url=")
        self.assertEqual(code, 400)

    def test_cover_html_response_rejected(self):
        code, body, _ = req("/api/cover?url=" + urllib.parse.quote("/proxy/html"))
        self.assertEqual(code, 502)
        self.assertNotEqual(body[:4], b"\xff\xd8")


class TestLocal(unittest.TestCase):
    def test_local_scan(self):
        d = tempfile.mkdtemp(prefix="hgscan_")
        try:
            for n in (1, 2):
                with open(os.path.join(d, f"某剧 - 第{n}集.mp4"), "wb") as fh:
                    fh.write(b"x")
            code, j = js("/api/local?dir=" + urllib.parse.quote(d))
            self.assertEqual(code, 200)
            self.assertTrue(j["shows"])
            hit = [s for s in j["shows"] if "某剧" in s["title"]]
            self.assertTrue(hit)
            self.assertEqual(hit[0]["eps"], [1, 2])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_local_bad_dir_no_crash(self):
        code, d = js("/api/local?dir=/definitely/not/here")
        self.assertEqual(code, 200)
        self.assertEqual(d["shows"], [])


class TestDownloadAPI(unittest.TestCase):
    def setUp(self):
        """每个下载用例独立输出目录，避免互相串扰。"""
        self.out = tempfile.mkdtemp(prefix="hgdl_")
        self.addCleanup(shutil.rmtree, self.out, True)

    def test_start_download_and_poll(self):
        code, d = js("/api/download", {
            "title": "都市逆袭传", "episodes": [1, 2], "out": self.out,
            "workers": 2, "cover": True})
        self.assertEqual(code, 200, d)
        self.assertTrue(d["ok"], d)
        self.assertEqual(d["task"]["status"], "queued")
        tid = d["task"]["id"]

        code, d2 = js(f"/api/tasks/{tid}/start", {})
        self.assertEqual(code, 200, d2)

        # 轮询直到完成
        task = None
        for _ in range(80):
            code, t = js("/api/tasks")
            self.assertEqual(code, 200)
            task = next((x for x in t["tasks"] if x["id"] == tid), None)
            if task and task["status"] in ("done", "error"):
                break
            time.sleep(0.15)
        self.assertIsNotNone(task)
        self.assertEqual(task["status"], "done", task.get("error"))
        self.assertEqual(task["done"], 2)
        self.assertEqual(task["fail"], 0)

        files = []
        for dirpath, _dirs, names in os.walk(self.out):
            for fn in names:
                if fn.endswith(".mp4"):
                    files.append(os.path.join(dirpath, fn))
        self.assertEqual(len(files), 2, files)
        jpgs = []
        for dirpath, _dirs, names in os.walk(self.out):
            for fn in names:
                if fn.endswith(".jpg"):
                    jpgs.append(fn)
        self.assertTrue(any(n == "poster.jpg" for n in jpgs), jpgs)
        self.assertTrue(
            any(os.path.basename(os.path.dirname(f)) == "Season 01" for f in files),
            files,
        )

        # 内容必须是 mock 的确定性字节
        for f in files:
            with open(f, "rb") as fh:
                ep = 1 if "E01" in os.path.basename(f) else 2
                self.assertEqual(fh.read(), mock_api.fake_media_bytes("1001", ep))

    def test_download_unknown_title_returns_candidates(self):
        code, d = js("/api/download", {"title": "不存在的剧xyz", "out": self.out})
        self.assertEqual(code, 200)
        self.assertFalse(d["ok"])
        self.assertIn("candidates", d)
        self.assertTrue(d["candidates"])

    def test_download_bad_json_400(self):
        code, body, _ = req("/api/download", raw=b"{not json")
        self.assertEqual(code, 400)

    def test_download_missing_title_ok_false(self):
        code, d = js("/api/download", {"episodes": [1], "out": self.out})
        self.assertEqual(code, 200)
        self.assertFalse(d["ok"])

    def test_episodes_filter_respected(self):
        code, d = js("/api/download", {
            "title": "豪门夜色", "episodes": "1", "out": self.out,
            "workers": 1, "cover": False})
        self.assertEqual(code, 200, d)
        self.assertEqual(d["task"]["plan"], [1])

    def test_scan_dir_skips_existing(self):
        """已有第1集时，下载 1-2 应只排第2集。"""
        with open(os.path.join(self.out, "豪门夜色[1080p] - 第1集.mp4"), "wb") as fh:
            fh.write(b"already")
        code, d = js("/api/download", {
            "title": "豪门夜色", "episodes": [1, 2], "out": self.out,
            "scan_dir": self.out, "workers": 1, "cover": False})
        self.assertEqual(code, 200, d)
        self.assertEqual(d["task"]["plan"], [2])
        self.assertEqual(d["task"]["have"], [1])

    def test_cover_only(self):
        code, d = js("/api/cover-only",
                     {"title": "重生之我在都市当高管", "out": self.out})
        self.assertEqual(code, 200)
        self.assertTrue(d["ok"])
        self.assertTrue(d["good"], d.get("note"))
        self.assertTrue(os.path.exists(d["path"]))


class TestSecurity(unittest.TestCase):
    def test_file_outside_outdir_blocked(self):
        code, _ = js("/api/file?path=" + urllib.parse.quote("C:/Windows/win.ini"))
        self.assertEqual(code, 404)

    def test_file_traversal_blocked(self):
        evil = os.path.abspath(os.path.join(OUT, "..", "hg_dl.py"))
        code, _ = js("/api/file?path=" + urllib.parse.quote(evil))
        self.assertEqual(code, 404)

    def test_safe_under(self):
        self.assertIsNotNone(web.safe_under(OUT, os.path.join(OUT, "a.mp4")))
        self.assertIsNone(web.safe_under(OUT, os.path.join(OUT, "..", "x.mp4")))
        self.assertIsNone(web.safe_under(OUT, OUT))


class TestTaskState(unittest.TestCase):
    def test_task_capped(self):
        for i in range(40):
            web.S.put({"id": f"cap{i}", "created": time.time(), "status": "done",
                       "title": "t", "plan": [], "items": [], "done": 0, "fail": 0})
        self.assertLessEqual(len(web.S.all_tasks()), 30)

    def test_show_index_caching(self):
        js("/api/catalog?category=hot")
        self.assertTrue(web.S.show_index)
        s = web.find_show("1001")
        self.assertEqual(s.title, "都市逆袭传")
        # 再调一次应走缓存，结果一致
        self.assertEqual(web.find_show("1001").title, "都市逆袭传")


if __name__ == "__main__":
    unittest.main(verbosity=2)