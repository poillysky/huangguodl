#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_hg_dl.py — hg_dl.py 的离线端到端测试。

全部打本地 mock_api，不联网、不下载任何真实内容。
验证：目录拉取 → 剧名匹配 → 集数列表 → 计划生成 → 真实下载字节 →
      断点续传 → 去重跳过 → 噪音标签清洗 → 年份不误判。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import unittest

_TESTS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _TESTS)

import hg_dl
import mock_api

SRV = mock_api.serve()
BASE = f"http://127.0.0.1:{SRV.server_port}"


def api(cache=None, ttl=1800) -> hg_dl.HGApi:
    return hg_dl.HGApi(BASE, cache=cache, cache_ttl=ttl, retries=1, timeout=10)


class TestTitleParsing(unittest.TestCase):
    def test_extract_episode(self):
        cases = {
            "都市逆袭传 第1集": 1,
            "都市逆袭传 第 03 集": 3,
            "都市逆袭传.S01E05": 5,
            "都市逆袭传 EP07": 7,
            "都市逆袭传 - 12 [1080p]": 12,
            "都市逆袭传 2024": None,          # 年份不算集数
            "都市逆袭传": None,
        }
        for name, want in cases.items():
            with self.subTest(name=name):
                self.assertEqual(hg_dl.extract_episode(name), want)

    def test_clean_title(self):
        cases = {
            "都市逆袭传 [1080p][中文字幕]": "都市逆袭传",
            "重生之我在都市当高管(国语中字)": "重生之我在都市当高管",
            "豪门夜色 1080p WEB-DL": "豪门夜色",
            "某剧AI短剧": "某剧",
            "某剧2024": "某剧",                # 剥掉年份
        }
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(hg_dl.clean_title(raw), want)

    def test_title_score(self):
        self.assertEqual(hg_dl.title_score("都市逆袭传", "都市逆袭传"), 1.0)
        self.assertGreater(hg_dl.title_score("都市逆袭传", "都市逆袭传[1080p]"), 0.6)
        self.assertLess(hg_dl.title_score("都市逆袭传", "完全不同的一部剧"), 0.6)

    def test_fmt_eps(self):
        self.assertEqual(hg_dl.fmt_eps([1, 2, 3, 7]), "1-3, 7")
        self.assertEqual(hg_dl.fmt_eps([]), "无")


class TestCatalog(unittest.TestCase):
    def test_catalog(self):
        shows = api().catalog("hot", 1)
        self.assertEqual(len(shows), len(mock_api.CATALOG) + len(mock_api.SEARCH_EXTRA))
        self.assertEqual(shows[0].id, "1001")

    def test_finished_parsing(self):
        shows = {s.id: s for s in api().catalog("hot", 1)}
        self.assertTrue(shows["1001"].finished)          # is_finished = 1
        self.assertFalse(shows["1002"].finished)         # is_finished = "0" 字符串陷阱
        self.assertFalse(shows["1003"].finished)         # is_finished = False

    def test_tag_category(self):
        shows = api().catalog("tag:dushi", 1)
        self.assertTrue(shows)
        self.assertTrue(any("都市" in s.title for s in shows))

    def test_search(self):
        shows = api().search("都市")
        self.assertTrue(any(s.id == "1001" for s in shows))
        self.assertTrue(any(s.id == "2001" for s in shows))

    def test_match_exact_and_ambiguous(self):
        a = api()
        show, score, _ = a.match("都市逆袭传")
        self.assertIsNotNone(show)
        self.assertEqual(show.id, "1001")
        self.assertGreaterEqual(score, 0.62)

        # 名字对不上时应拒绝，而不是硬返回一个
        show2, _, cands = a.match("完全不相干的三百字片名 zzz")
        self.assertIsNone(show2)
        self.assertTrue(cands)      # 但应给出候选供参考


class TestEpisodes(unittest.TestCase):
    def test_episodes(self):
        a = api()
        show = next(s for s in a.catalog("hot", 1) if s.id == "1001")
        eps = a.episodes(show)
        self.assertEqual(len(eps), 8)
        self.assertEqual(eps[0]["n"], 1)
        self.assertEqual(eps[0]["title"], "第1集 初入都市")

    def test_episodes_fallback_from_total(self):
        """详情没给 episodes 时，用 total 造占位，保证仍能下。"""
        class Fake:
            id, title, total, finished = "1002", "豪门夜色", 5, False
        eps = api().episodes(Fake())
        self.assertEqual([e["n"] for e in eps], [1, 2, 3, 4, 5])

    def test_play_url(self):
        a = api()
        show = next(s for s in a.catalog("hot", 1) if s.id == "1001")
        url = a.play_url(show, 3)
        self.assertIn("/media/1001_ep3.mp4", url)


class TestLocalScan(unittest.TestCase):
    def test_scan_and_resume(self):
        tmp = tempfile.mkdtemp()
        try:
            blob = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * (64 * 1024)
            for ep in (1, 2, 3):
                with open(os.path.join(tmp, f"本地剧名 - 第{ep}集.mp4"), "wb") as fh:
                    fh.write(blob)
            # 残缺假文件不应计入已有
            with open(os.path.join(tmp, "本地剧名 - 第4集.mp4"), "wb") as fh:
                fh.write(b"#EXTM3U\n")
            m = hg_dl.scan_local(tmp)
            key = hg_dl.normalize(hg_dl.clean_title("本地剧名"))
            self.assertIn(key, m)
            self.assertEqual(m[key], {1, 2, 3})
            self.assertTrue(hg_dl.local_has(m, "本地剧名", 2))
            self.assertFalse(hg_dl.local_has(m, "本地剧名", 4))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestDownload(unittest.TestCase):
    """真起 HTTP、真收字节，但内容是 mock 生成的伪数据。"""

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="hgdl_")
        self.a = api(cache=hg_dl.Cache(os.path.join(self.out, "c.json")))
        self.show = next(s for s in self.a.catalog("hot", 1) if s.id == "1001")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_download_single(self):
        job = hg_dl.Job(show=self.show, ep=2)
        job = hg_dl.download(job, self.a, self.out, timeout=10, retries=1)
        self.assertEqual(job.status, "ok", job.note)
        self.assertTrue(os.path.exists(job.path))
        with open(job.path, "rb") as fh:
            got = fh.read()
        self.assertEqual(got, mock_api.fake_media_bytes("1001", 2))
        self.assertFalse(os.path.exists(job.path + ".part"))

    def test_download_concurrent(self):
        jobs = [hg_dl.Job(show=self.show, ep=n) for n in (1, 2, 3, 4)]
        with __import__("concurrent.futures").futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = [f.result() for f in
                       [pool.submit(hg_dl.download, j, self.a, self.out, timeout=10, retries=1)
                        for j in jobs]]
        self.assertTrue(all(r.status == "ok" for r in results),
                        [r.note for r in results])
        self.assertEqual(len({os.path.basename(r.path) for r in results}), 4)

    def test_resume_from_partial(self):
        """手动造一个半截 .part，应续传而不是重头下。"""
        full = mock_api.fake_media_bytes("1001", 5)
        part_path = os.path.join(self.out, "续传测试 - 第5集.mp4.part")
        prefix = full[: len(full) // 3]
        with open(part_path, "wb") as fh:
            fh.write(prefix)

        job = hg_dl.Job(show=self.show, ep=5,
                        path=os.path.join(self.out, "续传测试 - 第5集.mp4"))
        job = hg_dl.download(job, self.a, self.out, timeout=10, retries=1)
        self.assertEqual(job.status, "ok", job.note)
        with open(job.path, "rb") as fh:
            self.assertEqual(fh.read(), full)      # 字节完整 = 续传拼接正确

    def test_skip_existing(self):
        jobs, have = hg_dl.build_jobs(self.show, self.a.episodes(self.show),
                                     ep_filter=None, local_map={},
                                     out_dir=self.out)
        self.assertEqual(len(jobs), 8)
        self.assertEqual(have, [])

        j = jobs[0]
        os.makedirs(os.path.dirname(j.path), exist_ok=True)
        with open(j.path, "wb") as fh:
            # ftyp 头 + 体积达标，视为已存在
            fh.write(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * (256 * 1024))
        again = hg_dl.download(j, self.a, self.out, timeout=10, retries=1)
        self.assertEqual(again.status, "exist")

    def test_reject_m3u8_fake_mp4(self):
        """误存的 m3u8 不算已完成，应重新进入待下。"""
        path = hg_dl.target_path(self.show, 1, ".mp4", self.out)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"#EXTM3U\n#EXTINF:1,\nhttp://x/a.ts\n")
        self.assertFalse(hg_dl.already_done(path))
        jobs, have = hg_dl.build_jobs(
            self.show,
            self.a.episodes(self.show),
            ep_filter={1},
            local_map={},
            out_dir=self.out,
        )
        self.assertEqual(have, [])
        self.assertEqual([j.ep for j in jobs], [1])

    def test_skip_local_existing(self):
        """scan-dir 扫到的本地已有集应跳过（去重是默认行为）。"""
        fake_map = {hg_dl.normalize(self.show.title): {1, 2}}
        jobs, have = hg_dl.build_jobs(self.show, self.a.episodes(self.show),
                                     ep_filter=None, local_map=fake_map,
                                     out_dir=self.out)
        self.assertEqual(have, [1, 2])
        self.assertEqual([j.ep for j in jobs], [3, 4, 5, 6, 7, 8])

    def test_ep_filter(self):
        f = hg_dl.parse_ep_filter("1-3,7")
        jobs, have = hg_dl.build_jobs(self.show, self.a.episodes(self.show),
                                     ep_filter=f, local_map={},
                                     out_dir=self.out)
        self.assertEqual([j.ep for j in jobs], [1, 2, 3, 7])

    def test_invalid_ep_is_graceful(self):
        job = hg_dl.Job(show=self.show, ep=99)
        job = hg_dl.download(job, self.a, self.out, timeout=10, retries=1)
        self.assertEqual(job.status, "fail")
        self.assertIn("未返回播放地址", job.note)

    def test_target_path_sanitizes(self):
        show = hg_dl.Show(id="1", title='坏/名字:*?"<>|', total=1, finished=True)
        p = hg_dl.target_path(show, 3, "", self.out)
        self.assertEqual(os.path.basename(p), "坏_名字_______ - S01E03.mp4")
        season = os.path.basename(os.path.dirname(p))
        self.assertEqual(season, "Season 01")
        folder = os.path.basename(os.path.dirname(os.path.dirname(p)))
        self.assertNotRegex(folder, r'[\\/:*?"<>|]')
        self.assertTrue(folder.startswith("坏_名字"))
        self.assertTrue(p.endswith(".mp4"))


class TestCover(unittest.TestCase):
    """封面：URL 拼装、代理解密、非图片响应识别。"""

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="hgcover_")
        self.a = api(cache=hg_dl.Cache(os.path.join(self.out, "c.json")))
        self.show = next(s for s in self.a.catalog("hot", 1) if s.id == "1001")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_build_cover_url_absolute(self):
        u = hg_dl.build_cover_url("https://cdn/x.jpg", BASE, "", "")
        self.assertEqual(u, "https://cdn/x.jpg")

    def test_build_cover_url_scheme_relative(self):
        u = hg_dl.build_cover_url("//cdn/x.jpg", BASE, "", "")
        self.assertEqual(u, "https://cdn/x.jpg")

    def test_build_cover_url_relative(self):
        u = hg_dl.build_cover_url("/enc/a.jpg", BASE, "", "")
        self.assertEqual(u, f"{BASE}/enc/a.jpg")
        u2 = hg_dl.build_cover_url("enc/a.jpg", BASE, "", "")
        self.assertEqual(u2, f"{BASE}/enc/a.jpg")

    def test_build_cover_url_with_proxy(self):
        u = hg_dl.build_cover_url("/enc/a.jpg", BASE, f"{BASE}/proxy", "tk")
        self.assertIn(f"{BASE}/proxy?", u)
        self.assertIn("url=", u)
        self.assertIn("token=tk", u)
        # url 参数必须被编码，不能裸传斜杠
        self.assertNotIn("url=/enc/a.jpg", u)

    def test_build_cover_url_proxy_with_existing_query(self):
        u = hg_dl.build_cover_url("/a.jpg", BASE, f"{BASE}/proxy?k=1", "tk")
        self.assertIn("?k=1&url=", u)

    def test_build_cover_url_empty(self):
        self.assertEqual(hg_dl.build_cover_url("", BASE, "p", "t"), "")

    def test_fetch_cover_direct(self):
        ok, note = hg_dl.save_cover(self.show, self.a, self.out, "", "")
        self.assertTrue(ok, note)
        p = hg_dl.cover_path(self.show, self.out)
        self.assertTrue(os.path.exists(p))
        with open(p, "rb") as fh:
            got = fh.read()
        self.assertEqual(got[:4], b"\xff\xd8\xff\xe0")      # JPEG magic
        self.assertEqual(got, mock_api.fake_cover_bytes("a"))

    def test_fetch_cover_via_proxy(self):
        ok, note = hg_dl.save_cover(self.show, self.a, self.out,
                                    f"{BASE}/proxy", mock_api.EXPECT_TOKEN)
        self.assertTrue(ok, note)
        self.assertIn("image/jpeg", note)

    def test_proxy_bad_token_is_reported_not_saved(self):
        dest = hg_dl.cover_path(self.show, self.out)
        url = hg_dl.build_cover_url(
            self.a.cover_url(self.show), BASE, f"{BASE}/proxy", "WRONG"
        )
        ok, note = self.a.fetch_cover(url, dest)
        self.assertFalse(ok)
        # 代理的 JSON 错误原因必须透出来，不能只报个 403
        self.assertIn("403", note)
        self.assertIn("invalid token", note)
        self.assertFalse(os.path.exists(dest))

    def test_html_response_is_rejected(self):
        good, note = self.a.fetch_cover(f"{BASE}/proxy/html",
                                        os.path.join(self.out, "x.jpg"))
        self.assertFalse(good)
        self.assertIn("未返回图片", note)
        self.assertFalse(os.path.exists(os.path.join(self.out, "x.jpg")))

    def test_cover_skip_existing(self):
        p = hg_dl.cover_path(self.show, self.out)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(b"already")
        ok, note = hg_dl.save_cover(self.show, self.a, self.out, "", "")
        self.assertTrue(ok)
        self.assertIn("已存在", note)

    def test_missing_cover_is_graceful(self):
        s = hg_dl.Show(id="9999", title="没封面的剧", cover="")
        self.a.cache.set("detail:9999", {})       # 详情也没有 cover
        ok, note = hg_dl.save_cover(s, self.a, self.out, "", "")
        self.assertFalse(ok)
        self.assertIn("无封面地址", note)

    def test_cover_prefers_detail_over_list(self):
        """详情里的 cover 更准，应优先于列表里的。"""
        self.a.cache.set("detail:1001", {"cover": "/enc/detail.jpg"})
        raw = self.a.cover_url(self.show)
        self.assertEqual(raw, "/enc/detail.jpg")

    def test_show_from_dict_backward_compat(self):
        """老缓存没有 cover 字段也不该崩。"""
        s = hg_dl.show_from_dict({"id": "1", "title": "旧缓存剧", "total": 3})
        self.assertEqual(s.cover, "")
        self.assertEqual(s.total, 3)
        s2 = hg_dl.show_from_dict({"id": "1", "title": "x", "cover": "/c.jpg",
                                   "未来字段": 1})
        self.assertEqual(s2.cover, "/c.jpg")

    def test_cover_filename_sanitized(self):
        s = hg_dl.Show(id="1", title='封面/剧名:*?"<>|')
        p = hg_dl.cover_path(s, self.out)
        self.assertEqual(os.path.basename(p), "poster.jpg")
        self.assertNotRegex(os.path.basename(os.path.dirname(p)), r'[\\/:*?"<>|]')

    def test_emby_nfo_and_layout(self):
        ok, note = hg_dl.save_cover(self.show, self.a, self.out, "", "")
        self.assertTrue(ok, note)
        root = hg_dl.show_dir(self.show, self.out)
        self.assertTrue(os.path.isfile(os.path.join(root, "poster.jpg")))
        self.assertTrue(os.path.isfile(os.path.join(root, "tvshow.nfo")))
        season = os.path.join(root, "Season 01")
        self.assertTrue(os.path.isfile(os.path.join(season, "poster.jpg")))
        self.assertTrue(os.path.isfile(os.path.join(season, "season.nfo")))
        with open(os.path.join(root, "tvshow.nfo"), encoding="utf-8") as fh:
            nfo = fh.read()
        self.assertIn("<tvshow>", nfo)
        self.assertIn(self.show.title, nfo)

        job = hg_dl.Job(show=self.show, ep=1, ep_title="第一集")
        job = hg_dl.download(job, self.a, self.out, timeout=10, retries=1)
        self.assertEqual(job.status, "ok", job.note)
        self.assertIn("Season 01", job.path.replace("\\", "/"))
        self.assertIn("S01E01", os.path.basename(job.path))
        nfo_ep = os.path.splitext(job.path)[0] + ".nfo"
        self.assertTrue(os.path.isfile(nfo_ep))
        with open(nfo_ep, encoding="utf-8") as fh:
            enfo = fh.read()
        self.assertIn("<episodedetails>", enfo)
        self.assertIn("<episode>1</episode>", enfo)


class TestCache(unittest.TestCase):
    def test_roundtrip_and_ttl(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "c.json")
            c = hg_dl.Cache(p)
            c.set("k", {"v": 1})
            c.save()                              # 落盘后才可被新实例读到
            self.assertEqual(hg_dl.Cache(p).get("k", 60), {"v": 1})
            self.assertIsNone(hg_dl.Cache(p).get("k", 0))   # ttl=0 视为过期（--refresh 用）
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_corrupt_cache_is_tolerated(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "c.json")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("{ not json")
            c = hg_dl.Cache(p)          # 不应抛异常
            c.set("k", 1)
            c.save()
            self.assertEqual(hg_dl.Cache(p).get("k", 60), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)