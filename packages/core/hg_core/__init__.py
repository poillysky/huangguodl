"""hg_core — shared library for CLI and FastAPI backend."""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

# Emby / Kodi 短剧默认塞进第一季
EMBY_SEASON = 1
EMBY_SEASON_DIR = "Season 01"

# --------------------------------------------------------------------------
# 默认配置
# --------------------------------------------------------------------------
DEFAULT_API = os.environ.get("HG_API", "https://huangguoai.com")
DEFAULT_COVER_PROXY = os.environ.get("COVER_PROXY", "https://ai.wulii.de5.net")
DEFAULT_COVER_TOKEN = os.environ.get("COVER_TOKEN", "")
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15"
    ),
    "Referer": "https://huangguoai.com/",
}
CACHE_FILE = ".hg_cache.json"
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".ts", ".m4v"}

# 官网 crypto-worker.js 里的封面 AES-CBC 密钥（charCode 串）
_COVER_MEDIA_KEY = "102_53_100_57_54_53_100_102_55_53_51_51_54_50_55_48"
_COVER_MEDIA_IV = "57_55_98_54_48_51_57_52_97_98_99_50_102_98_101_49"


def _charcode_key(spec: str) -> bytes:
    return "".join(chr(int(x)) for x in spec.split("_") if x).encode("utf-8")


def is_image_bytes(data: bytes) -> bool:
    if not data or len(data) < 4:
        return False
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"GIF87a")
        or data.startswith(b"GIF89a")
        or (len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    )


def sniff_image_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def decrypt_cover_bytes(data: bytes) -> bytes:
    """解密黄果 CDN 加密封面。已是明文图片则原样返回。

    算法对齐官网 `/static/web/js/plugins/crypto-worker.js`：
    AES-128-CBC / NoPadding / key=f5d965df75336270 / iv=97b60394abc2fbe1
    """
    if not data:
        return data
    if is_image_bytes(data):
        return data
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise RuntimeError("缺少 cryptography，无法本机解密封面") from exc

    key = _charcode_key(_COVER_MEDIA_KEY)
    iv = _charcode_key(_COVER_MEDIA_IV)
    n = len(data) - (len(data) % 16)
    if n < 16:
        raise RuntimeError("加密封面长度异常")
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    pt = dec.update(data[:n]) + dec.finalize()
    if pt.startswith(b"\xff\xd8\xff"):
        end = pt.rfind(b"\xff\xd9")
        if end != -1:
            return pt[: end + 2]
    if pt.startswith(b"\x89PNG"):
        end = pt.rfind(b"IEND")
        if end != -1:
            return pt[: end + 8]
    pt = pt.rstrip(b"\0")
    if not is_image_bytes(pt):
        raise RuntimeError("封面解密后不是有效图片")
    return pt

# 官方导航 /api/videos/category/{slug} + /tag/{slug}/（tag 与现网页面一致）
CATEGORIES: dict[str, str] = {
    "hot": "热门",
    "new": "最新",
    "rank": "排行榜",
    "ai-duanju": "AI短剧",
    "ai-manju": "成人漫剧",
    "ai-huanlian": "AI换脸",
    "ai-mogai": "AI魔改",
    "tag:dushi": "都市",
    "tag:xiandai": "现代",
    "tag:xiaoyuan": "校园",
    "tag:zhichang": "职场",
    "tag:haomen": "豪门",
    "tag:hougong": "后宫",
    "tag:shunv": "熟女",
    "tag:nianxia": "年下",
    "tag:jiedi": "姐弟",
    "tag:muzi": "母子",
    "tag:dananzhu": "大男主",
    "tag:danvzhu": "大女主",
    "tag:nixi": "逆袭",
    "tag:quanmou": "权谋",
    "tag:bazong": "霸总",
    "tag:yulequan": "娱乐圈",
    "tag:mingxing": "明星",
    "tag:tianchong": "甜宠",
    "tag:gufeng": "古风",
    "tag:xianxia": "仙侠",
    "tag:qihuan": "奇幻",
    "tag:xuanhuan": "玄幻",
    "tag:chaonengli": "超能力",
    "tag:xitong": "系统",
    "tag:naodong": "脑洞",
    "tag:youxi": "游戏",
    "tag:huangdao": "荒岛",
    "tag:tongshi": "同事",
    "tag:lvmao": "绿帽",
    "tag:ntr": "NTR",
    "tag:luanlun": "乱伦",
}

_AI_CATEGORY_SLUGS = frozenset({"ai-duanju", "ai-manju", "ai-huanlian", "ai-mogai"})
# 官方 App「擦边短剧」：站点无独立 slug，用换脸+魔改合并近似

_lock = threading.Lock()


def log(msg: str = "", *, level: str = "info") -> None:
    prefix = {"info": "", "warn": "[warn] ", "err": "[err] ", "ok": "[ok] ", "dim": "     "}.get(level, "")
    with _lock:
        sys.stdout.write(prefix + msg + "\n")
        sys.stdout.flush()


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{int(n)}B" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


# --------------------------------------------------------------------------
# 1. 标题清洗与匹配
# --------------------------------------------------------------------------
_B = r"(?<![A-Za-z0-9])"
_E = r"(?![A-Za-z0-9])"
_JUNK_RE = re.compile(
    "|".join([
        rf"{_B}\d{{3,4}}[pP]{_E}",
        rf"{_B}(?:4K|8K|2K|UHD|FHD|HD|SD){_E}",
        rf"{_B}(?:HDR|HDR10\+|DV|Dolby\s?Vision){_E}",
        rf"{_B}(?:WEB[-_.]?DL|WEBRip|BluRay|BDRip|BRRip|REMUX|HDTV){_E}",
        rf"{_B}(?:x264|x265|H\.?26[45]|HEVC|AV1){_E}",
        rf"{_B}(?:AAC|AC3|EAC3|DDP?\s?\d(?:\.\d)?|FLAC|TrueHD|Atmos){_E}",
        r"(?:中文字幕|中英字幕|简体|繁体|简中|繁中|外挂字幕|内嵌字幕|中字)",
        r"(?:高清|超清|蓝光|未删减|完整版|导演剪辑版|加长版)",
        rf"{_B}(?:AI|ai)\s*(?:换脸|魔改|重制)?\s*(?:短剧|漫剧)?{_E}",
        r"\[[^\]]{0,40}\]",
        r"【[^】]{0,40}】",
        r"\([^)]{0,40}\)",
    ]),
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[\s\-–—_.·,，、:：;；!！?？'\"“”‘’()（）\[\]【】<>《》~～+&@#]+")


def clean_title(raw: str) -> str:
    s = _JUNK_RE.sub(" ", raw or "")
    s = re.sub(r"[._]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    # 剥掉独立的年份：某剧2024 -> 某剧（年份不是标题的一部分）
    s = re.sub(r"(?<![0-9])((?:19|20)\d{2})(?![0-9])", " ", s)
    return re.sub(r"\s{2,}", " ", s).strip(" -–—_.")


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "").lower()
    s = _PUNCT_RE.sub("", s)
    return s.replace("剧场版", "").replace("合集", "").replace("完整版", "")


def title_score(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    r = difflib.SequenceMatcher(None, na, nb).ratio()
    if na in nb or nb in na:
        r = max(r, 0.82 + 0.15 * (len(na) / max(len(na), len(nb))))
    return r


# --------------------------------------------------------------------------
# 2. 本地已有集数探测（用于续传与"只补缺集"）
# --------------------------------------------------------------------------
_EP_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"第\s*(\d+)\s*[集话話期回]"), "cn"),
    (re.compile(r"[Ss](\d{1,2})\s*[xX×]\s*[Ee](\d{1,3})"), "sxe"),
    (re.compile(r"[Ss](\d{1,2})\s*[Ee](\d{1,3})\b"), "sxe"),
    (re.compile(r"(?:^|[^A-Za-z])(?:EP|Ep|ep)\.?\s*(\d{1,4})(?!\d)"), "ep"),
    (re.compile(r"(?:^|\s)#\s*(\d{1,4})(?!\d)"), "num"),
    (re.compile(r"[-–—]\s*(\d{1,4})(?:\s|$|\[|\()"), "num"),
    (re.compile(r"(?:^|[\s._\-])(\d{1,4})$"), "num"),
]


def extract_episode(stem: str) -> int | None:
    base, ext = os.path.splitext(stem)
    if ext.lower() in VIDEO_EXT:
        stem = base
    for pat, kind in _EP_PATTERNS:
        m = pat.search(stem)
        if not m:
            continue
        if kind == "sxe":
            return int(m.group(2))
        try:
            n = int(m.group(1))
        except (TypeError, ValueError):
            continue
        if 1900 <= n <= 2100:          # 年份不是集数
            continue
        if 1 <= n <= 9999:
            return n
    return None


def scan_local(root: str | None) -> dict[str, set[int]]:
    """扫描本地，返回 {清洗后的剧名: {已有集数...}}。root 为 None 则返回空。

    残缺/假视频（m3u8 误存等）不计入已有。
    """
    found: dict[str, set[int]] = {}
    if not root or not os.path.isdir(root):
        return found
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if os.path.splitext(fn)[1].lower() not in VIDEO_EXT:
                continue
            full = os.path.join(dirpath, fn)
            if not is_plausible_media(full):
                continue
            stem = os.path.splitext(fn)[0]
            ep = extract_episode(stem)
            title = clean_title(re.sub(r"[-–—]?\s*(?:第\s*\d+\s*集|S\d+E\d+|\d{1,4})\s*$", "", stem, flags=re.I))
            if not title:
                continue
            key = normalize(title)
            if not key:
                continue
            found.setdefault(key, set())
            if ep is not None:
                found[key].add(ep)
            elif not stem.endswith(".part"):
                # 认不出集数的整片文件，视为"有一集但编号未知"
                found[key].add(0)
    return found


def local_has(local_map: dict[str, set[int]], title: str, ep: int) -> bool:
    """该剧该集是否已在本地（0 表示存在整片但集数未知）。"""
    key = normalize(clean_title(title))
    if key not in local_map:
        return False
    eps = local_map[key]
    return ep in eps or 0 in eps


def fmt_eps(eps: list[int]) -> str:
    if not eps:
        return "无"
    eps = sorted(set(eps))
    spans, start, prev = [], eps[0], eps[0]
    for n in eps[1:]:
        if n == prev + 1:
            prev = n
            continue
        spans.append((start, prev))
        start = prev = n
    spans.append((start, prev))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in spans)


# --------------------------------------------------------------------------
# 3. 缓存
# --------------------------------------------------------------------------
class Cache:
    def __init__(self, path: str):
        self.path = path
        self.data: dict[str, Any] = {}
        self._lock = threading.Lock()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    def get(self, key: str, ttl: int) -> Any | None:
        with self._lock:
            hit = self.data.get(key)
        if not hit or time.time() - hit.get("ts", 0) > ttl:
            return None
        return hit.get("val")

    def set(self, key: str, val: Any) -> None:
        with self._lock:
            self.data[key] = {"ts": time.time(), "val": val}

    def save(self) -> None:
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self.data, fh, ensure_ascii=False)
                os.replace(tmp, self.path)
            except OSError as exc:
                log(f"缓存写入失败: {exc}", level="warn")


# --------------------------------------------------------------------------
# 4. 黄果 API
# --------------------------------------------------------------------------
@dataclass
class Show:
    """远端一部剧。"""
    id: str
    title: str
    total: int = 0
    finished: bool = False
    cover: str = ""  # 加密封面地址（可能需要代理解密）
    tags: list[str] = field(default_factory=list)
    hot: int = 0  # 官方热门值

    @property
    def label(self) -> str:
        tag = "全" if self.finished else "更"
        n = f"{self.total}集" if self.total else "集数未知"
        return f"{self.title}  [{n}{tag}]"


def show_from_dict(d: dict) -> Show:
    """从缓存字典还原，忽略未知/缺失字段（老缓存不该让程序崩）。"""
    known = {f for f in Show.__dataclass_fields__}
    return Show(**{k: v for k, v in d.items() if k in known})


def _truthy(v: Any) -> bool:
    """严格真值：把接口可能返回的 "0" / "false" 正确判为假。"""
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return bool(v)


def build_opener(proxy: str = "") -> urllib.request.OpenerDirector:
    """Build urllib opener. proxy like http://127.0.0.1:7890 (empty = direct)."""
    proxy = (proxy or "").strip()
    if not proxy:
        return urllib.request.build_opener()
    if "://" not in proxy:
        proxy = "http://" + proxy
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})]
    return urllib.request.build_opener(*handlers)


class HGApi:
    def __init__(self, base: str = DEFAULT_API, *, timeout: int = 20,
                 cache: Cache | None = None, cache_ttl: int = 1800,
                 referer: str | None = None, retries: int = 2,
                 proxy: str = ""):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.cache = cache
        self.cache_ttl = cache_ttl
        self.retries = retries
        self.proxy = (proxy or "").strip()
        self.opener = build_opener(self.proxy)
        self.headers = dict(DEFAULT_HEADERS)
        if referer:
            self.headers["Referer"] = referer

    def set_proxy(self, proxy: str) -> None:
        self.proxy = (proxy or "").strip()
        self.opener = build_opener(self.proxy)

    def open(self, req: urllib.request.Request, *, timeout: int | None = None):
        return self.opener.open(req, timeout=timeout if timeout is not None else self.timeout)

    # -- 底层 ------------------------------------------------------------
    def _request_bytes(self, url: str) -> bytes:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(url, headers=self.headers, method="GET")
                with self.open(req) as resp:
                    return resp.read()
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(0.6 * (attempt + 1))
        raise RuntimeError(f"请求失败: {url} — {last}")

    def _get(self, url: str) -> Any:
        raw = self._request_bytes(url)
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError as exc:
            raise RuntimeError(f"JSON 解析失败: {url} — {exc}") from exc

    def _get_text(self, url: str) -> str:
        return self._request_bytes(url).decode("utf-8", "replace")

    @staticmethod
    def _items(payload: Any) -> list[dict]:
        node = (payload or {}).get("data")
        node = node if isinstance(node, dict) else {}
        for key in ("items", "list", "videos", "rows", "results"):
            val = node.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        return []

    @staticmethod
    def _to_show(raw: dict) -> Show | None:
        rid = str(raw.get("id") or raw.get("vod_id") or "").strip()
        if not rid:
            return None
        title = str(raw.get("title") or raw.get("vod_name") or raw.get("name") or rid).strip()
        total = raw.get("episode_count") or raw.get("total_episodes") or raw.get("total") or 0
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = 0
        cover = str(raw.get("cover") or raw.get("vod_pic") or raw.get("pic") or "").strip()
        tags: list[str] = []
        raw_tags = raw.get("tags") or raw.get("tag_links") or []
        if isinstance(raw_tags, list):
            for item in raw_tags:
                if isinstance(item, str) and item.strip():
                    tags.append(item.strip())
                elif isinstance(item, dict):
                    name = str(item.get("name") or item.get("title") or item.get("tag") or "").strip()
                    if name:
                        tags.append(name)
        hot = 0
        try:
            hot = int(raw.get("hot") or raw.get("heat") or 0)
        except (TypeError, ValueError):
            hot = 0
        return Show(id=rid, title=title, total=total,
                    finished=_truthy(raw.get("is_finished")), cover=cover, tags=tags,
                    hot=hot)

    def _parse_tag_page(self, html: str) -> list[dict]:
        """从官方 /tag/{slug}/ 主列表 SSR 卡片解析目录项。"""
        # 页面顶部常有推荐卡，只吃主网格，避免和官方 ItemList 顺序不一致
        grid = re.search(
            r'class="hg-card-grid[^"]*"(.*?)(?:class="hg-channel-pager"|class="hg-pager"|</main>|$)',
            html,
            re.I | re.S,
        )
        html = grid.group(1) if grid else html
        items: list[dict] = []
        seen: set[str] = set()
        for m in re.finditer(
            r'class="hg-drama-card__cover-link"\s+href="/video/(\d+)/"(.*?)</div>\s*'
            r'<div class="hg-drama-card__body">(.*?)</div>\s*</div>',
            html,
            re.I | re.S,
        ):
            rid = m.group(1)
            if rid in seen:
                continue
            seen.add(rid)
            head, body = m.group(2), m.group(3)
            cover = ""
            for attr in ("data-src", "src"):
                cm = re.search(rf'{attr}="(https?://[^"]+)"', head)
                if cm:
                    cover = cm.group(1)
                    break
            tm = re.search(r'alt="([^"]*)"', head)
            title = (tm.group(1) if tm else "").strip()
            if not title:
                tm = re.search(
                    r'class="hg-drama-card__title"[^>]*>\s*<a[^>]*>\s*([^<]+)',
                    body,
                )
                title = (tm.group(1).strip() if tm else rid)
            ep_m = re.search(r'data-ep-base="([^"]+)"', head)
            ep_base = ep_m.group(1) if ep_m else ""
            total = 0
            finished = "全" in ep_base and "更新" not in ep_base
            num = re.search(r"(\d+)", ep_base)
            if num:
                total = int(num.group(1))
            tags = [
                t.strip()
                for t in re.findall(r'class="hg-tag"[^>]*>\s*([^<]+)', body)
                if t.strip()
            ]
            items.append({
                "id": rid,
                "title": title or rid,
                "cover": cover,
                "episode_count": total,
                "is_finished": finished,
                "tags": tags,
            })
        return items

    def _catalog_tag(self, slug: str, page: int, sort: str = "new") -> list[dict]:
        slug = (slug or "").strip().strip("/")
        if not slug:
            return []
        sort = "hot" if sort == "hot" else "new"
        # 热度：走 JSON API（HTML 题材页顺序不稳且难切 sort）
        if sort == "hot":
            return self._items(self._get(
                f"{self.base}/api/videos?" + urllib.parse.urlencode(
                    {"page": page, "page_size": 24, "sort": "hot", "tag": slug})))
        path = f"/tag/{urllib.parse.quote(slug)}/" if page <= 1 else (
            f"/tag/{urllib.parse.quote(slug)}/page/{page}/"
        )
        try:
            html = self._get_text(self.base + path)
            items = self._parse_tag_page(html)
            if items:
                return items
        except RuntimeError as exc:
            log(f"标签页不可用 {path}: {exc}", level="warn")
        # 旧接口兜底（多数环境会忽略 tag 参数）
        return self._items(self._get(
            f"{self.base}/api/videos?" + urllib.parse.urlencode(
                {"page": page, "page_size": 24, "sort": "new", "tag": slug})))

    # -- 目录 ------------------------------------------------------------
    def catalog(
        self,
        category: str = "hot",
        page: int = 1,
        page_size: int = 24,
        sort: str | None = None,
    ) -> list[Show]:
        """拉远端目录。category 支持 hot/new/rank/ai-*/tag:xxx；sort=hot|new。"""
        page = max(1, int(page or 1))
        page_size = max(1, int(page_size or 24))
        sort_n = (sort or "").strip().lower()
        if sort_n not in ("hot", "new"):
            if category == "new":
                sort_n = "new"
            elif category in ("hot", "rank", "ranks", ""):
                sort_n = "hot"
            else:
                # 频道 / 题材：历史默认最新
                sort_n = "new"
        if category in ("hot", "new"):
            sort_n = category
        key = f"cat:{category}:{sort_n}:{page}:{page_size}"
        if self.cache:
            hit = self.cache.get(key, self.cache_ttl)
            if hit is not None:
                return [show_from_dict(s) for s in hit]

        items: list[dict] = []
        if category in ("rank", "ranks"):
            try:
                items = self._items(self._get(f"{self.base}/api/ranks/hot?" +
                                               urllib.parse.urlencode({"page": page})))
            except RuntimeError as exc:
                log(f"排行榜接口不可用: {exc}", level="warn")
        elif category in _AI_CATEGORY_SLUGS:
            # 官方频道页：/api/videos/category/ai-manju?sort=&page=&size=
            items = self._items(self._get(
                f"{self.base}/api/videos/category/{category}?" + urllib.parse.urlencode(
                    {"page": page, "size": page_size, "sort": sort_n})))
        elif category.startswith("tag:"):
            items = self._catalog_tag(category[4:], page, sort=sort_n)
        else:
            # 通用列表：hot=累计热门值降序；new=最新
            items = self._items(self._get(
                f"{self.base}/api/videos?" + urllib.parse.urlencode(
                    {"page": page, "page_size": page_size, "sort": sort_n})))

        shows = [s for s in (self._to_show(r) for r in items) if s]
        if self.cache:
            self.cache.set(key, [asdict(s) for s in shows])
        return shows

    def search(self, keyword: str, page: int = 1) -> list[Show]:
        page = max(1, int(page or 1))
        key = f"search:{normalize(keyword)}:{page}"
        if self.cache:
            hit = self.cache.get(key, self.cache_ttl)
            if hit is not None:
                return [show_from_dict(s) for s in hit]
        items = self._items(self._get(
            f"{self.base}/api/search?" + urllib.parse.urlencode({"q": keyword, "page": page})))
        shows = [s for s in (self._to_show(r) for r in items) if s]
        if self.cache:
            self.cache.set(key, [asdict(s) for s in shows])
        return shows

    def match(self, title: str, threshold: float = 0.62) -> tuple[Show | None, float, list[Show]]:
        """先搜再用 difflib 兜底，返回 (最佳候选, 分数, 候选列表)。

        搜索无结果时也会去热门目录抓一批候选回来，好让用户看到"到底有哪些剧可选"，
        而不是干瞪眼。
        """
        cands: list[Show] = []
        try:
            cands = self.search(title)
        except RuntimeError as exc:
            log(f"搜索接口失败，尝试目录兜底: {exc}", level="warn")

        if not cands:
            for cat in ("hot", "new"):
                try:
                    cands = self.catalog(cat, 1)
                except RuntimeError:
                    continue
                if cands:
                    break
        if not cands:
            return None, 0.0, []

        scored = sorted(((title_score(title, c.title), c) for c in cands),
                        key=lambda x: x[0], reverse=True)
        best_score, best = scored[0]
        top = [c for _, c in scored[:5]]
        return (best, best_score, top) if best_score >= threshold else (None, best_score, top)

    # -- 详情 ------------------------------------------------------------
    def detail(self, show: Show) -> dict:
        key = f"detail:{show.id}"
        if self.cache:
            hit = self.cache.get(key, self.cache_ttl)
            if hit is not None:
                return hit
        data = (self._get(f"{self.base}/api/videos/{urllib.parse.quote(show.id)}")
                or {}).get("data") or {}
        if self.cache:
            self.cache.set(key, data)
        return data

    def episodes(self, show: Show) -> list[dict]:
        """统一成 [{'n': 1, 'title': '第1集', 'url': ''}, ...]，按集号排序。

        详情接口拿不到时不抛异常——降级用列表里的 total 造占位，
        让"下载"这种主流程不至于因为一个附加接口挂了就崩。
        """
        raw: list = []
        try:
            detail = self.detail(show)
            if isinstance(detail.get("episodes"), list):
                raw = detail["episodes"]
        except RuntimeError as exc:
            log(f"详情接口不可用，用列表里的 {show.total} 集兜底: {exc}", level="warn")

        out: list[dict] = []
        for i, ep in enumerate(raw):
            if not isinstance(ep, dict):
                continue
            n = ep.get("ep_num") or ep.get("episode") or ep.get("index") or (i + 1)
            try:
                n = int(n)
            except (TypeError, ValueError):
                n = i + 1
            out.append({
                "n": n,
                "title": str(ep.get("title") or ep.get("name") or f"第{n}集"),
                "url": str(ep.get("video_url") or ep.get("url") or "").strip(),
            })
        out.sort(key=lambda x: x["n"])

        # 详情没给集数时兜底：用 total 造出占位，播放时现调 /play
        if not out and show.total:
            out = [{"n": n, "title": f"第{n}集", "url": ""} for n in range(1, show.total + 1)]
        return out

    def play_url(self, show: Show, ep: int, preset: str = "") -> str:
        if preset:
            return preset
        data = self._get(f"{self.base}/api/videos/{urllib.parse.quote(show.id)}/play?" +
                         urllib.parse.urlencode({"ep": ep})) or {}
        node = data.get("data")
        node = node if isinstance(node, dict) else data
        return str(node.get("video_url") or node.get("url") or "").strip()

    def cover_url(self, show: Show) -> str:
        """封面最终地址。优先详情里的 cover（更准），否则用列表里的。

        接口返回的封面可能是加密地址，需要过解密代理才能显示，
        所以把原始地址交给调用方，由 build_cover_url 拼代理和 token。
        """
        try:
            detail = self.detail(show)
            cand = detail.get("cover") or detail.get("vod_pic") or detail.get("pic")
            if cand:
                return str(cand).strip()
        except RuntimeError:
            pass
        return show.cover

    # -- 封面 ------------------------------------------------------------
    def fetch_cover(self, url: str, dest: str, *, timeout: int = 30) -> tuple[bool, str]:
        """下载封面到 dest。返回 (是否成功, 说明)。

        注意：图片请求不能复用 JSON 接口的 headers（Accept 里没有 image/*），
        某些代理会因此返回错误内容。单独构造一套。
        """
        if not url:
            return False, "无封面地址"
        try:
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        except OSError as exc:
            return False, f"建目录失败: {exc}"

        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return True, "已存在"

        part = dest + ".part"
        img_headers = {
            "User-Agent": DEFAULT_HEADERS["User-Agent"],
            "Referer": self.headers.get("Referer") or f"{self.base}/",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        try:
            req = urllib.request.Request(url, headers=img_headers, method="GET")
            with self.open(req, timeout=timeout) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                data = resp.read()
        except urllib.error.HTTPError as exc:
            # 非 2xx 时也要读响应体：代理通常在错误里说明原因（token 失效等）
            detail = ""
            try:
                detail = exc.read()[:160].decode("utf-8", "replace").strip()
            except Exception:                      # noqa: BLE001
                pass
            return False, f"HTTP {exc.code}{(' · ' + detail) if detail else ''}"
        except (urllib.error.URLError, OSError) as exc:
            return False, f"封面请求失败: {exc}"

        if not data:
            return False, "封面响应为空"
        # 代理若返回 JSON 而不是图片，多半是鉴权或参数错误，直接报出来而不是存成坏图
        head = data[:200].lstrip()
        if head[:1] in (b"{", b"[") or ctype.startswith("text/html"):
            snippet = data[:120].decode("utf-8", "replace")
            return False, f"代理未返回图片({ctype or 'unknown'}): {snippet}"

        # CDN 常见为 AES 密文（Content-Type 常是 binary/octet-stream）
        if not is_image_bytes(data):
            try:
                data = decrypt_cover_bytes(data)
                ctype = sniff_image_mime(data)
            except Exception as exc:  # noqa: BLE001
                return False, f"封面解密失败: {exc}"

        try:
            with open(part, "wb") as fh:
                fh.write(data)
            os.replace(part, dest)
        except OSError as exc:
            return False, f"写文件失败: {exc}"
        return True, f"{human_size(len(data))} {ctype.split(';')[0] or sniff_image_mime(data)}"


# --------------------------------------------------------------------------
# 5. 下载计划
# --------------------------------------------------------------------------
@dataclass
class Job:
    show: Show
    ep: int
    ep_title: str = ""
    preset_url: str = ""
    status: str = "pending"     # pending / exist / skip / ok / fail
    note: str = ""
    path: str = ""


def build_jobs(show: Show, eps: list[dict], *, ep_filter: set[int] | None,
               local_map: dict[str, set[int]],
               out_dir: str) -> tuple[list[Job], list[int]]:
    """返回 (任务列表, 因已存在而跳过的集数)。

    去重永远生效（此前有个从不生效的 missing_only 开关，已删除），三个来源：
      1. --scan-dir 扫到的本地已有集
      2. 输出目录里已经落地的目标文件（.part 视为未完成，可续传）
      3. --ep 过滤掉的集
    计划表必须反映真实待办，否则"待下载 1-3"却在磁盘上已存在这种谎报会让人重复下载。
    """
    jobs: list[Job] = []
    have: list[int] = []
    for e in eps:
        n = e["n"]
        if ep_filter and n not in ep_filter:
            continue
        if local_has(local_map, show.title, n):
            have.append(n)
            continue
        ext = os.path.splitext(e.get("url", "") or "")[1] or ".mp4"
        path = target_path(show, n, ext, out_dir)
        legacy = legacy_target_path(show, n, ext, out_dir)
        flat = flat_legacy_path(show, n, ext, out_dir)
        # 旧路径上的假文件清掉；完整的旧文件算已有（不强制搬家）
        purge_bad_media(path, legacy, flat)
        if already_done(path) or already_done(legacy) or already_done(flat):
            have.append(n)
            continue
        jobs.append(Job(show=show, ep=n, ep_title=e["title"], preset_url=e["url"], path=path))
    return jobs, have


def already_done(path: str) -> bool:
    """目标文件已完整落盘（存在 .part 说明未完成，仍算待办）。

    误把 m3u8 存成 .mp4 的短文件视为未完成，允许重下。
    """
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        return False
    if os.path.exists(path + ".part"):
        return False
    return is_plausible_media(path)


def is_hls_playlist_bytes(data: bytes) -> bool:
    head = (data or b"").lstrip()[:16]
    return head.startswith(b"#EXTM3U")


def is_hls_url(url: str) -> bool:
    u = (url or "").lower()
    path = urllib.parse.urlparse(u).path
    return ".m3u8" in path or u.rstrip("/").endswith("m3u8") or "m3u8" in u


def is_plausible_media(path: str) -> bool:
    """粗检：排除 m3u8/HTML/JSON 假文件与过小残缺。

    - 播放列表、网页、JSON → 不算完成
    - MP4(ftyp) / MPEG-TS(0x47) → 通过
    - 其它封装：体积 ≥ 256KB 且非纯文本头 → 通过
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            head = fh.read(64)
    except OSError:
        return False
    if size < 1024 or not head:
        return False
    if is_hls_playlist_bytes(head):
        return False
    first = head.lstrip()[:1]
    if first in (b"<", b"{", b"["):
        return False
    if len(head) >= 8 and head[4:8] == b"ftyp":
        return True
    if head[0:1] == b"\x47":
        return True
    if size < 256 * 1024:
        return False
    # 大文件但开头像文本（误存的长 playlist）→ 拒绝；其余（含 RIFF 等）通过
    try:
        text = head.decode("ascii")
    except UnicodeDecodeError:
        return True
    if "#EXT" in text or text.startswith("http"):
        return False
    return True


def resolve_ffmpeg() -> str:
    """优先用 pip 依赖 imageio-ffmpeg（随容器/虚拟环境走，适合 NAS）。

    可选覆盖：环境变量 HG_FFMPEG / FFMPEG（调试用，部署勿依赖本机安装）。
    """
    for env_key in ("HG_FFMPEG", "FFMPEG"):
        v = (os.environ.get(env_key) or "").strip()
        if v and os.path.isfile(v):
            return v
    try:
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception as exc:  # noqa: BLE001
        raise FileNotFoundError(
            "未找到 ffmpeg。请安装依赖：pip install imageio-ffmpeg "
            f"（已写入 backend/requirements.txt）详情: {exc}"
        ) from exc
    raise FileNotFoundError(
        "imageio-ffmpeg 已安装但未提供可执行文件。请重装：pip install -U imageio-ffmpeg"
    )


def _ffmpeg_creationflags() -> int:
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def _ffmpeg_env(*, proxy: str = "") -> dict[str, str]:
    """ffmpeg 环境：默认直连 CDN（清掉进程里的 HTTP_PROXY）。

    设置里的 http_proxy 只给上游 API/封面用；片源经代理常触发
   「Protocol httpproxy not on whitelist」。需要时再显式传入 proxy。
    """
    env = {k: v for k, v in os.environ.items() if isinstance(v, str)}
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        env.pop(key, None)
    proxy = (proxy or "").strip()
    if proxy:
        if "://" not in proxy:
            proxy = "http://" + proxy
        env["HTTP_PROXY"] = proxy
        env["HTTPS_PROXY"] = proxy
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
    return env


def download_hls_ffmpeg(
    url: str,
    dest: str,
    headers: dict[str, str],
    *,
    timeout: int = 1800,
    proxy: str = "",
) -> int:
    """用 ffmpeg 拉 HLS（含 AES-128），输出 MP4。返回字节数。

    默认直连；proxy 非空时才让 ffmpeg 走代理。
    """
    ff = resolve_ffmpeg()
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".fftmp.mp4"
    for stale in (tmp, dest + ".part"):
        try:
            if os.path.exists(stale):
                os.remove(stale)
        except OSError:
            pass

    ua = headers.get("User-Agent") or DEFAULT_HEADERS["User-Agent"]
    referer = headers.get("Referer") or DEFAULT_HEADERS.get("Referer") or ""
    hdr = ""
    if referer:
        hdr += f"Referer: {referer}\r\n"
    accept = headers.get("Accept")
    if accept:
        hdr += f"Accept: {accept}\r\n"

    # httpproxy：仅在显式走代理时用到
    whitelist = "file,http,https,tcp,tls,crypto,data,httpproxy"
    cmd = [
        ff,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-user_agent",
        ua,
    ]
    if hdr:
        cmd += ["-headers", hdr]
    cmd += [
        "-protocol_whitelist",
        whitelist,
        "-i",
        url,
        "-c",
        "copy",
        "-bsf:a",
        "aac_adtstoasc",
        "-movflags",
        "+faststart",
        tmp,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=max(120, int(timeout)),
            creationflags=_ffmpeg_creationflags(),
            env=_ffmpeg_env(proxy=proxy),
        )
    except subprocess.TimeoutExpired as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError(f"ffmpeg 超时({timeout}s)") from exc

    err = (proc.stderr or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not os.path.isfile(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError(err or f"ffmpeg 失败 code={proc.returncode}")

    if not is_plausible_media(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError("ffmpeg 输出不是有效视频")

    os.replace(tmp, dest)
    return os.path.getsize(dest)


def _peek_url(
    url: str,
    headers: dict[str, str],
    *,
    timeout: int,
    opener: urllib.request.OpenerDirector | None,
    nbytes: int = 4096,
) -> tuple[bytes, Any]:
    """打开 URL，读最多 nbytes，返回 (peek, response)。调用方负责关闭 resp。"""
    req = urllib.request.Request(url, headers=dict(headers), method="GET")
    open_fn = opener.open if opener is not None else urllib.request.urlopen
    resp = open_fn(req, timeout=timeout)
    peek = resp.read(nbytes)
    return peek, resp


def _safe_name(name: str) -> str:
    s = (name or "").strip() or "untitled"
    for ch in '\\/:*?"<>|':
        s = s.replace(ch, "_")
    return s


def _xml_text(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def show_dir(show: Show, out_dir: str) -> str:
    """一部剧一个子目录（Emby 剧集根）。"""
    return os.path.join(out_dir, _safe_name(show.title))


def season_dir(show: Show, out_dir: str) -> str:
    """Emby Season 文件夹。"""
    return os.path.join(show_dir(show, out_dir), EMBY_SEASON_DIR)


def cover_path(show: Show, out_dir: str) -> str:
    """剧集海报：poster.jpg（Emby Primary）。"""
    return os.path.join(show_dir(show, out_dir), "poster.jpg")


def season_poster_path(show: Show, out_dir: str) -> str:
    return os.path.join(season_dir(show, out_dir), "poster.jpg")


def tvshow_nfo_path(show: Show, out_dir: str) -> str:
    return os.path.join(show_dir(show, out_dir), "tvshow.nfo")


def season_nfo_path(show: Show, out_dir: str) -> str:
    return os.path.join(season_dir(show, out_dir), "season.nfo")


def episode_nfo_path(video_path: str) -> str:
    base, _ = os.path.splitext(video_path)
    return base + ".nfo"


def legacy_target_path(show: Show, ep: int, ext: str, out_dir: str) -> str:
    """旧版：downloads/<剧名>/第N集.mp4"""
    use = _normalize_ext(ext)
    return os.path.join(show_dir(show, out_dir), f"第{ep}集{use}")


def flat_legacy_path(show: Show, ep: int, ext: str, out_dir: str) -> str:
    """更旧：downloads/<剧名> - 第N集.mp4（无子目录）。"""
    use = _normalize_ext(ext)
    return os.path.join(out_dir, f"{_safe_name(show.title)} - 第{ep}集{use}")


def flat_legacy_cover_path(show: Show, out_dir: str) -> str:
    return os.path.join(out_dir, f"{_safe_name(show.title)} - 封面.jpg")


def purge_bad_media(*paths: str) -> None:
    """删掉残缺/假视频，避免旧路径误导。"""
    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        if is_plausible_media(path):
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def _normalize_ext(ext: str) -> str:
    if ext and len(ext) <= 5 and re.fullmatch(r"\.[A-Za-z0-9]{2,4}", ext):
        return ext.lower()
    return ".mp4"


def episode_filename(show: Show, ep: int, ext: str) -> str:
    """Show Name - S01E01.ext"""
    use = _normalize_ext(ext)
    return f"{_safe_name(show.title)} - S{EMBY_SEASON:02d}E{ep:02d}{use}"


def write_tvshow_nfo(
    show: Show,
    out_dir: str,
    *,
    plot: str = "",
    genres: list[str] | None = None,
) -> str:
    """写入剧集根 tvshow.nfo。"""
    path = tvshow_nfo_path(show, out_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tags = genres if genres is not None else list(show.tags or [])
    genre_xml = "".join(f"  <genre>{_xml_text(g)}</genre>\n" for g in tags if g)
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        "<tvshow>\n"
        f"  <title>{_xml_text(show.title)}</title>\n"
        f"  <plot>{_xml_text(plot)}</plot>\n"
        f"{genre_xml}"
        f"  <episode>{int(show.total or 0)}</episode>\n"
        f"  <season>{EMBY_SEASON}</season>\n"
        "  <status>"
        f"{'Ended' if show.finished else 'Continuing'}"
        "</status>\n"
        f"  <uniqueid type=\"huangguo\" default=\"true\">{_xml_text(show.id)}</uniqueid>\n"
        "</tvshow>\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


def write_season_nfo(show: Show, out_dir: str) -> str:
    path = season_nfo_path(show, out_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        "<season>\n"
        f"  <seasonnumber>{EMBY_SEASON}</seasonnumber>\n"
        f"  <title>Season {EMBY_SEASON}</title>\n"
        f"  <plot>{_xml_text(show.title)} · 第{EMBY_SEASON}季</plot>\n"
        "</season>\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


def write_episode_nfo(
    show: Show,
    ep: int,
    ep_title: str,
    video_path: str,
) -> str:
    path = episode_nfo_path(video_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    title = (ep_title or "").strip() or f"第{ep}集"
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        "<episodedetails>\n"
        f"  <title>{_xml_text(title)}</title>\n"
        f"  <showtitle>{_xml_text(show.title)}</showtitle>\n"
        f"  <season>{EMBY_SEASON}</season>\n"
        f"  <episode>{int(ep)}</episode>\n"
        f"  <plot>{_xml_text(title)}</plot>\n"
        f"  <uniqueid type=\"huangguo\" default=\"true\">{_xml_text(show.id)}-{int(ep)}</uniqueid>\n"
        "</episodedetails>\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


def ensure_emby_metadata(
    show: Show,
    out_dir: str,
    *,
    plot: str = "",
    genres: list[str] | None = None,
) -> None:
    """保证剧集/季目录与 nfo、海报副本就绪（适合 Emby TV 库）。"""
    os.makedirs(season_dir(show, out_dir), exist_ok=True)
    # 旧封面文件名迁移
    root = show_dir(show, out_dir)
    old_cover = os.path.join(root, "封面.jpg")
    poster = cover_path(show, out_dir)
    if os.path.isfile(old_cover) and not os.path.isfile(poster):
        try:
            os.replace(old_cover, poster)
        except OSError:
            pass
    write_tvshow_nfo(show, out_dir, plot=plot, genres=genres)
    write_season_nfo(show, out_dir)
    if os.path.isfile(poster):
        try:
            shutil.copy2(poster, season_poster_path(show, out_dir))
        except OSError:
            pass


def build_cover_url(raw: str, api_base: str, proxy: str, token: str) -> str:
    """把接口给的封面地址变成可下载的地址。

    - 协议相对//xxx  -> https://xxx
    - 相对路径      -> 拼到 api_base
    - 其余情况      -> 原样返回（已经是绝对地址）
    走代理时把 url + token 一起带上，逻辑与 ForwardWidget 脚本一致。
    """
    url = (raw or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    elif not url.lower().startswith(("http://", "https://")):
        url = api_base.rstrip("/") + ("" if url.startswith("/") else "/") + url

    proxy = (proxy or "").strip().rstrip("/")
    if not proxy:
        return url
    sep = "&" if "?" in proxy else "?"
    url = f"{proxy}{sep}url={urllib.parse.quote(url, safe='')}"
    if token:
        url += f"&token={urllib.parse.quote(token, safe='')}"
    return url


def save_cover(show: Show, api: HGApi, out_dir: str, cover_proxy: str = "",
               cover_token: str = "", *, timeout: int = 30,
               plot: str = "") -> tuple[bool, str]:
    """下载并落盘 poster.jpg，并写好 Emby nfo / 季海报。"""
    ensure_emby_metadata(show, out_dir, plot=plot)
    dest = cover_path(show, out_dir)
    raw = api.cover_url(show)
    # cover_proxy 仅作兜底：本机解密失败时才走远程解密站
    url = build_cover_url(raw, api.base, "", "")
    ok, note = api.fetch_cover(url, dest, timeout=timeout)
    if not ok and cover_proxy:
        alt = build_cover_url(raw, api.base, cover_proxy, cover_token)
        if alt and alt != url:
            ok, note = api.fetch_cover(alt, dest, timeout=timeout)
    if ok:
        try:
            shutil.copy2(dest, season_poster_path(show, out_dir))
        except OSError:
            pass
        ensure_emby_metadata(show, out_dir, plot=plot)
    return ok, note


def target_path(show: Show, ep: int, ext: str, out_dir: str) -> str:
    """Emby：downloads/<剧名>/Season 01/<剧名> - S01E01.mp4"""
    return os.path.join(
        season_dir(show, out_dir),
        episode_filename(show, ep, ext),
    )


# --------------------------------------------------------------------------
# 6. 下载
# --------------------------------------------------------------------------
def download(job: Job, api: HGApi, out_dir: str, *, timeout: int = 60,
             retries: int = 3) -> Job:
    final = job.path or target_path(job.show, job.ep, "", out_dir)
    part = final + ".part"
    ext = os.path.splitext(final)[1] or ".mp4"
    # 误存的 m3u8/假视频（含旧扁平路径）清掉重下
    purge_bad_media(
        final,
        legacy_target_path(job.show, job.ep, ext, out_dir),
        flat_legacy_path(job.show, job.ep, ext, out_dir),
    )
    if already_done(final) and not os.path.exists(part):
        job.status, job.note = "exist", "已存在"
        try:
            write_episode_nfo(job.show, job.ep, job.ep_title, final)
        except OSError:
            pass
        return job

    try:
        os.makedirs(os.path.dirname(final) or out_dir, exist_ok=True)
        ensure_emby_metadata(job.show, out_dir)
    except OSError as exc:
        job.status, job.note = "fail", f"建目录失败: {exc}"
        return job

    try:
        url = api.play_url(job.show, job.ep, job.preset_url)
    except RuntimeError as exc:
        job.status, job.note = "fail", str(exc)
        return job
    if not url:
        job.status, job.note = "fail", "接口未返回播放地址"
        return job

    media_headers = {
        "User-Agent": api.headers.get("User-Agent") or DEFAULT_HEADERS["User-Agent"],
        "Referer": api.headers.get("Referer") or DEFAULT_HEADERS["Referer"],
        "Accept": "*/*",
    }

    for attempt in range(1, retries + 1):
        try:
            use_hls = is_hls_url(url)
            if not use_hls:
                # 探头：CDN 常把 play 指到 m3u8 却不带扩展名
                peek, resp = _peek_url(
                    url, media_headers, timeout=timeout, opener=api.opener,
                )
                try:
                    if is_hls_playlist_bytes(peek):
                        use_hls = True
                        resp.close()
                    else:
                        total = _stream_to(
                            url,
                            part,
                            media_headers,
                            timeout=timeout,
                            opener=api.opener,
                            resp=resp,
                            prefix=peek,
                        )
                        os.replace(part, final)
                        if not is_plausible_media(final):
                            os.remove(final)
                            raise RuntimeError("下载结果不是有效视频（疑似播放列表）")
                        job.status, job.note, job.path = "ok", human_size(total), final
                        try:
                            write_episode_nfo(job.show, job.ep, job.ep_title, final)
                        except OSError as exc:
                            job.note = f"{job.note} · nfo失败:{exc}"
                        return job
                except Exception:
                    try:
                        resp.close()
                    except Exception:  # noqa: BLE001
                        pass
                    raise

            if use_hls:
                log(f"  HLS → ffmpeg 第{job.ep}集", level="dim")
                total = download_hls_ffmpeg(
                    url,
                    final,
                    media_headers,
                    timeout=max(900, int(timeout) * 30),
                )
                job.status, job.note, job.path = (
                    "ok",
                    f"{human_size(total)} · ffmpeg",
                    final,
                )
                try:
                    write_episode_nfo(job.show, job.ep, job.ep_title, final)
                except OSError as exc:
                    job.note = f"{job.note} · nfo失败:{exc}"
                return job

        except Exception as exc:                       # noqa: BLE001
            if attempt >= retries:
                job.status = "fail"
                job.note = f"下载失败({attempt}/{retries}): {exc}"
                return job
            log(f"  重试 {attempt}/{retries}: 第{job.ep}集 — {exc}", level="warn")
            time.sleep(min(2 ** attempt, 8))

    job.status, job.note = "fail", "未知错误"
    return job


def _stream_to(
    url: str,
    part: str,
    headers: dict[str, str],
    *,
    timeout: int,
    chunk: int = 256 * 1024,
    opener: urllib.request.OpenerDirector | None = None,
    resp: Any = None,
    prefix: bytes = b"",
) -> int:
    """Range 断点续传写入 .part，返回总字节数。

    若传入已打开的 resp + prefix（探头字节），则接着写完并关闭 resp。
    """
    own_resp = resp is None
    have = 0 if prefix or resp is not None else (
        os.path.getsize(part) if os.path.exists(part) else 0
    )
    if resp is None:
        hdrs = dict(headers)
        if have:
            hdrs["Range"] = f"bytes={have}-"
        req = urllib.request.Request(url, headers=hdrs, method="GET")
        open_fn = opener.open if opener is not None else urllib.request.urlopen
        resp = open_fn(req, timeout=timeout)

    try:
        status = getattr(resp, "status", 200) or 200
        clen = int(resp.headers.get("Content-Length") or 0)
        if have and status != 206 and not prefix:
            have = 0
        mode = "ab" if have and not prefix else "wb"
        # prefix 是同一个 resp 上探读出来的字节，Content-Length 已经把它算在内，
        # 不能再加一次 len(prefix)，否则进度百分比会偏小。
        total = clen if (prefix and not have) else have + clen

        written = have
        t0 = next_tick = time.time()
        with open(part, mode) as fh:
            if prefix:
                fh.write(prefix)
                written += len(prefix)
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                fh.write(buf)
                written += len(buf)
                now = time.time()
                if now - next_tick >= 0.4:
                    pct = f"{written / total * 100:5.1f}%" if total else "  ?.?%"
                    speed = written / max(now - t0, 0.01)
                    log(f"    第{os.path.basename(part).split('-')[-1]:<12} "
                        f"{pct}  {human_size(written)}  {human_size(speed)}/s", level="dim")
                    next_tick = now
        return written
    finally:
        if own_resp or resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------
# 7. 渲染目录
# --------------------------------------------------------------------------
def print_shows(shows: list[Show], *, start: int = 0, show_index: bool = True) -> None:
    if not shows:
        log("（空）", level="warn")
        return
    for i, s in enumerate(shows, start=start + 1):
        idx = f"[{i:>3}] " if show_index else "      "
        log(f"{idx}{s.label}")


def print_episodes(eps: list[dict], *, local_map: dict[str, set[int]] | None = None,
                   title: str = "") -> None:
    if not eps:
        log("远端没有集数信息", level="warn")
        return
    for e in eps:
        flag = ""
        if local_map is not None:
            flag = "  [本地已有]" if local_has(local_map, title, e["n"]) else ""
        log(f"  第{e['n']:>3}集  {e['title']}{flag}")

def parse_ep_filter(spec: str) -> set[int] | None:
    if not (spec or '').strip():
        return None
    out: set[int] = set()
    for chunk in spec.split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        if '-' in chunk:
            a, _, b = chunk.partition('-')
            try:
                out.update(range(int(a), int(b) + 1))
            except ValueError:
                log(f'忽略无法解析的区间: {chunk}', level='warn')
        else:
            try:
                out.add(int(chunk))
            except ValueError:
                log(f'忽略无法解析的集数: {chunk}', level='warn')
    return out or None


def download_cover(show: Show, api: HGApi, out_dir: str, args) -> tuple[bool, str]:
    plot = ""
    try:
        detail = api.detail(show) if hasattr(api, "detail") else None
        if isinstance(detail, dict):
            plot = str(
                detail.get("description")
                or detail.get("plot")
                or detail.get("vod_content")
                or ""
            ).strip()
            tags = detail.get("tags")
            if isinstance(tags, list) and tags and not show.tags:
                show.tags = [str(t) for t in tags if t]
    except Exception:  # noqa: BLE001
        pass
    return save_cover(
        show,
        api,
        out_dir,
        cover_proxy=getattr(args, "cover_proxy", ""),
        cover_token=getattr(args, "cover_token", ""),
        timeout=max(30, int(getattr(args, "timeout", 30) or 30)),
        plot=plot,
    )


def resolve_show(api: HGApi, title: str, threshold: float) -> Show | None:
    show, score, cands = api.match(title, threshold)
    if show:
        log(f'✓ 匹配「{title}」→「{show.title}」 id={show.id} 相似度={score:.2f}', level='ok')
        return show
    if cands:
        log(f'✗ 没匹配上「{title}」，最接近的是：', level='warn')
        print_shows(cands, show_index=False)
    else:
        log(f'✗ 没匹配上「{title}」，且搜索无结果', level='warn')
    return None
