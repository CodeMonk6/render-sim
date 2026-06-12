"""Optional production guards for public deployments.

Both guards are **off by default** — with no environment variables set, the
middleware is a pass-through and the app behaves exactly as in development.
They exist so a public demo backed by a server-side LLM key can defend itself
without standing up a full auth stack:

* ``RENDER_ACCESS_TOKEN`` — when set, the expensive endpoints (``/ask``,
  ``/eval``) require a matching token, supplied either as a bearer token in the
  ``Authorization`` header or as ``?token=``.  The static page, ``/health``,
  ``/coverage`` and ``/runs`` stay open so the UI still loads and can prompt for
  the token.
* ``RENDER_RATE_LIMIT`` — when set to an integer N, each client IP may call the
  guarded endpoints at most N times per ``RENDER_RATE_WINDOW`` seconds
  (default 60).  A tiny in-memory sliding window — fine for a single-instance
  demo.  For multi-instance or heavier traffic, put ``slowapi``/Redis in front.

Wired in :mod:`render.app.main` via ``app.middleware("http")``.
"""

from __future__ import annotations

import os
import time
from collections import deque

from fastapi import Request
from fastapi.responses import JSONResponse

# Endpoints worth protecting — they spend the LLM key and/or CPU.
_GUARDED_PREFIXES = ("/ask", "/eval")

# Per-IP request timestamps for the sliding-window limiter.
_HITS: dict[str, deque[float]] = {}


def _client_ip(request: Request) -> str:
    """Best-effort client IP, trusting the first proxy hop if present."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _token_from(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token", "") or request.headers.get("x-render-token", "")


def _check_token(request: Request) -> JSONResponse | None:
    expected = os.environ.get("RENDER_ACCESS_TOKEN", "")
    if not expected:
        return None
    import secrets

    provided = _token_from(request)
    if not provided or not secrets.compare_digest(provided, expected):
        return JSONResponse(
            status_code=401,
            content={"detail": "This demo is access-gated. Provide a valid token."},
        )
    return None


def _check_rate(request: Request) -> JSONResponse | None:
    raw = os.environ.get("RENDER_RATE_LIMIT", "")
    if not raw:
        return None
    try:
        limit = int(raw)
    except ValueError:
        return None
    if limit <= 0:
        return None
    window = float(os.environ.get("RENDER_RATE_WINDOW", "60"))

    ip = _client_ip(request)
    now = time.monotonic()
    hits = _HITS.setdefault(ip, deque())
    while hits and now - hits[0] > window:
        hits.popleft()
    if len(hits) >= limit:
        retry = int(window - (now - hits[0])) + 1
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit reached ({limit} per {int(window)}s). Try again soon."},
            headers={"Retry-After": str(retry)},
        )
    hits.append(now)
    return None


async def guard_middleware(request: Request, call_next):
    """ASGI middleware: enforce token + rate guards on the guarded endpoints."""
    path = request.url.path
    if request.method != "OPTIONS" and any(path.startswith(p) for p in _GUARDED_PREFIXES):
        blocked = _check_token(request) or _check_rate(request)
        if blocked is not None:
            return blocked
    return await call_next(request)
