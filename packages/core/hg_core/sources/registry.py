"""Merge multiple CatalogSource adapters into one facade."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from hg_core.ids import DEFAULT_SOURCE, make_key, parse_key


class SourceRegistry:
    """Facade used by backend in place of a single HGApi for catalog/search/detail."""

    def __init__(self, sources: list[Any] | None = None) -> None:
        self._sources: dict[str, Any] = {}
        self._order: list[str] = []
        for src in sources or []:
            self.register(src)

    def register(self, source: Any) -> None:
        name = str(getattr(source, "name", "") or "").strip().lower()
        if not name:
            raise ValueError("source.name required")
        if name not in self._sources:
            self._order.append(name)
        self._sources[name] = source

    def list_sources(self) -> list[dict[str, str]]:
        return [
            {"name": n, "title": str(getattr(self._sources[n], "title", n))}
            for n in self._order
            if n in self._sources
        ]

    def get(self, name: str) -> Any | None:
        return self._sources.get((name or "").strip().lower())

    def primary(self) -> Any:
        if not self._order:
            raise RuntimeError("无可用片源")
        return self._sources[self._order[0]]

    @property
    def huangguo_api(self) -> Any | None:
        """Underlying HGApi if 黄果 is registered (download/cover helpers)."""
        src = self.get(DEFAULT_SOURCE)
        return getattr(src, "api", None) if src else None

    @property
    def base(self) -> str:
        api = self.huangguo_api
        return str(getattr(api, "base", "") or "")

    @property
    def headers(self) -> dict:
        api = self.huangguo_api
        if api is not None:
            return getattr(api, "headers", {}) or {}
        return getattr(self.primary(), "headers", {}) or {}

    @property
    def opener(self) -> Any:
        api = self.huangguo_api
        if api is not None:
            return getattr(api, "opener", None)
        return getattr(self.primary(), "opener", None)

    @property
    def cache(self) -> Any | None:
        api = self.huangguo_api
        return getattr(api, "cache", None) if api else None

    def _to_show(self, raw: dict) -> Any | None:
        """Compat: detail→Show via primary (黄果) parser."""
        api = self.huangguo_api
        if api is None:
            return None
        return api._to_show(raw)

    def open(self, req: Any, *, timeout: int | None = None):
        """Compat for cover proxy: use 黄果 opener (shared HTTP proxy)."""
        api = self.huangguo_api
        if api is not None and hasattr(api, "open"):
            return api.open(req, timeout=timeout)
        primary = self.primary()
        opener = getattr(primary, "opener", None)
        if opener is None:
            raise RuntimeError("无可用 HTTP opener")
        return opener.open(req, timeout=timeout if timeout is not None else 20)

    def categories(self, source: str | None = None) -> list[dict[str, str]]:
        if source:
            src = self.get(source)
            if not src:
                return []
            return [{"value": k, "title": v} for k, v in src.categories()]
        # merge unique by value, prefer first source's labels
        seen: set[str] = set()
        out: list[dict[str, str]] = []
        for name in self._order:
            for k, v in self._sources[name].categories():
                if k in seen:
                    continue
                seen.add(k)
                out.append({"value": k, "title": v})
        return out

    def tags(self, source: str | None = None) -> list[dict[str, str]]:
        """题材列表（目前黄果有官方 /api/tags；其它源返回空）。"""
        name = (source or "").strip().lower() or DEFAULT_SOURCE
        src = self.get(name)
        if src is None or not hasattr(src, "tags"):
            return []
        try:
            pairs = src.tags() or []
        except Exception:  # noqa: BLE001
            return []
        return [{"value": str(k), "title": str(v)} for k, v in pairs if k]

    def browse_filters(self, source: str | None = None) -> dict[str, Any]:
        name = (source or "").strip().lower()
        if not name:
            return {}
        src = self.get(name)
        if src is None or not hasattr(src, "browse_filters"):
            return {}
        try:
            data = src.browse_filters() or {}
        except Exception:  # noqa: BLE001
            return {}
        return data if isinstance(data, dict) else {}

    def channel_tabs(
        self, category: str, *, source: str | None = None
    ) -> list[dict[str, str]]:
        """黄豆等源：某分类下的官方子 Tab。"""
        name = (source or "").strip().lower() or "huangdou"
        src = self.get(name)
        if src is None or not hasattr(src, "channel_tabs"):
            return []
        try:
            pairs = src.channel_tabs(category) or []
        except Exception:  # noqa: BLE001
            return []
        return [{"value": str(k), "title": str(v)} for k, v in pairs if k]

    def resolve_show(self, key: str, *, title: str = "") -> Any:
        """Build a Show stub with source + native id from composite or bare key."""
        from hg_core import Show

        src_name, nid = parse_key(key)
        return Show(id=nid, title=title or nid, source=src_name)

    def source_for(self, show_or_key: Any) -> Any:
        if hasattr(show_or_key, "source"):
            name = getattr(show_or_key, "source", None) or DEFAULT_SOURCE
            nid = getattr(show_or_key, "id", "")
        else:
            name, nid = parse_key(str(show_or_key or ""))
        src = self.get(name)
        if src is None:
            # fall back to primary so legacy bare ids still work
            src = self.primary()
        return src

    def catalog(
        self,
        category: str = "hot",
        page: int = 1,
        page_size: int = 24,
        *,
        sort: str | None = None,
        source: str | None = None,
        tab: str | None = None,
    ) -> list[Any]:
        if source:
            src = self.get(source)
            if not src:
                return []
            return list(
                src.catalog(category, page, page_size, sort=sort, tab=tab) or []
            )

        # Fan-out: pull from all sources in parallel, interleave by rank
        buckets: dict[str, list[Any]] = {}

        def _one(name: str) -> tuple[str, list[Any]]:
            try:
                return name, list(
                    self._sources[name].catalog(
                        category, page, page_size, sort=sort, tab=tab
                    )
                    or []
                )
            except Exception:  # noqa: BLE001
                return name, []

        with ThreadPoolExecutor(max_workers=max(1, len(self._order))) as pool:
            futs = [pool.submit(_one, n) for n in self._order]
            for fut in as_completed(futs):
                name, items = fut.result()
                buckets[name] = items

        return self._interleave([buckets.get(n, []) for n in self._order], page_size)

    def search(
        self,
        keyword: str,
        page: int = 1,
        *,
        source: str | None = None,
    ) -> list[Any]:
        if source:
            src = self.get(source)
            if not src:
                return []
            return list(src.search(keyword, page) or [])

        buckets: dict[str, list[Any]] = {}

        def _one(name: str) -> tuple[str, list[Any]]:
            try:
                return name, list(self._sources[name].search(keyword, page) or [])
            except Exception:  # noqa: BLE001
                return name, []

        with ThreadPoolExecutor(max_workers=max(1, len(self._order))) as pool:
            futs = [pool.submit(_one, n) for n in self._order]
            for fut in as_completed(futs):
                name, items = fut.result()
                buckets[name] = items

        return self._interleave([buckets.get(n, []) for n in self._order], 40)

    def detail(self, show: Any) -> dict[str, Any]:
        return self.source_for(show).detail(show)

    def episodes(self, show: Any) -> list[dict[str, Any]]:
        return self.source_for(show).episodes(show)

    def play_url(self, show: Any, ep: int, preset: str = "") -> str:
        return self.source_for(show).play_url(show, ep, preset=preset)

    def cover_url(self, show: Any) -> str:
        return self.source_for(show).cover_url(show)

    def fetch_cover(self, url: str, dest: str, *, timeout: int = 30, show: Any = None) -> tuple[bool, str]:
        src = self.source_for(show) if show is not None else self.primary()
        return src.fetch_cover(url, dest, timeout=timeout)

    def match(
        self, title: str, threshold: float = 0.62, *, source: str | None = None
    ) -> tuple[Any | None, float, list[Any]]:
        if source:
            src = self.get(source) or self.primary()
            return src.match(title, threshold=threshold)

        best: Any | None = None
        best_score = 0.0
        top: list[Any] = []
        for name in self._order:
            try:
                b, sc, t = self._sources[name].match(title, threshold=threshold)
            except Exception:  # noqa: BLE001
                continue
            top.extend(t)
            if b is not None and sc > best_score:
                best, best_score = b, sc
        # de-dupe top by key
        seen: set[str] = set()
        uniq: list[Any] = []
        for s in top:
            k = make_key(getattr(s, "source", DEFAULT_SOURCE), getattr(s, "id", ""))
            if k in seen:
                continue
            seen.add(k)
            uniq.append(s)
        return best, best_score, uniq[:8]

    @staticmethod
    def _interleave(lists: list[list[Any]], limit: int) -> list[Any]:
        out: list[Any] = []
        seen: set[str] = set()
        i = 0
        while len(out) < limit:
            progressed = False
            for lst in lists:
                if i < len(lst):
                    s = lst[i]
                    k = make_key(getattr(s, "source", DEFAULT_SOURCE), getattr(s, "id", ""))
                    if k and k not in seen:
                        seen.add(k)
                        out.append(s)
                        if len(out) >= limit:
                            break
                    progressed = True
            if not progressed:
                break
            i += 1
        return out
