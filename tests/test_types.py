"""Tests for render.types — Phase 0.2 acceptance."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from render.types import (
    Constraint,
    EngineInputs,
    EnvSpec,
    Intent,
    Pathway,
    PathwayProposal,
    Quantity,
    RawOutputs,
    ReferenceCase,
    ResourceSpec,
    ResultBundle,
    RunManifest,
    ToleranceSpec,
    ValidationReport,
)

# ── EnvSpec ───────────────────────────────────────────────────────────────────


def test_envspec_pip():
    e = EnvSpec(env_type="pip", packages=["scipy>=1.13", "numpy"])
    assert e.env_type == "pip"
    assert "scipy>=1.13" in e.packages


def test_envspec_module():
    e = EnvSpec(env_type="module", module_name="lammps/23Aug2023")
    assert e.module_name == "lammps/23Aug2023"


def test_envspec_frozen():
    e = EnvSpec(env_type="pip")
    with pytest.raises(Exception):
        e.env_type = "conda"  # type: ignore[misc]


def test_envspec_round_trip():
    e = EnvSpec(env_type="conda", packages=["gromacs=2024.1"])
    assert EnvSpec.model_validate(e.model_dump()) == e


# ── ResourceSpec ──────────────────────────────────────────────────────────────


def test_resource_defaults():
    r = ResourceSpec()
    assert r.nodes == 1
    assert r.cores_per_node == 1
    assert r.memory_gb == 4.0
    assert r.walltime_hours == 1.0
    assert not r.gpu


def test_resource_hpc():
    r = ResourceSpec(nodes=4, cores_per_node=40, memory_gb=256, walltime_hours=8, gpu=True)
    assert r.nodes == 4


# ── Constraint ────────────────────────────────────────────────────────────────


def test_constraint_user():
    c = Constraint(name="temperature", value=300, unit="K")
    assert c.source == "user"


def test_constraint_default():
    c = Constraint(name="timestep", value=2e-15, unit="s", source="default")
    assert c.source == "default"


# ── Intent ────────────────────────────────────────────────────────────────────


def test_intent_simulation_explicit():
    intent = Intent(
        mode="simulation_explicit",
        question="Run LAMMPS for argon at 300 K with LJ potential",
        family="md",
        engine="lammps",
        parameters={"temperature": 300, "ensemble": "NVT"},
    )
    assert isinstance(intent.intent_id, UUID)
    assert intent.confidence == 1.0
    assert intent.engine == "lammps"


def test_intent_property_driven_no_engine():
    intent = Intent(
        mode="property_driven",
        question="What force field should I use to model liquid water at 300 K?",
        family="md",
    )
    assert intent.engine == ""
    assert intent.mode == "property_driven"


def test_intent_confidence_bounds():
    with pytest.raises(ValidationError):
        Intent(mode="simulation_explicit", question="q", family="md", confidence=1.5)
    with pytest.raises(ValidationError):
        Intent(mode="simulation_explicit", question="q", family="md", confidence=-0.1)


def test_intent_frozen():
    intent = Intent(mode="simulation_explicit", question="q", family="ode")
    with pytest.raises(Exception):
        intent.engine = "lammps"  # type: ignore[misc]


def test_intent_round_trip():
    intent = Intent(
        mode="simulation_explicit",
        question="Simulate argon",
        family="md",
        engine="lammps",
        constraints=[Constraint(name="T", value=300, unit="K")],
        defaults_applied=[Constraint(name="dt", value=2e-15, unit="s", source="default")],
        assumptions=["periodic boundary conditions"],
    )
    data = intent.model_dump()
    restored = Intent.model_validate(data)
    assert restored.intent_id == intent.intent_id
    assert restored.constraints[0].name == "T"
    assert restored.defaults_applied[0].source == "default"


# ── PathwayProposal ───────────────────────────────────────────────────────────


def test_pathway_proposal():
    prop = PathwayProposal(
        question="What method for water at 300 K?",
        pathways=[
            Pathway(
                engine="lammps",
                family="md",
                description="Classical MD with SPC/E water model",
                estimated_cost="minutes (local)",
                fidelity="medium",
                assumptions=["classical force field"],
                status="certified",
            ),
            Pathway(
                engine="pyscf",
                family="dft",
                description="DFT-MD (AIMD) with PBE functional",
                estimated_cost="hours (HPC, ~100 core-h)",
                fidelity="high",
                assumptions=["Born-Oppenheimer approximation"],
                status="certified",
            ),
        ],
        recommendation="lammps",
    )
    assert len(prop.pathways) == 2
    assert prop.recommendation == "lammps"


# ── ValidationReport ─────────────────────────────────────────────────────────


def test_validation_passed():
    v = ValidationReport(passed=True)
    assert v.passed
    assert v.failed_layer is None
    assert v.in_regime


def test_validation_failed_layer():
    v = ValidationReport(passed=False, failed_layer=3, errors=["out of regime"])
    assert v.failed_layer == 3
    assert "out of regime" in v.errors


def test_validation_bad_layer():
    with pytest.raises(ValidationError):
        ValidationReport(passed=False, failed_layer=8)
    with pytest.raises(ValidationError):
        ValidationReport(passed=False, failed_layer=0)


def test_validation_round_trip():
    v = ValidationReport(passed=True, warnings=["timestep is large"])
    assert ValidationReport.model_validate(v.model_dump()) == v


# ── EngineInputs / RawOutputs ─────────────────────────────────────────────────


def test_engine_inputs():
    inp = EngineInputs(
        engine="lammps",
        files={"in.lammps": "units real\n"},
        params={"T": 300},
        seed=42,
    )
    assert inp.seed == 42
    assert "in.lammps" in inp.files


def test_raw_outputs():
    out = RawOutputs(engine="lammps", exit_code=0, stdout="Run complete", wall_time_s=12.3)
    assert out.exit_code == 0
    assert out.wall_time_s == pytest.approx(12.3)


# ── ResultBundle ─────────────────────────────────────────────────────────────


def test_result_bundle_get():
    bundle = ResultBundle(
        engine="lammps",
        quantities=[
            Quantity(name="density", value=0.997, unit="g/cm^3"),
            Quantity(name="temperature", value=300.1, unit="K"),
        ],
    )
    q = bundle.get("density")
    assert q is not None
    assert q.value == pytest.approx(0.997)
    assert bundle.get("nonexistent") is None


def test_result_bundle_converged_default():
    bundle = ResultBundle(engine="pyscf")
    assert bundle.converged


def test_quantity_frozen():
    q = Quantity(name="E", value=-76.3, unit="Ha")
    with pytest.raises(Exception):
        q.value = -77.0  # type: ignore[misc]


# ── RunManifest ───────────────────────────────────────────────────────────────


def _make_manifest() -> RunManifest:
    intent = Intent(mode="simulation_explicit", question="q", family="md", engine="lammps")
    return RunManifest(
        timestamp=datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC),
        intent=intent,
        engine_name="lammps",
        engine_version="23Aug2023",
        engine_status="certified",
        environment=EnvSpec(env_type="module", module_name="lammps/23Aug2023"),
        inputs=EngineInputs(engine="lammps"),
        raw_outputs=RawOutputs(engine="lammps"),
        bundle=ResultBundle(engine="lammps"),
        validation=ValidationReport(passed=True),
        platform="compute2 / Linux / Python 3.11",
        seed=42,
    )


def test_run_manifest_creation():
    m = _make_manifest()
    assert isinstance(m.run_id, UUID)
    assert m.engine_status == "certified"
    assert m.seed == 42


def test_run_manifest_round_trip():
    m = _make_manifest()
    restored = RunManifest.model_validate(m.model_dump())
    assert restored.run_id == m.run_id
    assert restored.timestamp == m.timestamp
    assert restored.intent.intent_id == m.intent.intent_id


# ── ReferenceCase ─────────────────────────────────────────────────────────────


def test_reference_case():
    intent = Intent(
        mode="simulation_explicit",
        question="Compute density of SPC/E water at 300 K",
        family="md",
        engine="lammps",
        parameters={"T": 300, "ensemble": "NVT"},
    )
    rc = ReferenceCase(
        name="lammps_spce_water_density_300K",
        engine="lammps",
        description="SPC/E water density at 300 K matches experiment (0.997 g/cm³)",
        citation="doi:10.1021/j100308a038",
        intent=intent,
        tolerances=[ToleranceSpec(quantity_name="density", expected_value=0.997, rtol=0.01)],
    )
    assert rc.tolerances[0].rtol == pytest.approx(0.01)
    assert rc.tolerances[0].expected_value == pytest.approx(0.997)


def test_tolerance_spec_frozen():
    t = ToleranceSpec(quantity_name="density", expected_value=0.997)
    with pytest.raises(Exception):
        t.expected_value = 1.0  # type: ignore[misc]
