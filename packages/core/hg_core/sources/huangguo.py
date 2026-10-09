"""Huangguo adapter — wraps existing HGApi."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hg_core.ids import DEFAULT_SOURCE

if TYPE_CHECKING:
    from hg_core import HGApi, Show


class HuangguoSource:
    name = DEFAULT_SOURCE
    title = "黄果"

    def __init__(self, api: HGApi) -> None:
        self.api = api

    @property
    def base(self) -> str:
        return str(getattr(self.api, "base", "") or "")

    @property
    def headers(self) -> dict:
        return getattr(self.api, "headers", {}) or {}

    @property
    def opener(self):
        return getattr(self.api, "opener", None)

    def categories(self) -> list[tuple[str, str]]:
        """仅返回大类频道，不含 tag 题材（题材走 tags()）。"""
        from hg_core import CATEGORIES

        channels = (
            "hot",
            "new",
            "rank",
            "ai-duanju",
            "ai-manju",
            "ai-huanlian",
            "ai-mogai",
        )
        return [(k, CATEGORIES[k]) for k in channels if k in CATEGORIES]

    def tags(self) -> list[tuple[str, str]]:
        """官方题材：/api/tags → [(slug, name), ...]。"""
        return list(self.api.list_tags() or [])

    def _tag(self, shows: list[Show]) -> list[Show]:
        for s in shows:
            if not getattr(s, "source", None):
                s.source = self.name
        return shows

    def catalog(
        self,
        category: str,
        page: int,
        page_size: int,
        *,
        sort: str | None = None,
        tab: str | None = None,  # noqa: ARG002 — 黄果无频道子 Tab
    ) -> list[Show]:
        return self._tag(self.api.catalog(category, page, page_size, sort=sort))

    def search(self, keyword: str, page: int = 1) -> list[Show]:
        return self._tag(self.api.search(keyword, page))

    def _to_show(self, raw: dict) -> Show | None:
        s = self.api._to_show(raw)
        if s:
            s.source = self.name
        return s

    def detail(self, show: Show) -> dict[str, Any]:
        return self.api.detail(show)

    def episodes(self, show: Show) -> list[dict[str, Any]]:
        return self.api.episodes(show)

    def play_url(self, show: Show, ep: int, preset: str = "") -> str:
        return self.api.play_url(show, ep, preset=preset)

    def cover_url(self, show: Show) -> str:
        return self.api.cover_url(show)

    def fetch_cover(self, url: str, dest: str, *, timeout: int = 30) -> tuple[bool, str]:
        return self.api.fetch_cover(url, dest, timeout=timeout)

    def match(
        self, title: str, threshold: float = 0.62
    ) -> tuple[Show | None, float, list[Show]]:
        best, score, top = self.api.match(title, threshold=threshold)
        if best:
            best.source = self.name
        for s in top:
            s.source = self.name
        return best, score, top
