from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure packages/core is importable before routes load hg_core
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CORE = os.path.join(_ROOT, "packages", "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from .config import get_settings  # noqa: E402
from .routes.api import router  # noqa: E402
from .services.state import S  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    os.environ.setdefault("HG_API", settings.hg_api)
    if settings.cover_proxy:
        os.environ.setdefault("COVER_PROXY", settings.cover_proxy)
    if settings.cover_token:
        os.environ.setdefault("COVER_TOKEN", settings.cover_token)
    S.init(settings)
    yield


app = FastAPI(title="hg-dl API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # 鉴权走 Bearer / ?access_token=，不用 Cookie；带 credentials 的
    # 通配 origin 会被浏览器拒绝（规范禁止），关掉即可。
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
