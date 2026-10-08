#!/usr/bin/env python3
"""API smoke tests against local mock_api. No real network."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, TESTS)

import mock_api  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# Point settings at mock before app import side effects
SRV = mock_api.serve(0)
BASE = f"http://127.0.0.1:{SRV.server_port}"
TMP = tempfile.mkdtemp(prefix="hgapi_")
DATA = tempfile.mkdtemp(prefix="hgdata_")
os.environ["HG_API"] = BASE
os.environ["OUT_DIR"] = TMP
os.environ["DATA_DIR"] = DATA
os.environ["COVER_PROXY"] = f"{BASE}/proxy"
os.environ["COVER_TOKEN"] = mock_api.EXPECT_TOKEN
os.environ["API_TOKEN"] = "smoke-token"
os.environ["CACHE_TTL"] = "0"

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.main import app  # noqa: E402
from app.services.state import S  # noqa: E402

S.init(get_settings())
CLIENT = TestClient(app)
AUTH = {"Authorization": "Bearer smoke-token"}


class TestApiSmoke(unittest.TestCase):
    def test_health_requires_auth(self):
        r = CLIENT.get("/api/health")
        self.assertEqual(r.status_code, 401)

    def test_health_ok(self):
        r = CLIENT.get("/api/health", headers=AUTH)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_config(self):
        r = CLIENT.get("/api/config", headers=AUTH)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["authRequired"])
        self.assertEqual(body["out"], TMP)
        self.assertEqual(body["data"], DATA)
        self.assertTrue(any(c["value"] == "hot" for c in body["categories"]))

    def test_catalog_and_search(self):
        r = CLIENT.get("/api/catalog?category=hot&page=1", headers=AUTH)
        self.assertEqual(r.status_code, 200)
        items = r.json()["items"]
        self.assertGreaterEqual(len(items), 1)
        r2 = CLIENT.get("/api/search?q=都市", headers=AUTH)
        self.assertEqual(r2.status_code, 200)
        self.assertGreaterEqual(len(r2.json()["items"]), 1)

    def test_episodes(self):
        r = CLIENT.get("/api/episodes?id=1001", headers=AUTH)
        self.assertEqual(r.status_code, 200)
        eps = r.json()["episodes"]
        self.assertEqual(len(eps), 8)

    def test_download_and_task(self):
        r = CLIENT.post(
            "/api/download",
            headers=AUTH,
            json={"title": "都市逆袭传", "episodes": [1, 2], "cover": True},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        tid = body["taskId"]
        self.assertEqual(body["task"]["status"], "queued")
        # 创建不自动跑；手动 start
        r2 = CLIENT.post(f"/api/tasks/{tid}/start", headers=AUTH)
        self.assertEqual(r2.status_code, 200, r2.text)
        deadline = time.time() + 30
        status = "running"
        while time.time() < deadline:
            t = CLIENT.get(f"/api/tasks/{tid}", headers=AUTH).json()["task"]
            status = t["status"]
            if status in ("done", "error"):
                break
            time.sleep(0.3)
        self.assertEqual(status, "done")
        self.assertGreaterEqual(t["done"], 1)

    def test_cover(self):
        r = CLIENT.get("/api/cover?url=/enc/a.jpg", headers=AUTH)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"\xff\xd8\xff"))


if __name__ == "__main__":
    unittest.main()
