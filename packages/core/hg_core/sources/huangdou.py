"""Huangdou (黄豆) adapter — Forward Widget v3.1.1 compatible.

Protocol:
  POST {host}/api{path}
  body = IV(16) + AES-256-CBC(gzip(json), HMAC-SHA256(platform_key, rid), iv)
  Device login → token_userId in subsequent requests
  Categories via /drama/navList + navFilter + navBlock
  Playback: {host}/api/drama/hls/{id}/{seq}/play.m3u8?line=free
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import os
import time
import uuid
import urllib.error
import urllib.request
from typing import Any

from hg_core.ids import make_key

# Forward Worker LINES (china + oversea)
DEFAULT_LINES = (
    "https://lzlukvca.cc",
    "https://psfxhhox.top",
    "https://sxqirtho.top",
    "https://qicuknlj.top",
    "https://hddj05.com",
    "https://hddj06.com",
    "https://hddj07.com",
    "https://hvthtcpa.top",
)

PLATFORM_KEY = "7961beb44246e3012ce228d6b5ced05a"
API_VERSION = "1.0.0"
DEVICE_TYPE = "web"
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
)

# Forward enum → display; real codes resolved from navList
# 离线兜底频道（热门/最新由 sort 承担，不进分类）；现网以 navList 为准
ENUM_CATEGORIES: list[tuple[str, str]] = [
    ("yuandou", "黄豆原创"),
    ("mod", "魔改短剧"),
    ("caibian", "擦边短剧"),
    ("zhenren", "真人短剧"),
    ("erciyuan", "动漫"),
    ("aiman", "影院"),
    ("zongyi", "贤者"),
    ("heiliao", "黑料"),
]


class _AESCBC:
    @staticmethod
    def pad(data: bytes) -> bytes:
        n = 16 - (len(data) % 16)
        return data + bytes([n]) * n

    @staticmethod
    def unpad(data: bytes) -> bytes:
        if not data:
            return data
        n = data[-1]
        if 1 <= n <= 16:
            return data[:-n]
        return data

    @staticmethod
    def encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return enc.update(_AESCBC.pad(data)) + enc.finalize()

    @staticmethod
    def decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        return _AESCBC.unpad(dec.update(data) + dec.finalize())


class HuangdouSource:
    name = "huangdou"
    title = "黄豆"

    def __init__(
        self,
        base: str = "",
        *,
        timeout: int = 20,
        proxy: str = "",
        retries: int = 1,
        platform_key: str = PLATFORM_KEY,
        lines: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        self.lines = list(lines or DEFAULT_LINES)
        if base and base.strip():
            b = base.strip().rstrip("/")
            if b in self.lines:
                self.lines.remove(b)
            self.lines.insert(0, b)
        self.base = self.lines[0]
        self.timeout = timeout
        self.retries = retries
        self.platform_key = (platform_key or PLATFORM_KEY).strip()
        self.proxy = (proxy or "").strip()
        from hg_core import build_opener

        self.opener = build_opener(self.proxy)
        self.session_id = uuid.uuid4().hex
        self.device_id = str(uuid.uuid4()).lower()
        self.token = ""
        self.user_id = ""
        self._enabled = True
        self._live_base = ""
        self._nav_cache: list[dict] | None = None
        self._filter_cache: dict[str, list] = {}
        self.headers = {
            "User-Agent": UA,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    def categories(self) -> list[tuple[str, str]]:
        """仅频道大类；热门/最新用 catalog(sort=)，避免与前端排序重复。"""
        try:
            self._ensure_login()
            nav = self._nav_list()
            if nav:
                out: list[tuple[str, str]] = []
                seen: set[str] = set()
                for it in nav:
                    code = str(it.get("code") or "").strip().lower()
                    name = str(it.get("name") or code).strip()
                    if not code or code in seen or code in ("hot", "new"):
                        continue
                    seen.add(code)
                    out.append((code, name))
                if out:
                    return out
        except Exception:  # noqa: BLE001
            pass
        return list(ENUM_CATEGORIES)

    # ------------------------------------------------------------------ crypto
    def _key(self, rid: str) -> bytes:
        return hmac.new(
            self.platform_key.encode("utf-8"),
            bytes.fromhex(str(rid).replace("-", "")),
            hashlib.sha256,
        ).digest()

    def _decode(self, blob: bytes, rid: str) -> Any:
        if not blob:
            return {}
        if len(blob) < 32:
            try:
                return json.loads(blob.decode("utf-8", "replace"))
            except ValueError:
                return {}
        try:
            plain = _AESCBC.decrypt(blob[16:], self._key(rid), blob[:16])
            if plain[:2] == b"\x1f\x8b":
                plain = gzip.decompress(plain)
            return json.loads(plain.decode("utf-8"))
        except Exception:  # noqa: BLE001
            try:
                return json.loads(blob.decode("utf-8", "replace"))
            except ValueError:
                return {}

    def _token_value(self) -> str:
        if self.token and self.user_id:
            return f"{self.token}_{self.user_id}"
        return self.token or ""

    def _post_once(self, host: str, path: str, data: dict | None) -> Any:
        path = "/" + path.lstrip("/")
        rid = str(uuid.uuid4()).lower()
        key = self._key(rid)
        iv = os.urandom(16)
        raw = json.dumps(
            {
                "token": self._token_value(),
                "deviceId": self.device_id,
                "data": data or {},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        body = iv + _AESCBC.encrypt(gzip.compress(raw), key, iv)
        ts = int(time.time())
        # Forward v3: MD5(Dart|session|rid|ts|host/api/path) ; TVBox SHA256(path) also works
        # Prefer Forward MD5 over full URL-without-scheme for play/login stability
        url_clean = host.replace("https://", "").replace("http://", "").rstrip("/") + "/api" + path
        sign_src = f"Dart|{self.session_id}|{rid}|{ts}|{url_clean}"
        sign = hashlib.md5(sign_src.encode("utf-8")).hexdigest() + "-" + str(ts)
        headers = {
            **self.headers,
            "Origin": host,
            "Referer": host + "/home",
            "version": API_VERSION,
            "deviceType": DEVICE_TYPE,
            "time": str(ts),
            "sign": sign,
            "requestId": rid,
            "sessionId": self.session_id,
            "deviceBrand": "",
            "deviceModel": "",
            "systemName": "",
            "systemVersion": "",
        }
        url = host.rstrip("/") + "/api" + path
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with self.opener.open(req, timeout=self.timeout) as resp:
            blob = resp.read()
        return self._decode(blob, rid)

    def _api(self, path: str, data: dict | None = None, *, silent: bool = False) -> Any:
        if not self._enabled:
            return {}
        hosts: list[str] = []
        if self._live_base:
            hosts.append(self._live_base)
        for h in self.lines:
            if h not in hosts:
                hosts.append(h)
        last: Exception | None = None
        for host in hosts:
            for _ in range(self.retries + 1):
                try:
                    out = self._post_once(host, path, data)
                    if not out:
                        continue
                    # session expired → clear token and retry once
                    if (
                        isinstance(out, dict)
                        and out.get("status") == "n"
                        and str(out.get("errorCode") or out.get("error") or "") == "2002"
                    ):
                        self.token = ""
                        self.user_id = ""
                        continue
                    self._live_base = host
                    self.base = host
                    return out
                except (urllib.error.URLError, urllib.error.HTTPError, OSError, RuntimeError, ValueError) as exc:
                    last = exc
                    continue
        if last and not silent:
            raise RuntimeError(f"黄豆请求失败: {path} — {last}")
        return {}

    def _ensure_login(self) -> None:
        if self.token and self.user_id:
            return
        result = self._api(
            "/login/device",
            {
                "line_code": "china_1",
                "channel_code": "",
                "share_code": "",
                "clipboard_text": "",
                "device_info": {
                    "browserName": "BrowserName.safari",
                    "language": "zh-CN",
                    "userAgent": UA,
                    "platform": "iPhone",
                },
            },
            silent=True,
        )
        data = result.get("data") if isinstance(result, dict) else None
        if isinstance(data, dict) and data.get("token"):
            self.token = str(data.get("token") or "")
            self.user_id = str(data.get("user_id") or "")

    # ------------------------------------------------------------------ nav
    def _nav_list(self) -> list[dict]:
        if self._nav_cache is not None:
            return self._nav_cache
        result = self._api("/drama/navList", {}, silent=True)
        data = result.get("data") if isinstance(result, dict) else result
        lst: list = []
        if isinstance(data, dict):
            lst = data.get("list") or []
        elif isinstance(result, dict):
            lst = result.get("list") or []
        self._nav_cache = [x for x in lst if isinstance(x, dict)]
        return self._nav_cache

    def _resolve_code(self, enum_value: str) -> str:
        enum_value = (enum_value or "").strip()
        if not enum_value or enum_value in ("hot", "new", "all"):
            return enum_value
        name_map = {k: v for k, v in ENUM_CATEGORIES}
        nav = self._nav_list()
        for it in nav:
            if str(it.get("code") or "") == enum_value:
                return enum_value
        cn = name_map.get(enum_value, "")
        if cn:
            for it in nav:
                api_name = str(it.get("name") or "")
                if api_name and (cn in api_name or api_name in cn):
                    return str(it.get("code") or enum_value)
        return enum_value

    def _nav_filter(self, code: str) -> list[dict]:
        if code in self._filter_cache:
            return self._filter_cache[code]
        result = self._api("/drama/navFilter", {"code": str(code)}, silent=True)
        data = result.get("data") if isinstance(result, dict) else result
        lst = []
        if isinstance(data, dict):
            lst = data.get("list") or []
        self._filter_cache[code] = [x for x in lst if isinstance(x, dict)]
        return self._filter_cache[code]

    @staticmethod
    def _tab_id(tab: dict, index: int) -> str:
        tid = str(tab.get("tab") or "").strip()
        if tid:
            return tid
        flt = tab.get("filter") if isinstance(tab.get("filter"), dict) else {}
        for key in ("cat_id", "tag_id", "source"):
            val = flt.get(key)
            if val is not None and str(val).strip() != "":
                return f"{key}:{val}"
        return f"i:{index}"

    def channel_tabs(self, category: str) -> list[tuple[str, str]]:
        """频道内子 Tab：[(tab_id, name), ...]。"""
        code = self._resolve_code((category or "").strip())
        if not code or code in ("hot", "new", "all"):
            return []
        try:
            self._ensure_login()
        except RuntimeError:
            pass
        tabs = self._nav_filter(code)
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for i, t in enumerate(tabs):
            tid = self._tab_id(t, i)
            name = str(t.get("name") or tid).strip() or tid
            if tid in seen:
                continue
            seen.add(tid)
            out.append((tid, name))
        return out

    def _pick_tab(self, tabs: list[dict], tab: str | None) -> dict | None:
        if not tabs:
            return None
        want = (tab or "").strip()
        if not want:
            return tabs[0]
        for i, t in enumerate(tabs):
            if self._tab_id(t, i) == want:
                return t
        try:
            idx = int(want)
            if 0 <= idx < len(tabs):
                return tabs[idx]
        except ValueError:
            pass
        return tabs[0]

    # ------------------------------------------------------------------ parse
    @staticmethod
    def _list(data: Any) -> list[dict]:
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if not isinstance(data, dict):
            return []
        for key in ("list", "items", "data", "records"):
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
            if isinstance(val, dict):
                nested = HuangdouSource._list(val)
                if nested:
                    return nested
        return []

    def _nav_block_items(self, data: Any) -> list[dict]:
        blocks = self._list(data.get("data", data) if isinstance(data, dict) else data)
        items: list[dict] = []
        for b in blocks:
            nested = b.get("items") or b.get("dramas")
            if isinstance(nested, list):
                items.extend(x for x in nested if isinstance(x, dict))
            elif b.get("id") or b.get("drama_id"):
                items.append(b)
        return items

    def _to_show(self, raw: dict) -> Any | None:
        from hg_core import Show, _truthy

        rid = str(raw.get("id") or raw.get("drama_id") or "").strip()
        if not rid:
            return None
        rid = rid.replace("rp_", "")
        # strip channel prefix like xxx_
        if "_" in rid and not rid.replace("_", "").isalnum():
            pass
        title = str(raw.get("name") or raw.get("title") or raw.get("t") or rid).strip()
        total = raw.get("episode_count") or raw.get("free_episodes") or raw.get("total") or 0
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = 0
        cover = str(
            raw.get("img_y")
            or raw.get("img_x")
            or raw.get("img")
            or raw.get("cover")
            or raw.get("pic")
            or ""
        ).strip()
        tags: list[str] = []
        cat = raw.get("category") or raw.get("type") or ""
        if cat:
            tags.append(str(cat))
        finished = False
        label = str(raw.get("update_label") or "")
        if "全" in label or _truthy(raw.get("is_finished")):
            finished = True
        if str(raw.get("update_status") or "") in ("1", "finished", "done"):
            finished = True
        hot = 0
        try:
            hot = int(raw.get("hot") or raw.get("hot_rate") or raw.get("heat") or 0)
        except (TypeError, ValueError):
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
        if not self._enabled:
            return []
        page = max(1, int(page or 1))
        page_size = max(1, min(36, int(page_size or 18)))
        sort_n = (sort or "").strip().lower()
        if not sort_n:
            sort_n = "hot" if category == "hot" else "new"
        order = "hot" if sort_n == "hot" else "new"

        try:
            self._ensure_login()
        except RuntimeError:
            pass

        cat = (category or "hot").strip()
        # channel categories (yuandou / aiman / …)
        if cat not in ("hot", "new", "all", ""):
            try:
                code = self._resolve_code(cat)
                tabs = self._nav_filter(code)
                picked = self._pick_tab(tabs, tab)
                items: list[dict] = []
                if picked and picked.get("tab"):
                    data = self._api(
                        "/drama/navBlock",
                        {
                            "code": code,
                            "tab": str(picked.get("tab")),
                            "page": str(page),
                        },
                        silent=True,
                    )
                    items = self._nav_block_items(data)
                elif picked and isinstance(picked.get("filter"), dict):
                    flt = picked["filter"]
                    req: dict[str, Any] = {
                        "page": str(page),
                        "page_size": str(page_size),
                    }
                    if flt.get("cat_id"):
                        req["cat_id"] = flt["cat_id"]
                    if flt.get("tag_id"):
                        req["tag_id"] = flt["tag_id"]
                    if flt.get("source"):
                        req["source"] = flt["source"]
                    # 优先用前端排序；否则保留官方 filter.order
                    if sort_n in ("hot", "new"):
                        req["order"] = f"{sort_n}:top"
                    elif flt.get("order"):
                        req["order"] = flt["order"]
                    data = self._api("/drama/list", req, silent=True)
                    items = self._list(data)
                else:
                    # name search fallback
                    label = dict(ENUM_CATEGORIES).get(cat, cat)
                    data = self._api(
                        "/drama/list",
                        {
                            "page": str(page),
                            "page_size": str(page_size),
                            "keywords": label,
                            "order": f"{order}:top",
                        },
                        silent=True,
                    )
                    items = self._list(data)
                shows = [s for s in (self._to_show(r) for r in items) if s]
                if shows:
                    return shows[:page_size]
            except Exception:  # noqa: BLE001
                pass

        # default hot/new list
        try:
            data = self._api(
                "/drama/list",
                {
                    "page": str(page),
                    "page_size": str(page_size),
                    "order": order,
                },
            )
        except RuntimeError:
            return []
        return [s for s in (self._to_show(r) for r in self._list(data)) if s]

    def search(self, keyword: str, page: int = 1) -> list[Any]:
        if not self._enabled or not (keyword or "").strip():
            return []
        page = max(1, int(page or 1))
        try:
            self._ensure_login()
            data = self._api(
                "/drama/list",
                {
                    "page": str(page),
                    "page_size": "30",
                    "keywords": keyword.strip(),
                },
            )
        except RuntimeError:
            return []
        return [s for s in (self._to_show(r) for r in self._list(data)) if s]

    def detail(self, show: Any) -> dict[str, Any]:
        rid = str(getattr(show, "id", "") or "").replace("rp_", "")
        if not rid:
            return {}
        try:
            self._ensure_login()
            obj = self._api("/drama/detail", {"id": rid})
        except RuntimeError:
            return {}
        data = obj.get("data", obj) if isinstance(obj, dict) else {}
        return data if isinstance(data, dict) else {}

    def episodes(self, show: Any) -> list[dict[str, Any]]:
        detail = self.detail(show)
        raw = detail.get("episodes") if isinstance(detail.get("episodes"), list) else []
        out: list[dict[str, Any]] = []
        for i, ep in enumerate(raw):
            if not isinstance(ep, dict):
                continue
            n = ep.get("seq") or ep.get("episode") or ep.get("ep") or (i + 1)
            try:
                n = int(n)
            except (TypeError, ValueError):
                n = i + 1
            title = str(ep.get("name") or ep.get("title") or f"第{n}集")
            ep_type = str(ep.get("type") or "free")
            if ep_type != "free":
                title = f"{title} [VIP]"
            out.append({
                "n": n,
                "title": title,
                "url": self._free_hls(str(getattr(show, "id", "")), n),
            })
        out.sort(key=lambda x: x["n"])
        if not out:
            total = int(
                detail.get("episode_count")
                or detail.get("free_episodes")
                or getattr(show, "total", 0)
                or 0
            )
            rid = str(getattr(show, "id", "") or "")
            if total:
                out = [
                    {"n": n, "title": f"第{n}集", "url": self._free_hls(rid, n)}
                    for n in range(1, total + 1)
                ]
        return out

    def _free_hls(self, drama_id: str, seq: int, host: str | None = None) -> str:
        drama_id = str(drama_id or "").replace("rp_", "")
        base = (host or self._live_base or self.base).rstrip("/")
        return f"{base}/api/drama/hls/{drama_id}/{int(seq)}/play.m3u8?line=free"

    def play_url(self, show: Any, ep: int, preset: str = "") -> str:
        if preset:
            return preset
        rid = str(getattr(show, "id", "") or "").replace("rp_", "")
        if not rid:
            return ""
        # Prefer signed URL from /drama/play when available
        try:
            self._ensure_login()
            obj = self._api("/drama/play", {"id": rid, "seq": str(ep)}, silent=True)
            data = obj.get("data", {}) if isinstance(obj, dict) else {}
            if isinstance(data, dict):
                url = str(data.get("m3u8") or data.get("url") or "").strip()
                if url:
                    return url
        except RuntimeError:
            pass
        # Forward: VIP/free both work with ?line=free (no auth)
        return self._free_hls(rid, ep)

    def cover_url(self, show: Any) -> str:
        try:
            detail = self.detail(show)
            cand = (
                detail.get("img_y")
                or detail.get("img_x")
                or detail.get("cover")
                or detail.get("pic")
                or detail.get("img")
            )
            if cand:
                return str(cand).strip()
        except RuntimeError:
            pass
        return str(getattr(show, "cover", "") or "")

    def fetch_cover(self, url: str, dest: str, *, timeout: int = 30) -> tuple[bool, str]:
        from hg_core import DEFAULT_HEADERS, is_image_bytes

        if not url:
            return False, "无封面地址"
        try:
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        except OSError as exc:
            return False, f"建目录失败: {exc}"
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return True, "已存在"
        host = self._live_base or self.base
        img_headers = {
            "User-Agent": DEFAULT_HEADERS["User-Agent"],
            "Referer": host + "/",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        try:
            req = urllib.request.Request(url, headers=img_headers, method="GET")
            with self.opener.open(req, timeout=timeout) as resp:
                data = resp.read()
        except Exception as exc:  # noqa: BLE001
            return False, f"封面请求失败: {exc}"
        if not data or not is_image_bytes(data):
            return False, "封面不是有效图片"
        part = dest + ".part"
        try:
            with open(part, "wb") as fh:
                fh.write(data)
            os.replace(part, dest)
        except OSError as exc:
            return False, f"写入失败: {exc}"
        return True, "ok"

    def match(
        self, title: str, threshold: float = 0.62
    ) -> tuple[Any | None, float, list[Any]]:
        from hg_core import title_score

        cands = self.search(title) or []
        if not cands:
            return None, 0.0, []
        scored = sorted(
            ((title_score(title, c.title), c) for c in cands),
            key=lambda x: x[0],
            reverse=True,
        )
        best_score, best = scored[0]
        top = [c for _, c in scored[:5]]
        return (best, best_score, top) if best_score >= threshold else (None, best_score, top)

    def public_key(self, show: Any) -> str:
        return make_key(self.name, getattr(show, "id", ""))
