"""Tests for the EngineAdapter Protocol, registry, and built-in reference engine."""

import math

import pytest

from render.engines.reference import HarmonicOscillatorAdapter
from render.eval.runner import eval_engine, run_reference_case
from render.registry import EngineAdapter, EngineRegistry
from render.types import (
    EnvSpec,
    Intent,
    ResourceSpec,
    ValidationReport,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def adapter() -> HarmonicOscillatorAdapter:
    return HarmonicOscillatorAdapter()


@pytest.fixture()
def reg() -> EngineRegistry:
    return EngineRegistry()


# ── Protocol conformance ──────────────────────────────────────────────────────


def test_adapter_is_protocol(adapter: HarmonicOscillatorAdapter) -> None:
    assert isinstance(adapter, EngineAdapter)


def test_adapter_attributes(adapter: HarmonicOscillatorAdapter) -> None:
    assert adapter.name == "harmonic_oscillator"
    assert adapter.family == "ode"
    assert adapter.status == "certified"
    assert isinstance(adapter.environment, EnvSpec)


def test_adapter_has_reference_cases(adapter: HarmonicOscillatorAdapter) -> None:
    assert len(adapter.reference_cases) >= 2


# ── Registry ──────────────────────────────────────────────────────────────────


def test_register_and_get(reg: EngineRegistry, adapter: HarmonicOscillatorAdapter) -> None:
    reg.register(adapter)
    assert "harmonic_oscillator" in reg
    retrieved = reg.get("harmonic_oscillator")
    assert retrieved.name == "harmonic_oscillator"


def test_register_duplicate_raises(reg: EngineRegistry, adapter: HarmonicOscillatorAdapter) -> None:
    reg.register(adapter)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(adapter)


def test_get_unknown_raises(reg: EngineRegistry) -> None:
    with pytest.raises(KeyError):
        reg.get("nonexistent_engine")


def test_list_by_status(reg: EngineRegistry, adapter: HarmonicOscillatorAdapter) -> None:
    reg.register(adapter)
    certified = reg.list_by_status("certified")
    assert any(a.name == "harmonic_oscillator" for a in certified)
    experimental = reg.list_by_status("experimental")
    assert not any(a.name == "harmonic_oscillator" for a in experimental)


def test_list_by_family(reg: EngineRegistry, adapter: HarmonicOscillatorAdapter) -> None:
    reg.register(adapter)
    ode_engines = reg.list_by_family("ode")
    assert any(a.name == "harmonic_oscillator" for a in ode_engines)
    assert not reg.list_by_family("md")


def test_certified_engine_without_reference_cases_raises(reg: EngineRegistry) -> None:
    class NoCasesAdapter:
        name = "no_cases"
        family = "ode"
        status = "certified"
        runtime = "local"
        environment = EnvSpec(env_type="pip")

        @property
        def intent_schema(self): ...
        @property
        def reference_cases(self):
            return []

        def validate(self, intent): ...
        def build_inputs(self, intent): ...
        def run(self, inputs, resources): ...
        def parse(self, raw): ...

    with pytest.raises(ValueError, match="no reference cases"):
        reg.register(NoCasesAdapter())


# ── Harmonic oscillator correctness ───────────────────────────────────────────


def _intent(
    omega0: float = 1.0, zeta: float = 0.0, x0: float = 1.0, v0: float = 0.0, t_end: float = 10.0
) -> Intent:
    return Intent(
        mode="simulation_explicit",
        question="test",
        family="ode",
        engine="harmonic_oscillator",
        parameters={"omega0": omega0, "zeta": zeta, "x0": x0, "v0": v0, "t_end": t_end},
    )


def test_undamped_period(adapter: HarmonicOscillatorAdapter) -> None:
    intent = _intent(omega0=1.0, zeta=0.0, x0=1.0)
    inputs = adapter.build_inputs(intent)
    raw = adapter.run(inputs, ResourceSpec())
    bundle = adapter.parse(raw)
    period = bundle.get("period")
    assert period is not None
    assert abs(period.value - 2 * math.pi) < 1e-9


def test_underdamped_natural_frequency(adapter: HarmonicOscillatorAdapter) -> None:
    omega0, zeta = 3.0, 0.5
    omegad_expected = omega0 * math.sqrt(1 - zeta**2)
    intent = _intent(omega0=omega0, zeta=zeta, x0=1.0)
    inputs = adapter.build_inputs(intent)
    raw = adapter.run(inputs, ResourceSpec())
    bundle = adapter.parse(raw)
    omegad = bundle.get("omegad")
    assert omegad is not None
    assert abs(omegad.value - omegad_expected) < 1e-9


def test_zero_initial_displacement_zero_velocity(adapter: HarmonicOscillatorAdapter) -> None:
    intent = _intent(omega0=2.0, zeta=0.1, x0=0.0, v0=0.0)
    inputs = adapter.build_inputs(intent)
    raw = adapter.run(inputs, ResourceSpec())
    bundle = adapter.parse(raw)
    x_max = bundle.get("x_max")
    assert x_max is not None
    assert abs(x_max.value) < 1e-12


def test_validation_bad_zeta(adapter: HarmonicOscillatorAdapter) -> None:
    intent = _intent(zeta=1.5)  # overdamped — outside regime
    report = adapter.validate(intent)
    assert not report.passed
    assert report.failed_layer == 1


def test_validation_bad_omega0(adapter: HarmonicOscillatorAdapter) -> None:
    intent = _intent(omega0=-1.0)
    report = adapter.validate(intent)
    assert not report.passed


def test_validation_passes(adapter: HarmonicOscillatorAdapter) -> None:
    intent = _intent()
    report = adapter.validate(intent)
    assert report.passed
    assert isinstance(report, ValidationReport)


# ── Reference-case runner ─────────────────────────────────────────────────────


def test_reference_cases_pass(adapter: HarmonicOscillatorAdapter) -> None:
    report = eval_engine(adapter)
    assert report.ok, "Reference cases failed:\n" + "\n".join(
        f"  {r.case_name}: {r.failures}" for r in report.cases if not r.passed
    )
    assert report.passed == report.total


def test_individual_reference_case(adapter: HarmonicOscillatorAdapter) -> None:
    case = adapter.reference_cases[0]
    result = run_reference_case(adapter, case)
    assert result.passed, result.failures
