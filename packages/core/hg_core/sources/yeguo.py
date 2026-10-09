"""Yeguo (野果) adapter — encrypted api.php (AES-CBC).

Protocol (guoapp / public crawlers, 2026-10):
  POST/GET {api_base}{route}  e.g. https://www.yeguodj.com/api.php/api/theater/exploreList
  form: bundleId/version/oauth_* + route params
  response: {errcode:0, timestamp, data:<b64 AES>, sign}
  AES-CBC key/iv: API_KEY / API_IV (Pkcs7)
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from hg_core.ids import make_key

DEFAULT_API_LINES = (
    "https://www.yeguodj.com/api.php",
    "https://yeguodj.com/api.php",
    "https://analyze.buxefaex.cc/api.php",
    "https://adviser.tjecfkte.cc/api.php",
)

DEFAULT_SITE = "https://analyze.buxefaex.cc"

API_KEY = b"2acf7e91e9864673"
API_IV = b"1c29882d3ddfcfd6"
MEDIA_KEY = b"f5d965df75336270"
MEDIA_IV = b"97b60394abc2fbe1"

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

# Offline fallback themes (live list from /api/home/contentOptions)
FALLBACK_THEMES: list[tuple[str, str]] = [
    ("theme:7", "野果原创"),
    ("theme:8", "真人短剧"),
    ("theme:9", "魔改漫剧"),
    ("theme:10", "网红改编"),
    ("theme:11", "PMV裸舞"),
]

FILTER_DIMS = ("setting", "background", "time")
FILTER_TITLES = {"setting": "设定", "background": "背景", "time": "时间"}

FALLBACK_FILTERS: dict[str, list[tuple[str, str]]] = {
    "setting": [
        ("23", "家庭乱伦"),
        ("24", "职场淫乱"),
        ("25", "情色喜剧"),
        ("26", "绿帽淫妻"),
        ("27", "多H群交"),
        ("28", "后宫动漫"),
        ("29", "逆袭系统"),
    ],
    "background": [
        ("39", "校园"),
        ("40", "都市"),
        ("41", "乡村"),
        ("43", "古代"),
        ("44", "异界"),
        ("45", "末日"),
        ("46", "其他"),
    ],
    "time": [
        ("all", "全部"),
        ("1", "7天内"),
        ("2", "14天内"),
        ("3", "30天内"),
        ("4", "90天内"),
    ],
}


def _parse_yeguo_tab(tab: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not tab:
        return out
    for part in str(tab).split(","):
        piece = part.strip()
        if ":" not in piece:
            continue
        key, val = piece.split(":", 1)
        key, val = key.strip().lower(), val.strip()
        if key not in FILTER_DIMS or not val or val in ("all", "0"):
            continue
        out[key] = val
    return out


def _pkcs7_pad(data: bytes) -> bytes:
    n = 16 - (len(data) % 16)
    return data + bytes([n]) * n


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    n = data[-1]
    if 1 <= n <= 16:
        return data[:-n]
    return data


def _aes_decrypt(blob: str, key: bytes = API_KEY, iv: bytes = API_IV) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    ct = base64.b64decode(blob.replace(" ", "+").strip())
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return _pkcs7_unpad(dec.update(ct) + dec.finalize())


class YeguoSource:
    name = "yeguo"
    title = "野果"

    def __init__(
        self,
        base: str = "",
        *,
        timeout: int = 20,
        proxy: str = "",
        site: str = "",
        lines: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        self.lines = list(lines or DEFAULT_API_LINES)
        if base and str(base).strip():
            b = str(base).strip().rstrip("/")
            if not b.endswith("api.php"):
                b = b.rstrip("/") + "/api.php"
            if b in self.lines:
                self.lines.remove(b)
            self.lines.insert(0, b)
        self.api_base = self.lines[0]
        self.site = (site or DEFAULT_SITE).strip().rstrip("/") or DEFAULT_SITE
        self.timeout = timeout
        self.proxy = (proxy or "").strip()
        from hg_core import build_opener

        self.opener = build_opener(self.proxy)
        self._oauth = hashlib.md5(random.randbytes(16)).hexdigest()
        self._themes: list[tuple[str, str]] | None = None
        self._filters: dict[str, list[tuple[str, str]]] | None = None
        self._content_options: dict[str, Any] | None = None
        self._enabled = True

    @property
    def base(self) -> str:
        return self.site

    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": self.site + "/",
            "Origin": self.site,
        }

    def _common(self) -> dict[str, str]:
        return {
            "bundleId": "com.pwa.mater",
            "version": "1.3.2",
            "oauth_type": "web",
            "language": "zh",
            "via": "pwa",
            "oauth_id": self._oauth,
            "trace_id": self._oauth,
            "token": "",
        }

    def _call(
        self,
        route: str,
        params: dict[str, Any] | None = None,
        *,
        method: str = "POST",
        silent: bool = False,
    ) -> dict[str, Any]:
        values = self._common()
        if params:
            for k, v in params.items():
                if v is None:
                    continue
                values[str(k)] = str(v)
        qs = urllib.parse.urlencode(values)
        last_err: Exception | None = None
        for api in self.lines:
            url = api.rstrip("/") + route
            try:
                headers = dict(self.headers)
                if method.upper() == "GET":
                    req = urllib.request.Request(
                        url + "?" + qs, headers=headers, method="GET"
                    )
                else:
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                    req = urllib.request.Request(
                        url, data=qs.encode(), headers=headers, method="POST"
                    )
                with self.opener.open(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                env = json.loads(raw.decode("utf-8", "replace"))
                if int(env.get("errcode", -1)) != 0:
                    raise RuntimeError(
                        f"野果 errcode={env.get('errcode')} {env.get('msg') or ''}".strip()
                    )
                blob = env.get("data")
                if not isinstance(blob, str) or not blob:
                    raise RuntimeError("野果返回无加密数据")
                plain = _aes_decrypt(blob)
                payload = json.loads(plain.decode("utf-8"))
                # promote working line
                if api != self.api_base:
                    self.api_base = api
                    if api in self.lines:
                        self.lines.remove(api)
                        self.lines.insert(0, api)
                if isinstance(payload, dict) and "data" in payload:
                    data = payload["data"]
                    return data if isinstance(data, dict) else {"value": data}
                return payload if isinstance(payload, dict) else {"value": payload}
            except Exception as e:  # noqa: BLE001
                last_err = e
                if silent:
                    continue
                continue
        if silent:
            return {}
        raise RuntimeError(f"野果请求失败: {last_err}")

    def categories(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = [("hot", "热门"), ("new", "最新")]
        for tid, name in self._load_themes():
            out.append((tid, name))
        return out

    def tags(self) -> list[tuple[str, str]]:
        return []

    def browse_filters(self) -> dict[str, Any]:
        loaded = self._load_extra_filters()
        out: dict[str, Any] = {}
        for key in FILTER_DIMS:
            options = loaded.get(key) or []
            if not options:
                continue
            out[key] = {
                "title": FILTER_TITLES.get(key, key),
                "options": [{"value": v, "title": t} for v, t in options],
            }
        return out

    def _load_content_options(self) -> dict[str, Any]:
        if self._content_options is not None:
            return self._content_options
        try:
            data = self._call("/api/home/contentOptions", method="GET", silent=True)
            self._content_options = data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            self._content_options = {}
        return self._content_options

    def _load_extra_filters(self) -> dict[str, list[tuple[str, str]]]:
        if self._filters is not None:
            return self._filters
        filters = self._load_content_options().get("video_filter") or {}
        out: dict[str, list[tuple[str, str]]] = {}
        for key in FILTER_DIMS:
            block = filters.get(key) or {}
            rows = block.get("list") or []
            opts: list[tuple[str, str]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                value = row.get("value")
                name = str(row.get("name") or "").strip()
                if value is None or not name:
                    continue
                vid = "all" if str(value) == "0" else str(value)
                opts.append((vid, name))
            if opts:
                out[key] = opts
        if not out:
            out = {k: list(v) for k, v in FALLBACK_FILTERS.items()}
        self._filters = out
        return self._filters

    def _load_themes(self) -> list[tuple[str, str]]:
        if self._themes is not None:
            return self._themes
        try:
            filters = self._load_content_options().get("video_filter") or {}
            theme = filters.get("theme") or {}
            rows = theme.get("list") or []
            out: list[tuple[str, str]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                value = row.get("value")
                name = str(row.get("name") or "").strip()
                if value is None or not name:
                    continue
                out.append((f"theme:{value}", name))
            self._themes = out or list(FALLBACK_THEMES)
        except Exception:  # noqa: BLE001
            self._themes = list(FALLBACK_THEMES)
        return self._themes

    def _to_show(self, raw: dict) -> Any | None:
        from hg_core import Show

        rid = str(raw.get("video_id") or raw.get("id") or "").strip()
        if not rid:
            return None
        title = str(raw.get("title") or rid).strip()
        total = raw.get("episode_count") or raw.get("episodes") or raw.get("total_serial") or 0
        try:
            total = int(total or 0)
        except (TypeError, ValueError):
            total = 0
        cover = str(raw.get("cover") or "").strip()
        tags: list[str] = []
        for t in raw.get("tags") or []:
            if isinstance(t, str) and t.strip():
                tags.append(t.strip())
            elif isinstance(t, dict):
                n = str(t.get("name") or t.get("title") or "").strip()
                if n:
                    tags.append(n)
        status = str(raw.get("serialize_status") or "")
        finished = status in ("2", "finished", "done")
        hot = 0
        try:
            hot = int(raw.get("play_count") or raw.get("hot") or 0)
        except (TypeError, ValueError):
            hot = 0
            text = str(raw.get("play_count_text") or "")
            if text.endswith("万"):
                try:
                    hot = int(float(text[:-1]) * 10000)
                except ValueError:
                    hot = 0
        return Show(
            id=rid,
            title=title,
            total=total,
            finished=finished,
            cover=cover,
            tags=tags,
            hot=hot,
            source=self.name,
        )

    def catalog(
        self,
        category: str,
        page: int,
        page_size: int,
        *,
        sort: str | None = None,
        tab: str | None = None,
    ) -> list[Any]:
        page = max(1, int(page or 1))
        page_size = max(1, min(36, int(page_size or 20)))
        params: dict[str, Any] = {"page": page, "limit": page_size}
        cat = (category or "hot").strip()
        if cat.startswith("theme:"):
            params["theme"] = cat.split(":", 1)[1]
        elif cat not in ("hot", "new", "all", ""):
            # treat bare numeric as theme id
            if cat.isdigit():
                params["theme"] = cat
        sort_n = (sort or "").strip().lower()
        if sort_n == "new":
            params.setdefault("recommend", "2")
        elif sort_n == "hot" or cat in ("hot", "all", ""):
            params.setdefault("recommend", "1")
        elif cat == "new":
            params.setdefault("recommend", "2")
        for key, val in _parse_yeguo_tab(tab).items():
            params[key] = val
        try:
            data = self._call("/api/theater/exploreList", params)
        except RuntimeError:
            return []
        rows = data.get("list") or []
        out = []
        for row in rows:
            if isinstance(row, dict):
                s = self._to_show(row)
                if s:
                    out.append(s)
        return out

    def search(self, keyword: str, page: int = 1) -> list[Any]:
        kw = (keyword or "").strip()
        if not kw:
            return []
        page = max(1, int(page or 1))
        try:
            data = self._call(
                "/api/search/result",
                {"keyword": kw, "tab": "video", "page": page, "limit": 20},
            )
        except RuntimeError:
            return []
        rows = data.get("list") or []
        out = []
        for row in rows:
            if isinstance(row, dict):
                s = self._to_show(row)
                if s:
                    out.append(s)
        return out

    def detail(self, show: Any) -> dict[str, Any]:
        rid = str(getattr(show, "id", "") or "")
        data = self._call(
            "/api/playlet/detail",
            {
                "video_id": rid,
                "id": rid,
                "episode_id": "0",
                "related_limit": "0",
            },
        )
        # refresh show fields when possible
        try:
            s = self._to_show(data)
            if s and hasattr(show, "title"):
                show.title = s.title or show.title
                show.cover = s.cover or getattr(show, "cover", "")
                show.total = s.total or getattr(show, "total", 0)
                show.finished = s.finished
                show.tags = s.tags or getattr(show, "tags", [])
        except Exception:  # noqa: BLE001
            pass
        return data

    def episodes(self, show: Any) -> list[dict[str, Any]]:
        rid = str(getattr(show, "id", "") or "")
        try:
            data = self.detail(show)
        except RuntimeError:
            return []
        rows = data.get("episodes") or []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("is_adv") in (True, 1, "1"):
                continue
            eid = str(row.get("id") or "").strip()
            try:
                n = int(row.get("sort") or 0)
            except (TypeError, ValueError):
                n = 0
            if not eid or n < 1:
                continue
            title = str(row.get("title") or f"第{n}集").strip()
            out.append(
                {
                    "n": n,
                    "title": title,
                    "url": "",
                    "episode_id": eid,
                    "key": make_key(self.name, f"{rid}:{eid}"),
                }
            )
        out.sort(key=lambda e: int(e["n"]))
        if out and not getattr(show, "total", 0):
            try:
                show.total = max(int(e["n"]) for e in out)
            except Exception:  # noqa: BLE001
                pass
        return out

    def play_url(self, show: Any, ep: int, preset: str = "") -> str:  # noqa: ARG002
        rid = str(getattr(show, "id", "") or "")
        ep_n = max(1, int(ep or 1))
        # resolve episode_id from detail
        eps = self.episodes(show)
        episode_id = ""
        for e in eps:
            if int(e.get("n") or 0) == ep_n:
                episode_id = str(e.get("episode_id") or "")
                break
        if not episode_id and eps:
            # fallback: index
            idx = min(ep_n, len(eps)) - 1
            episode_id = str(eps[idx].get("episode_id") or "")
        if not episode_id:
            return ""
        try:
            data = self._call(
                "/api/playlet/play",
                {
                    "playlet_id": rid,
                    "video_id": rid,
                    "episode_id": episode_id,
                },
            )
        except RuntimeError:
            return ""
        url = str(data.get("video_url") or data.get("video_url_h265") or "").strip()
        if url.startswith("//"):
            url = "https:" + url
        return url

    def cover_url(self, show: Any) -> str:
        return str(getattr(show, "cover", "") or "").strip()

    def fetch_cover(self, url: str, dest: str, *, timeout: int = 30) -> tuple[bool, str]:
        u = (url or "").strip()
        if not u:
            return False, "empty"
        try:
            req = urllib.request.Request(
                u,
                headers={
                    "User-Agent": UA,
                    "Referer": self.site + "/",
                    "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                },
            )
            with self.opener.open(req, timeout=timeout) as resp:
                data = resp.read()
            if not data:
                return False, "empty body"
            with open(dest, "wb") as f:
                f.write(data)
            return True, ""
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def match(
        self, title: str, threshold: float = 0.62
    ) -> tuple[Any | None, float, list[Any]]:
        from difflib import SequenceMatcher

        cands = self.search(title) or []
        if not cands:
            return None, 0.0, []
        scored = []
        for s in cands:
            score = SequenceMatcher(None, title, s.title).ratio()
            scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [s for _, s in scored[:8]]
        best_score, best = scored[0]
        if best_score < threshold:
            return None, best_score, top
        return best, best_score, top
