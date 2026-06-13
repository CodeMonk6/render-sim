"""Render FastAPI application — main entry point."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import render
from render.app.guard import guard_middleware
from render.app.routers import ask as ask_router
from render.app.routers import coverage as coverage_router
from render.app.routers import eval as eval_router
from render.app.routers import runs as runs_router

app = FastAPI(
    title="Render",
    description="Natural-language → simulation → interpretation co-pilot for researchers.",
    version=render.__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Optional production guards (token gate + per-IP rate limit). No-op unless the
# RENDER_ACCESS_TOKEN / RENDER_RATE_LIMIT environment variables are set.
app.middleware("http")(guard_middleware)

app.include_router(ask_router.router)
app.include_router(eval_router.router)
app.include_router(coverage_router.router)
app.include_router(runs_router.router)

_STATIC = Path(__file__).parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> FileResponse:
    return FileResponse(str(_STATIC / "index.html"))


@app.get("/health")
async def health() -> dict:
    import os

    from render.llm import get_api_key, get_default_model, get_provider

    provider = get_provider()
    return {
        "status": "ok",
        "version": render.__version__,
        "provider": provider,
        "model": get_default_model(provider),
        "has_key": bool(get_api_key()),
        "auth_required": bool(os.environ.get("RENDER_ACCESS_TOKEN")),
    }
