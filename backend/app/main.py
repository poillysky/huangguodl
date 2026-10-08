from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

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
    from .services.follow import start_follow_loop, stop_follow_loop

    settings = get_settings()
    os.environ.setdefault("HG_API", settings.hg_api)
    if settings.cover_proxy:
        os.environ.setdefault("COVER_PROXY", settings.cover_proxy)
    if settings.cover_token:
        os.environ.setdefault("COVER_TOKEN", settings.cover_token)
    S.init(settings)
    start_follow_loop()
    try:
        yield
    finally:
        stop_follow_loop()


app = FastAPI(title="hg-dl", version="1.0.0", lifespan=lifespan)
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


def _mount_spa(static_dir: Path) -> None:
    """单一镜像：API 之外托管前端，并做 SPA 回退。"""
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/sw.js")
    async def service_worker() -> FileResponse:
        return FileResponse(
            static_dir / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/manifest.webmanifest")
    async def web_manifest() -> FileResponse:
        return FileResponse(
            static_dir / "manifest.webmanifest",
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    icons = static_dir / "icons"
    if icons.is_dir():
        app.mount("/icons", StaticFiles(directory=str(icons)), name="icons")

    index = static_dir / "index.html"

    @app.get("/")
    async def spa_index() -> FileResponse:
        return FileResponse(index)

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> Response:
        # /api 已由 router 处理；其余先找静态文件，否则 index.html
        if full_path.startswith("api/") or full_path == "api":
            return Response(status_code=404)
        candidate = (static_dir / full_path).resolve()
        try:
            candidate.relative_to(static_dir.resolve())
        except ValueError:
            return FileResponse(index)
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


_static = (os.environ.get("STATIC_DIR") or "").strip()
if _static and Path(_static).is_dir():
    _mount_spa(Path(_static))


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
