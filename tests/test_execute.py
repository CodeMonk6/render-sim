"""Tests for run_local, manifest serialization, and replay."""

from __future__ import annotations

from pathlib import Path

from render.engines.reference import HarmonicOscillatorAdapter
from render.execute.local import run_local
from render.types import Constraint, Intent, RunManifest


def _harmonic_intent() -> Intent:
    return Intent(
        mode="simulation_explicit",
        question="Harmonic oscillator omega0=1 x0=1",
        family="ode",
        engine="harmonic_oscillator",
        parameters={
            "omega0": 1.0,
            "x0": 1.0,
            "v0": 0.0,
            "zeta": 0.0,
            "t_end": 6.28318,
            "n_points": 100,
        },
        constraints=[Constraint(name="omega0", value=1.0)],
    )


def test_run_local_returns_manifest():
    adapter = HarmonicOscillatorAdapter()
    intent = _harmonic_intent()
    manifest = run_local(adapter, intent)
    assert isinstance(manifest, RunManifest)
    assert manifest.engine_name == "harmonic_oscillator"
    assert manifest.run_id is not None


def test_manifest_has_quantities():
    adapter = HarmonicOscillatorAdapter()
    intent = _harmonic_intent()
    manifest = run_local(adapter, intent)
    qty_names = {q.name for q in manifest.bundle.quantities}
    assert "period" in qty_names
    assert "x_max" in qty_names


def test_manifest_validation_passed():
    adapter = HarmonicOscillatorAdapter()
    intent = _harmonic_intent()
    manifest = run_local(adapter, intent)
    assert manifest.validation.passed


def test_manifest_serialization(tmp_path: Path):
    adapter = HarmonicOscillatorAdapter()
    intent = _harmonic_intent()
    manifest = run_local(adapter, intent, manifest_dir=tmp_path)
    # File should be written
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    # Round-trip: deserialize and compare
    manifest2 = RunManifest.model_validate_json(files[0].read_text())
    assert manifest2.run_id == manifest.run_id
    assert manifest2.engine_name == manifest.engine_name


def test_manifest_json_roundtrip():
    adapter = HarmonicOscillatorAdapter()
    intent = _harmonic_intent()
    manifest = run_local(adapter, intent)
    data = manifest.model_dump_json()
    manifest2 = RunManifest.model_validate_json(data)
    assert manifest2.run_id == manifest.run_id
    assert len(manifest2.bundle.quantities) == len(manifest.bundle.quantities)


def test_replay_reproduces_within_tolerance():
    adapter = HarmonicOscillatorAdapter()
    intent = _harmonic_intent()
    m1 = run_local(adapter, intent)
    m2 = run_local(adapter, intent)
    # Deterministic engine — identical
    for q1 in m1.bundle.quantities:
        q2 = m2.bundle.get(q1.name)
        assert q2 is not None
        try:
            v1 = float(q1.value)
            v2 = float(q2.value)
            denom = abs(v1) if v1 != 0 else 1.0
            assert abs(v1 - v2) / denom < 1e-6, f"{q1.name}: {v1} vs {v2}"
        except (TypeError, ValueError):
            pass


def test_run_local_engine_status_in_manifest():
    adapter = HarmonicOscillatorAdapter()
    intent = _harmonic_intent()
    manifest = run_local(adapter, intent)
    assert manifest.engine_status == "certified"


def test_run_local_replay_cmd_field():
    adapter = HarmonicOscillatorAdapter()
    intent = _harmonic_intent()
    manifest = run_local(adapter, intent)
    assert "replay" in manifest.replay_cmd
