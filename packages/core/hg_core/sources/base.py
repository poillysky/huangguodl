"""Catalog source protocol for multi-site aggregation."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CatalogSource(Protocol):
    """One upstream adult short-drama site."""

    name: str  # slug: huangguo / huangdou / ...
    title: str  # display name

    def categories(self) -> list[tuple[str, str]]:
        """Return [(value, title), ...] for Browse filters."""
        ...

    def catalog(
        self,
        category: str,
        page: int,
        page_size: int,
        *,
        sort: str | None = None,
    ) -> list[Any]:
        ...

    def search(self, keyword: str, page: int = 1) -> list[Any]:
        ...

    def detail(self, show: Any) -> dict[str, Any]:
        ...

    def episodes(self, show: Any) -> list[dict[str, Any]]:
        ...

    def play_url(self, show: Any, ep: int, preset: str = "") -> str:
        ...

    def cover_url(self, show: Any) -> str:
        ...

    def fetch_cover(self, url: str, dest: str, *, timeout: int = 30) -> tuple[bool, str]:
        ...

    def match(
        self, title: str, threshold: float = 0.62
    ) -> tuple[Any | None, float, list[Any]]:
        ...
