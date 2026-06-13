"""Tests for the optional production guards (token gate + rate limit).

The guards must be a no-op by default and only activate when their environment
variables are set, so the public/static surface always stays reachable.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import render.app.main as _main
from render.app.main import app

# The middleware registered on `app` closes over render.app.guard's module
# globals; reach the live per-IP hit map so we can reset it between tests.
_HITS = _main.guard_middleware.__globals__["_HITS"]


@pytest.fixture(autouse=True)
def _reset_rate_state():
    _HITS.clear()
    yield
    _HITS.clear()


def test_no_guard_by_default(monkeypatch):
    monkeypatch.delenv("RENDER_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("RENDER_RATE_LIMIT", raising=False)
    c = TestClient(app)
    assert c.get("/health").status_code == 200
    # Empty question hits validation (422), proving the guard let it through.
    assert c.post("/ask", json={"question": ""}).status_code == 422


def test_health_reports_auth_required(monkeypatch):
    monkeypatch.delenv("RENDER_ACCESS_TOKEN", raising=False)
    assert TestClient(app).get("/health").json()["auth_required"] is False
    monkeypatch.setenv("RENDER_ACCESS_TOKEN", "sekret")
    assert TestClient(app).get("/health").json()["auth_required"] is True


def test_token_gate_blocks_and_allows(monkeypatch):
    monkeypatch.setenv("RENDER_ACCESS_TOKEN", "sekret")
    monkeypatch.delenv("RENDER_RATE_LIMIT", raising=False)
    c = TestClient(app)
    # Open surface stays reachable.
    assert c.get("/").status_code == 200
    assert c.get("/health").status_code == 200
    assert c.get("/coverage").status_code == 200
    # Guarded endpoint: no token / wrong token -> 401.
    assert c.post("/ask", json={"question": "x"}).status_code == 401
    assert (
        c.post("/ask", json={"question": "x"}, headers={"Authorization": "Bearer nope"}).status_code
        == 401
    )
    # Correct token passes the guard (422 = reached request validation).
    ok = c.post("/ask", json={"question": ""}, headers={"Authorization": "Bearer sekret"})
    assert ok.status_code == 422
    # Token via query param also works.
    assert c.post("/ask?token=sekret", json={"question": ""}).status_code == 422


def test_rate_limit(monkeypatch):
    monkeypatch.delenv("RENDER_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("RENDER_RATE_LIMIT", "3")
    monkeypatch.setenv("RENDER_RATE_WINDOW", "60")
    c = TestClient(app)
    codes = [c.post("/ask", json={"question": ""}).status_code for _ in range(5)]
    assert codes[:3] == [422, 422, 422]
    assert codes[3] == 429 and codes[4] == 429
