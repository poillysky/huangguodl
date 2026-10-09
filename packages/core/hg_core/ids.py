"""Composite show IDs: ``source:native_id`` (e.g. ``huangguo:7951``).

Bare numeric / legacy IDs are treated as ``huangguo`` for backward compatibility.
"""

from __future__ import annotations

DEFAULT_SOURCE = "huangguo"

# Known source slugs (extend when adding adapters)
KNOWN_SOURCES = frozenset({
    "huangguo",
    "huangdou",
    "yeguo",
})


def make_key(source: str, native_id: str) -> str:
    src = (source or DEFAULT_SOURCE).strip().lower() or DEFAULT_SOURCE
    nid = str(native_id or "").strip()
    if not nid:
        return ""
    if ":" in nid and nid.split(":", 1)[0].lower() in KNOWN_SOURCES:
        return nid  # already composite
    return f"{src}:{nid}"


def parse_key(key: str, *, default_source: str = DEFAULT_SOURCE) -> tuple[str, str]:
    """Return (source, native_id). Bare ids → default_source."""
    raw = str(key or "").strip()
    if not raw:
        return default_source, ""
    if ":" in raw:
        src, nid = raw.split(":", 1)
        src = src.strip().lower()
        nid = nid.strip()
        if src in KNOWN_SOURCES and nid:
            return src, nid
    return (default_source or DEFAULT_SOURCE).strip().lower(), raw


def is_composite(key: str) -> bool:
    src, nid = parse_key(key)
    return bool(nid) and f"{src}:{nid}" == str(key or "").strip()
