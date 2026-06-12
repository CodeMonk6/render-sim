"""Tests for the end-to-end orchestration pipeline (render.pipeline.run_question).

The LLM steps are monkeypatched so these run offline and deterministically —
they exercise the orchestration (bind params → clarify/abstain → run → result),
not the model.
"""

from __future__ import annotations

import render.intent as intent_mod
from render.pipeline import run_question
from render.types import Intent


def _intent(engine: str, params: dict) -> Intent:
    return Intent(
        mode="simulation_explicit",
        question="test",
        family="ode",
        engine=engine,
        parameters=params,
    )


def test_run_question_ok_runs_and_returns_series(monkeypatch):
    """A fully-specified harmonic question runs locally and yields quantities + series."""
    good = {"omega0": 2.0, "zeta": 0.1, "x0": 1.0, "v0": 0.0, "t_end": 20.0, "n_points": 200}
    monkeypatch.setattr(
        intent_mod, "parse_intent", lambda *a, **k: (_intent("harmonic_oscillator", good), None)
    )

    r = run_question("damped oscillator", api_key="x", manifest_dir=None)
    assert r.status == "ok"
    assert r.engine_name == "harmonic_oscillator"
    assert r.engine_status == "certified"
    names = {q["name"] for q in r.quantities}
    assert {"omega0", "period", "x_max"} <= names
    assert r.series and r.series["y"], "expected trajectory series for plotting"
    assert r.run_id


def test_run_question_binds_params_to_engine_schema(monkeypatch):
    """Generic first-pass param names get re-extracted into the engine schema."""
    # First pass returns wrong names; the schema-binding pass supplies the real ones.
    monkeypatch.setattr(
        intent_mod,
        "parse_intent",
        lambda *a, **k: (_intent("harmonic_oscillator", {"natural_frequency": 2}), None),
    )
    monkeypatch.setattr(
        intent_mod,
        "extract_engine_parameters",
        lambda q, schema, **k: {"omega0": 2.0, "zeta": 0.1, "x0": 1.0, "t_end": 10.0},
    )

    r = run_question("oscillator with natural frequency 2", api_key="x", manifest_dir=None)
    assert r.status == "ok"
    assert r.parameters["omega0"] == 2.0


def test_run_question_clarifies_on_missing_fields(monkeypatch):
    """Missing required fields → clarify (ask), never a bad run."""
    monkeypatch.setattr(
        intent_mod, "parse_intent", lambda *a, **k: (_intent("harmonic_oscillator", {}), None)
    )
    monkeypatch.setattr(
        intent_mod, "extract_engine_parameters", lambda q, schema, **k: {}
    )  # still nothing extractable

    r = run_question("simulate something", api_key="x", manifest_dir=None)
    assert r.status == "clarify"
    assert r.missing_fields


def test_run_question_abstains_on_unknown_engine(monkeypatch):
    monkeypatch.setattr(
        intent_mod, "parse_intent", lambda *a, **k: (_intent("does_not_exist", {"x": 1}), None)
    )
    r = run_question("run the impossible engine", api_key="x", manifest_dir=None)
    assert r.status == "abstain"
    assert "does_not_exist" in r.message


def test_run_question_dry_run(monkeypatch):
    good = {"omega0": 1.0, "zeta": 0.0, "x0": 1.0, "v0": 0.0, "t_end": 6.28, "n_points": 50}
    monkeypatch.setattr(
        intent_mod, "parse_intent", lambda *a, **k: (_intent("harmonic_oscillator", good), None)
    )
    r = run_question("dry run please", dry_run=True, api_key="x", manifest_dir=None)
    assert r.status == "dry_run"
    assert r.run_id is None
