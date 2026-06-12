"""Tests for the canonical engine bootstrap and the /coverage scoreboard.

These pin the regression that the silent ``SIRAdapter``/``EpiAdapter`` mismatch
caused: the epidemiology family must register, and any future canonical-list typo
must surface as a ``registration_error`` rather than vanishing.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from render.app.main import app
from render.registry import EngineRegistry
from render.registry.bootstrap import ENGINE_SPECS, register_all_engines


def test_bootstrap_registers_every_spec_cleanly() -> None:
    reg = EngineRegistry()
    report = register_all_engines(reg)
    assert report.ok, f"registration errors: {report.errors}"
    assert not report.errors
    # harmonic_oscillator + every canonical spec import cleanly with lazy deps.
    assert len(reg) == len(ENGINE_SPECS) + 1


def test_bootstrap_registers_epi_family() -> None:
    """Regression: the epi engine was silently dropped by a wrong class name."""
    reg = EngineRegistry()
    register_all_engines(reg)
    assert reg.list_by_family("epi"), "epidemiology family failed to register"


def test_bootstrap_is_idempotent() -> None:
    reg = EngineRegistry()
    first = register_all_engines(reg)
    n = len(reg)
    second = register_all_engines(reg)
    assert len(reg) == n
    assert second.registered == []
    assert set(second.already_present) >= set(first.registered)


def test_bootstrap_surfaces_bad_class_name(monkeypatch) -> None:
    """A typo in the canonical list must become a recorded error, never silent."""
    import render.registry.bootstrap as bs

    bad = [*ENGINE_SPECS, ("render.engines.epi", "DoesNotExistAdapter")]
    monkeypatch.setattr(bs, "ENGINE_SPECS", bad)
    reg = EngineRegistry()
    report = bs.register_all_engines(reg)
    assert not report.ok
    assert any("DoesNotExistAdapter" in spec for spec, _ in report.errors)


def test_coverage_endpoint() -> None:
    client = TestClient(app)
    resp = client.get("/coverage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["registration_errors"] == []
    assert data["total_engines"] == data["certified"] + data["experimental"]
    assert data["family_count"] == len(data["families"])
    families = {f["family"] for f in data["families"]}
    assert "epi" in families
    assert "ode" in families
    # Per-family counts must sum to the totals.
    assert sum(f["certified"] for f in data["families"]) == data["certified"]
    assert sum(f["experimental"] for f in data["families"]) == data["experimental"]
    # Every engine row carries a trust status and runtime.
    for fam in data["families"]:
        for eng in fam["engines"]:
            assert eng["status"] in ("certified", "experimental")
            assert eng["runtime"] in ("local", "hpc", "either")


def test_coverage_certified_engines_have_reference_cases() -> None:
    """Invariant: a Certified engine always carries reference cases."""
    client = TestClient(app)
    data = client.get("/coverage").json()
    for fam in data["families"]:
        for eng in fam["engines"]:
            if eng["status"] == "certified":
                assert eng["reference_cases"] >= 1, eng["name"]
