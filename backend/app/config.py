from __future__ import annotations

import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import ROOT, resolve_path

_ENV_FILE = os.path.join(ROOT, ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE if os.path.isfile(_ENV_FILE) else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    hg_api: str = "https://huangguoai.com"
    huangdou_api: str = "https://lzlukvca.cc"
    yeguo_api: str = "https://www.yeguodj.com/api.php"
    # comma-separated: huangguo,huangdou,yeguo
    sources_enabled: str = "huangguo,huangdou,yeguo"
    # media files only
    out_dir: str = "downloads"
    # runtime settings + API cache (not media)
    data_dir: str = "data"
    cover_proxy: str = "https://ai.wulii.de5.net"
    cover_token: str = ""
    http_proxy: str = ""  # e.g. http://127.0.0.1:7890
    api_token: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    cache_ttl: int = 1800
    workers: int = 3
    # 同时进行的下载任务数（多剧并行上限）
    max_parallel_tasks: int = 2
    # 全局分集下载并发（跨任务共享，保护 NAS/带宽）
    max_global_workers: int = 4
    scan_dir: str = ""

    @field_validator("out_dir", "data_dir", mode="before")
    @classmethod
    def _abs_project_paths(cls, v: object, info) -> str:  # noqa: ANN001
        default = "downloads" if info.field_name == "out_dir" else "data"
        return resolve_path(str(v or ""), default)


@lru_cache
def get_settings() -> Settings:
    return Settings()
