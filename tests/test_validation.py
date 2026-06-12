"""Tests for the validation stack: regime, layers 1-3/5, stack, clarify/abstain."""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import BaseModel

from render.engines.reference import HarmonicOscillatorAdapter
from render.types import (
    Constraint,
    EngineInputs,
    EnvSpec,
    Intent,
    Quantity,
    RawOutputs,
    ResourceSpec,
    ResultBundle,
    TrustStatus,
    ValidationReport,
)
from render.validate import (
    ClarifyDecision,
    RegimeBound,
    RegimeSpec,
    check_regime,
    clarify_or_abstain,
    post_run_validate,
    pre_run_validate,
)
from render.validate.layers import (
    layer1_schema,
    layer2_physics,
    layer3_regime,
    layer5_postrun,
)
from render.validate.stack import _merge

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_intent(**params) -> Intent:
    return Intent(
        mode="simulation_explicit",
        question="test",
        family="ode",
        engine="harmonic_oscillator",
        parameters=params,
        constraints=[],
    )


VALID_PARAMS = {"omega0": 1.0, "zeta": 0.0, "x0": 1.0, "v0": 0.0, "t_end": 10.0}


# ── Mock adapters ─────────────────────────────────────────────────────────────


class _PermissiveSchema(BaseModel):
    """Schema with no sign constraints — lets layer 2 be the gate."""

    omega0: float
    t_end: float


class _MinimalSchema(BaseModel):
    value: float = 1.0


class _NoSchemaAdapter:
    """Adapter that declares no intent schema (regime also absent)."""

    name: str = "no_schema"
    family: str = "ode"
    status: TrustStatus = "certified"
    runtime: ClassVar[str] = "local"
    environment: EnvSpec = EnvSpec(env_type="pip", packages=[])

    @property
    def intent_schema(self):
        return None

    @property
    def reference_cases(self):
        return []

    def validate(self, intent: Intent) -> ValidationReport:
        return ValidationReport(passed=True)

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name, params=intent.parameters)

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        return RawOutputs(engine=self.name, exit_code=0, stdout="", stderr="", files={})

    def parse(self, raw: RawOutputs) -> ResultBundle:
        return ResultBundle(engine=self.name, quantities=[], converged=True)


class _PhysicsTestAdapter:
    """Adapter whose schema allows any float for omega0 — tests layer 2 isolation."""

    name: str = "physics_test"
    family: str = "ode"
    status: TrustStatus = "certified"
    runtime: ClassVar[str] = "local"
    environment: EnvSpec = EnvSpec(env_type="pip", packages=[])

    @property
    def intent_schema(self):
        return _PermissiveSchema

    @property
    def reference_cases(self):
        return []

    def validate(self, intent: Intent) -> ValidationReport:
        return ValidationReport(passed=True)

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name, params=intent.parameters)

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        return RawOutputs(engine=self.name, exit_code=0, stdout="", stderr="", files={})

    def parse(self, raw: RawOutputs) -> ResultBundle:
        return ResultBundle(engine=self.name, quantities=[], converged=True)


class _ExperimentalAdapter:
    """Minimal experimental adapter for trust-label tests."""

    name: str = "mock_experimental"
    family: str = "ode"
    status: TrustStatus = "experimental"
    runtime: ClassVar[str] = "local"
    environment: EnvSpec = EnvSpec(env_type="pip", packages=[])

    @property
    def intent_schema(self):
        return _MinimalSchema

    @property
    def reference_cases(self):
        return []

    def validate(self, intent: Intent) -> ValidationReport:
        return ValidationReport(passed=True)

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name, params=intent.parameters)

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        return RawOutputs(engine=self.name, exit_code=0, stdout="", stderr="", files={})

    def parse(self, raw: RawOutputs) -> ResultBundle:
        return ResultBundle(engine=self.name, quantities=[], converged=True)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def harmonic() -> HarmonicOscillatorAdapter:
    return HarmonicOscillatorAdapter()


# ── check_regime ──────────────────────────────────────────────────────────────


def test_check_regime_in_range() -> None:
    spec = RegimeSpec(
        bounds=[RegimeBound(field="omega0", min_val=0.1, max_val=100.0, unit="rad/s")]
    )
    in_regime, msgs = check_regime({"omega0": 1.0}, spec)
    assert in_regime
    assert msgs == []


def test_check_regime_below_min() -> None:
    spec = RegimeSpec(bounds=[RegimeBound(field="omega0", min_val=1e-6, max_val=1e6, unit="rad/s")])
    in_regime, msgs = check_regime({"omega0": 1e-10}, spec)
    assert not in_regime
    assert len(msgs) == 1
    assert "omega0" in msgs[0]
    assert "below" in msgs[0]


def test_check_regime_above_max() -> None:
    spec = RegimeSpec(bounds=[RegimeBound(field="omega0", min_val=1e-6, max_val=1e6, unit="rad/s")])
    in_regime, msgs = check_regime({"omega0": 2e6}, spec)
    assert not in_regime
    assert len(msgs) == 1
    assert "exceeds" in msgs[0]


def test_check_regime_missing_field_skipped() -> None:
    spec = RegimeSpec(
        bounds=[RegimeBound(field="omega0", min_val=1.0, max_val=100.0, unit="rad/s")]
    )
    in_regime, msgs = check_regime({"t_end": 10.0}, spec)
    assert in_regime
    assert msgs == []


def test_check_regime_multiple_violations() -> None:
    spec = RegimeSpec(
        bounds=[
            RegimeBound(field="omega0", min_val=1.0, max_val=100.0, unit="rad/s"),
            RegimeBound(field="t_end", min_val=0.0, max_val=1000.0, unit="s"),
        ]
    )
    in_regime, msgs = check_regime({"omega0": 0.001, "t_end": 5000.0}, spec)
    assert not in_regime
    assert len(msgs) == 2


def test_check_regime_empty_spec() -> None:
    in_regime, msgs = check_regime({"omega0": 1.0}, RegimeSpec())
    assert in_regime
    assert msgs == []


def test_check_regime_only_max() -> None:
    spec = RegimeSpec(bounds=[RegimeBound(field="zeta", max_val=0.999)])
    in_regime, _ = check_regime({"zeta": 0.5}, spec)
    assert in_regime
    in_regime2, msgs2 = check_regime({"zeta": 1.5}, spec)
    assert not in_regime2
    assert "exceeds" in msgs2[0]


def test_check_regime_only_min() -> None:
    spec = RegimeSpec(bounds=[RegimeBound(field="omega0", min_val=0.1)])
    in_regime, _ = check_regime({"omega0": 1.0}, spec)
    assert in_regime
    in_regime2, _msgs2 = check_regime({"omega0": 0.01}, spec)
    assert not in_regime2


# ── layer1_schema ─────────────────────────────────────────────────────────────


def test_layer1_schema_valid(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent(**VALID_PARAMS)
    result = layer1_schema(harmonic, intent)
    assert result is None


def test_layer1_schema_missing_required(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent()
    result = layer1_schema(harmonic, intent)
    assert result is not None
    assert not result.passed
    assert result.failed_layer == 1
    assert len(result.errors) > 0


def test_layer1_schema_constraint_violation(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent(omega0=-1.0, zeta=0.0, x0=1.0, t_end=10.0)
    result = layer1_schema(harmonic, intent)
    assert result is not None
    assert not result.passed
    assert result.failed_layer == 1


def test_layer1_schema_zeta_out_of_range(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent(omega0=1.0, zeta=1.5, x0=1.0, t_end=10.0)
    result = layer1_schema(harmonic, intent)
    assert result is not None
    assert not result.passed
    assert result.failed_layer == 1


def test_layer1_no_schema() -> None:
    adapter = _NoSchemaAdapter()
    intent = _make_intent(**VALID_PARAMS)
    result = layer1_schema(adapter, intent)
    assert result is None


# ── layer2_physics ────────────────────────────────────────────────────────────


def test_layer2_physics_valid() -> None:
    intent = _make_intent(**VALID_PARAMS)
    result = layer2_physics(intent)
    assert result is None


def test_layer2_physics_omega0_zero() -> None:
    intent = _make_intent(omega0=0.0, zeta=0.0, x0=1.0, t_end=10.0)
    result = layer2_physics(intent)
    assert result is not None
    assert not result.passed
    assert result.failed_layer == 2
    assert any("omega0" in e for e in result.errors)


def test_layer2_physics_omega0_negative() -> None:
    intent = _make_intent(omega0=-2.0, zeta=0.0, x0=1.0, t_end=10.0)
    result = layer2_physics(intent)
    assert result is not None
    assert not result.passed
    assert result.failed_layer == 2


def test_layer2_physics_t_end_negative() -> None:
    intent = _make_intent(omega0=1.0, zeta=0.0, x0=1.0, t_end=-5.0)
    result = layer2_physics(intent)
    assert result is not None
    assert not result.passed
    assert result.failed_layer == 2
    assert any("t_end" in e for e in result.errors)


def test_layer2_physics_multiple_violations() -> None:
    intent = _make_intent(omega0=-1.0, zeta=0.0, x0=1.0, t_end=0.0)
    result = layer2_physics(intent)
    assert result is not None
    assert not result.passed
    assert len(result.errors) == 2


def test_layer2_physics_from_constraints() -> None:
    intent = Intent(
        mode="simulation_explicit",
        question="test",
        family="ode",
        engine="harmonic_oscillator",
        parameters={"zeta": 0.0, "x0": 1.0, "t_end": 10.0},
        constraints=[Constraint(name="omega0", value=-1.0, unit="rad/s")],
    )
    result = layer2_physics(intent)
    assert result is not None
    assert not result.passed
    assert result.failed_layer == 2


def test_layer2_physics_unknown_field_negative() -> None:
    intent = _make_intent(**VALID_PARAMS, my_custom_field=-5.0)
    result = layer2_physics(intent)
    assert result is None


# ── layer3_regime ─────────────────────────────────────────────────────────────


def test_layer3_regime_in_range(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent(**VALID_PARAMS)
    result = layer3_regime(harmonic, intent)
    assert result is None


def test_layer3_regime_out_of_range(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent(omega0=2e6, zeta=0.0, x0=1.0, t_end=10.0)
    result = layer3_regime(harmonic, intent)
    assert result is not None
    assert result.passed
    assert not result.in_regime
    assert result.confidence == 0.5
    assert len(result.warnings) > 0


def test_layer3_regime_no_regime_attr() -> None:
    adapter = _NoSchemaAdapter()
    intent = _make_intent(**VALID_PARAMS)
    result = layer3_regime(adapter, intent)
    assert result is None


def test_layer3_regime_t_end_out_of_range(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent(omega0=1.0, zeta=0.0, x0=1.0, t_end=2e4)
    result = layer3_regime(harmonic, intent)
    assert result is not None
    assert result.passed
    assert not result.in_regime


# ── layer5_postrun ────────────────────────────────────────────────────────────


def _make_bundle(quantities=None, converged=True) -> ResultBundle:
    if quantities is None:
        quantities = [Quantity(name="x_max", value=1.0, unit="m")]
    return ResultBundle(engine="harmonic_oscillator", quantities=quantities, converged=converged)


def test_layer5_clean_bundle() -> None:
    bundle = _make_bundle()
    result = layer5_postrun(bundle)
    assert result is None


def test_layer5_nan_quantity() -> None:
    bundle = _make_bundle(quantities=[Quantity(name="bad", value=float("nan"))])
    result = layer5_postrun(bundle)
    assert result is not None
    assert not result.passed
    assert result.failed_layer == 5
    assert any("NaN" in e for e in result.errors)


def test_layer5_inf_quantity() -> None:
    bundle = _make_bundle(quantities=[Quantity(name="bad", value=float("inf"))])
    result = layer5_postrun(bundle)
    assert result is not None
    assert not result.passed
    assert result.failed_layer == 5
    assert any("Inf" in e for e in result.errors)


def test_layer5_neg_inf_quantity() -> None:
    bundle = _make_bundle(quantities=[Quantity(name="bad", value=float("-inf"))])
    result = layer5_postrun(bundle)
    assert result is not None
    assert not result.passed
    assert result.failed_layer == 5


def test_layer5_not_converged() -> None:
    bundle = _make_bundle(converged=False)
    result = layer5_postrun(bundle)
    assert result is not None
    assert not result.passed
    assert result.failed_layer == 5
    assert any("non-convergence" in e for e in result.errors)


def test_layer5_large_value_warning() -> None:
    bundle = _make_bundle(quantities=[Quantity(name="big", value=2e30, unit="m")])
    result = layer5_postrun(bundle)
    assert result is not None
    assert result.passed
    assert len(result.warnings) > 0


def test_layer5_non_numeric_quantity_skipped() -> None:
    bundle = _make_bundle(quantities=[Quantity(name="label", value="converged")])
    result = layer5_postrun(bundle)
    assert result is None


# ── _merge ────────────────────────────────────────────────────────────────────


def test_merge_both_pass() -> None:
    a = ValidationReport(passed=True, warnings=["w1"])
    b = ValidationReport(passed=True, warnings=["w2"])
    m = _merge(a, b)
    assert m.passed
    assert "w1" in m.warnings
    assert "w2" in m.warnings


def test_merge_override_fails() -> None:
    base = ValidationReport(passed=True)
    override = ValidationReport(passed=False, failed_layer=2, errors=["bad"])
    m = _merge(base, override)
    assert not m.passed
    assert m.failed_layer == 2
    assert "bad" in m.errors


def test_merge_base_fails_override_passes() -> None:
    base = ValidationReport(passed=False, failed_layer=1, errors=["e1"])
    override = ValidationReport(passed=True, warnings=["w1"])
    m = _merge(base, override)
    assert not m.passed
    assert m.failed_layer == 1
    assert "e1" in m.errors
    assert "w1" in m.warnings


def test_merge_confidence_min() -> None:
    a = ValidationReport(passed=True, confidence=0.8)
    b = ValidationReport(passed=True, confidence=0.5)
    m = _merge(a, b)
    assert m.confidence == 0.5


def test_merge_in_regime_and() -> None:
    a = ValidationReport(passed=True, in_regime=True)
    b = ValidationReport(passed=True, in_regime=False)
    m = _merge(a, b)
    assert not m.in_regime


# ── pre_run_validate ──────────────────────────────────────────────────────────


def test_pre_run_validate_all_good(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent(**VALID_PARAMS)
    report = pre_run_validate(harmonic, intent)
    assert report.passed
    assert report.in_regime
    assert report.confidence == 1.0


def test_pre_run_validate_layer1_stops_pipeline(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent(omega0=-1.0, zeta=0.0, x0=1.0, t_end=10.0)
    report = pre_run_validate(harmonic, intent)
    assert not report.passed
    assert report.failed_layer == 1


def test_pre_run_validate_out_of_regime(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent(omega0=2e6, zeta=0.0, x0=1.0, t_end=10.0)
    report = pre_run_validate(harmonic, intent)
    assert report.passed
    assert not report.in_regime
    assert report.confidence < 1.0


def test_pre_run_validate_layer2_via_mock() -> None:
    adapter = _PhysicsTestAdapter()
    intent = Intent(
        mode="simulation_explicit",
        question="test",
        family="ode",
        engine="physics_test",
        parameters={"omega0": -1.0, "t_end": 1.0},
        constraints=[],
    )
    report = pre_run_validate(adapter, intent)
    assert not report.passed
    assert report.failed_layer == 2


def test_pre_run_validate_no_schema_adapter() -> None:
    adapter = _NoSchemaAdapter()
    intent = _make_intent(**VALID_PARAMS)
    report = pre_run_validate(adapter, intent)
    assert report.passed


# ── post_run_validate ─────────────────────────────────────────────────────────


def test_post_run_validate_clean() -> None:
    bundle = _make_bundle()
    report = post_run_validate(bundle)
    assert report.passed


def test_post_run_validate_nan_fails() -> None:
    bundle = _make_bundle(quantities=[Quantity(name="x", value=float("nan"))])
    report = post_run_validate(bundle)
    assert not report.passed
    assert report.failed_layer == 5


def test_post_run_validate_not_converged_fails() -> None:
    bundle = _make_bundle(converged=False)
    report = post_run_validate(bundle)
    assert not report.passed


# ── clarify_or_abstain ────────────────────────────────────────────────────────


def test_clarify_all_good(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent(**VALID_PARAMS)
    resp = clarify_or_abstain(harmonic, intent)
    assert resp.decision == ClarifyDecision.PROCEED
    assert resp.confidence == 1.0
    assert resp.engine_status == "certified"


def test_clarify_missing_required_fields(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent()
    resp = clarify_or_abstain(harmonic, intent)
    assert resp.decision == ClarifyDecision.CLARIFY
    assert len(resp.missing_fields) > 0
    assert "omega0" in resp.missing_fields or "x0" in resp.missing_fields


def test_clarify_schema_non_missing_error_abstains(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent(omega0=-1.0, zeta=0.0, x0=1.0, t_end=10.0)
    resp = clarify_or_abstain(harmonic, intent)
    assert resp.decision == ClarifyDecision.ABSTAIN
    assert "invalid" in resp.message.lower() or "invalid" in resp.message.lower()


def test_clarify_out_of_regime_proceeds_with_caveat(harmonic: HarmonicOscillatorAdapter) -> None:
    intent = _make_intent(omega0=2e6, zeta=0.0, x0=1.0, t_end=10.0)
    resp = clarify_or_abstain(harmonic, intent)
    assert resp.decision == ClarifyDecision.PROCEED
    assert resp.confidence < 1.0
    assert resp.validation is not None
    assert not resp.validation.in_regime
    assert "out" in resp.message.lower() or "regime" in resp.message.lower()


def test_clarify_experimental_engine_proceeds_with_label() -> None:
    adapter = _ExperimentalAdapter()
    intent = Intent(
        mode="simulation_explicit",
        question="test",
        family="ode",
        engine="mock_experimental",
        parameters={"value": 1.0},
        constraints=[],
    )
    resp = clarify_or_abstain(adapter, intent)
    assert resp.decision == ClarifyDecision.PROCEED
    assert resp.confidence == 0.6
    assert resp.engine_status == "experimental"
    assert "experimental" in resp.message.lower() or "EXPERIMENTAL" in resp.message


def test_clarify_physics_violation_abstains() -> None:
    adapter = _PhysicsTestAdapter()
    intent = Intent(
        mode="simulation_explicit",
        question="test",
        family="ode",
        engine="physics_test",
        parameters={"omega0": -1.0, "t_end": 1.0},
        constraints=[],
    )
    resp = clarify_or_abstain(adapter, intent)
    assert resp.decision == ClarifyDecision.ABSTAIN
    assert resp.validation is not None
    assert not resp.validation.passed


def test_clarify_harmonic_adapter_has_regime(harmonic: HarmonicOscillatorAdapter) -> None:
    assert hasattr(harmonic, "regime")
    assert isinstance(harmonic.regime, RegimeSpec)
    assert len(harmonic.regime.bounds) >= 3
