"""Tests for ground_check, InterpretResult, and interpret."""
from __future__ import annotations

from render.interpret import InterpretResult, ground_check, interpret
from render.types import Constraint, Intent, Quantity, ResultBundle, ValidationReport


def _make_bundle(*qty_pairs) -> ResultBundle:
    quantities = [Quantity(name=n, value=v) for n, v in qty_pairs]
    return ResultBundle(engine="test", quantities=quantities, converged=True)


def _make_intent() -> Intent:
    return Intent(
        mode="simulation_explicit",
        question="Test interpretation",
        family="ode",
        engine="harmonic_oscillator",
        parameters={"k": 1.0},
        constraints=[Constraint(name="k", value=1.0)],
    )


# ── ground_check ──────────────────────────────────────────────────────────────

def test_ground_check_passes_when_numbers_in_bundle():
    bundle = _make_bundle(("energy", 3.14159), ("period", 6.28318))
    text = "The energy is 3.14159 J and the period is 6.28318 s."
    report = ground_check(text, bundle)
    assert report.passed


def test_ground_check_fails_on_fabricated_number():
    bundle = _make_bundle(("energy", 3.0))
    text = "The energy is 999.99 J."  # 999.99 not in bundle
    report = ground_check(text, bundle)
    assert not report.passed


def test_ground_check_passes_no_numbers_in_text():
    bundle = _make_bundle(("converged", True))
    text = "The simulation converged successfully."
    report = ground_check(text, bundle)
    assert report.passed


def test_ground_check_ignores_zero():
    bundle = _make_bundle(("energy", 5.0), ("start", 0.0))
    # 0 is in the bundle as start=0.0; 5.0 is in the bundle as energy
    text = "Starting from 0, the energy reached 5.0."
    report = ground_check(text, bundle)
    assert report.passed


def test_ground_check_rtol_boundary():
    bundle = _make_bundle(("x", 100.0))
    text = "x = 100.9"  # 0.9% off — within 1% rtol
    report = ground_check(text, bundle)
    assert report.passed

    text2 = "x = 102.0"  # 2% off — outside 1%
    report2 = ground_check(text2, bundle)
    assert not report2.passed


# ── interpret (template fallback, no API key needed) ──────────────────────────

def test_interpret_returns_intrepretresult():
    bundle = _make_bundle(("period", 6.28), ("energy_max", 0.5))
    validation = ValidationReport(passed=True, confidence=0.95)
    intent = _make_intent()
    result = interpret(intent, bundle, validation, engine_status="certified",
                       api_key="invalid-key")  # will fall back to template
    assert isinstance(result, InterpretResult)


def test_interpret_certified_badge():
    bundle = _make_bundle(("period", 6.28))
    validation = ValidationReport(passed=True, confidence=0.9)
    intent = _make_intent()
    result = interpret(intent, bundle, validation, engine_status="certified", api_key="x")
    assert "CERTIFIED" in result.status_badge


def test_interpret_experimental_badge():
    bundle = _make_bundle(("period", 6.28))
    validation = ValidationReport(passed=True, confidence=0.9)
    intent = _make_intent()
    result = interpret(intent, bundle, validation, engine_status="experimental", api_key="x")
    assert "EXPERIMENTAL" in result.status_badge


def test_interpret_confidence_capped_experimental():
    bundle = _make_bundle(("x", 1.0))
    validation = ValidationReport(passed=True, confidence=0.99)
    intent = _make_intent()
    result = interpret(intent, bundle, validation, engine_status="experimental", api_key="x")
    assert result.confidence <= 0.6


def test_interpret_grounding_field_present():
    bundle = _make_bundle(("period", 6.28))
    validation = ValidationReport(passed=True)
    intent = _make_intent()
    result = interpret(intent, bundle, validation, engine_status="certified", api_key="x")
    assert isinstance(result.grounding, ValidationReport)


def test_interpret_formatted_contains_badge():
    bundle = _make_bundle(("period", 6.28))
    validation = ValidationReport(passed=True)
    intent = _make_intent()
    result = interpret(intent, bundle, validation, engine_status="certified", api_key="x")
    fmt = result.formatted()
    assert "CERTIFIED" in fmt
    assert "Confidence" in fmt
