"""HLS reverse proxy: fetch upstream playlists/segments with Referer, rewrite m3u8."""

from __future__ import annotations

import re
from typing import Callable
from urllib.parse import urlencode, urljoin, urlparse

from hg_core import DEFAULT_HEADERS, is_hls_playlist_bytes

# Cap single proxied body (playlist or segment)
MAX_BODY = 48 * 1024 * 1024

_URI_ATTR = re.compile(
    r'(URI\s*=\s*)(["\'])([^"\']+)\2',
    re.IGNORECASE,
)


def referer_for(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return DEFAULT_HEADERS.get("Referer") or "https://huangguoai.com/"
    origin = f"{parsed.scheme}://{parsed.netloc}"
    host = (parsed.netloc or "").lower()
    # 黄豆 Forward 客户端用 /home；黄果 / 野果用站根
    if "huangguo" in host or "yeguo" in host or "yeguodj" in host or "buxefaex" in host:
        return origin + "/"
    return origin + "/home"


def proxy_path(
    upstream: str,
    *,
    access_token: str = "",
    referer: str = "",
) -> str:
    qs: dict[str, str] = {"url": upstream}
    tok = (access_token or "").strip()
    if tok:
        qs["access_token"] = tok
    ref = (referer or "").strip()
    if ref:
        qs["ref"] = ref
    return "/api/hls?" + urlencode(qs)


def _is_uri_line(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith("#"):
        return False
    return True


def rewrite_m3u8(
    text: str,
    base_url: str,
    make_proxy: Callable[[str], str],
) -> str:
    """Rewrite media / key / playlist URIs to go through make_proxy(absolute_url)."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("#"):
            def _sub(m: re.Match[str]) -> str:
                abs_u = urljoin(base_url, m.group(3).strip())
                return f"{m.group(1)}{m.group(2)}{make_proxy(abs_u)}{m.group(2)}"

            out.append(_URI_ATTR.sub(_sub, line))
            continue
        if _is_uri_line(line):
            abs_u = urljoin(base_url, line.strip())
            out.append(make_proxy(abs_u))
            continue
        out.append(line)
    # HLS playlists expect a trailing newline
    return "\n".join(out) + "\n"


def sniff_media_type(url: str, data: bytes, content_type: str = "") -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if is_hls_playlist_bytes(data) or ".m3u8" in (url or "").lower():
        return "application/vnd.apple.mpegurl"
    if ct and ct not in ("application/octet-stream", "binary/octet-stream", "text/plain"):
        return ct
    path = urlparse(url).path.lower()
    if path.endswith(".ts") or path.endswith(".m4s") or path.endswith(".mp4"):
        return "video/mp2t" if path.endswith(".ts") else "video/mp4"
    if path.endswith(".key"):
        return "application/octet-stream"
    if data[:1] == b"\x47":
        return "video/mp2t"
    return ct or "application/octet-stream"


def fetch_headers(url: str) -> dict[str, str]:
    return {
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
        "Accept": "*/*",
        "Referer": referer_for(url),
        "Origin": f"{urlparse(url).scheme}://{urlparse(url).netloc}",
    }
