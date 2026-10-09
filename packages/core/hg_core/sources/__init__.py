"""Multi-source catalog adapters."""

from hg_core.sources.base import CatalogSource
from hg_core.sources.huangdou import HuangdouSource
from hg_core.sources.huangguo import HuangguoSource
from hg_core.sources.registry import SourceRegistry
from hg_core.sources.yeguo import YeguoSource

__all__ = [
    "CatalogSource",
    "HuangdouSource",
    "HuangguoSource",
    "YeguoSource",
    "SourceRegistry",
]
