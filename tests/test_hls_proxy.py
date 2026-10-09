"""Unit tests for HLS playlist rewrite."""

from __future__ import annotations

import os
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.services.hls_proxy import proxy_path, referer_for, rewrite_m3u8  # noqa: E402


class HlsProxyTest(unittest.TestCase):
    def test_rewrite_relative_and_key(self) -> None:
        src = (
            "#EXTM3U\n"
            '#EXT-X-KEY:METHOD=AES-128,URI="keys/1.key",IV=0x01\n'
            "#EXTINF:4,\n"
            "seg0.ts\n"
            "https://cdn.example/a.ts\n"
        )
        out = rewrite_m3u8(
            src,
            "https://play.example/hls/master.m3u8",
            lambda u: proxy_path(
                u, access_token="t", referer="https://play.example/home"
            ),
        )
        self.assertIn("/api/hls?", out)
        self.assertIn("access_token=t", out)
        self.assertIn("seg0.ts", out)
        self.assertIn("cdn.example", out)
        self.assertIn("1.key", out)

    def test_referer_by_host(self) -> None:
        self.assertTrue(referer_for("https://huangguoai.com/x").endswith("/"))
        self.assertIn(
            "/home",
            referer_for("https://lzlukvca.cc/api/drama/hls/1/1/play.m3u8"),
        )


if __name__ == "__main__":
    unittest.main()
