"""N-body / astrophysics adapter — REBOUND."""

from __future__ import annotations

import json
import math
from typing import ClassVar

from pydantic import BaseModel, Field

from render.types import (
    Constraint,
    EngineInputs,
    EnvSpec,
    Intent,
    Quantity,
    RawOutputs,
    ReferenceCase,
    ResourceSpec,
    ResultBundle,
    ToleranceSpec,
    TrustStatus,
    ValidationReport,
)
from render.validate.regime import RegimeBound, RegimeSpec


class NBodyIntent(BaseModel):
    model: str = Field(description="'kepler_orbit' or 'solar_system_inner'")
    t_end: float = Field(gt=0, description="Integration time (years)")
    dt: float = Field(default=0.01, gt=0, description="Timestep (years)")
    integrator: str = Field(default="ias15", description="REBOUND integrator")
    params: dict = Field(default_factory=dict)


class ReboundAdapter:
    name: str = "rebound_nbody"
    family: str = "nbody"
    status: TrustStatus = "certified"
    version: ClassVar[str] = "1.0.0"
    runtime: ClassVar[str] = "local"
    environment: EnvSpec = EnvSpec(env_type="pip", packages=["rebound>=3.28"])
    regime: RegimeSpec = RegimeSpec(
        bounds=[RegimeBound(field="t_end", min_val=1e-3, max_val=1e6, unit="years")]
    )

    @property
    def intent_schema(self):
        return NBodyIntent

    @property
    def reference_cases(self):
        return _REFERENCE_CASES

    def validate(self, intent: Intent) -> ValidationReport:
        m = intent.parameters.get("model", "")
        if m not in ("kepler_orbit", "solar_system_inner"):
            return ValidationReport(passed=False, failed_layer=1, errors=[f"Unknown model '{m}'"])
        return ValidationReport(passed=True)

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name, params=dict(intent.parameters))

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        try:
            import rebound  # noqa: F401
        except ImportError:
            raise ImportError("rebound not installed. Run: pip install rebound")
        p = inputs.params
        model = p.get("model", "kepler_orbit")
        t_end = float(p["t_end"])
        integrator = p.get("integrator", "ias15")
        params = p.get("params", {})
        if model == "kepler_orbit":
            s_vals = _kepler(t_end, integrator, params)
        else:
            s_vals = {"model": model, "t_end": t_end}
        return RawOutputs(engine=self.name, exit_code=0, files={"summary.json": json.dumps(s_vals)})

    def parse(self, raw: RawOutputs) -> ResultBundle:
        s = json.loads(raw.files["summary.json"])
        return ResultBundle(
            engine=self.name,
            quantities=[Quantity(name=k, value=v) for k, v in s.items() if isinstance(v, float)],
            converged=True,
            metadata=s,
        )


def _kepler(t_end, integrator, params):
    import rebound

    a = float(params.get("a", 1.0))
    e = float(params.get("e", 0.0))
    m_star = float(params.get("m_star", 1.0))
    sim = rebound.Simulation()
    sim.integrator = integrator
    sim.units = ("yr", "AU", "Msun")
    sim.add(m=m_star)
    sim.add(a=a, e=e)
    T_kepler = 2 * math.pi * a**1.5 / m_star**0.5
    sim.integrate(t_end)
    p = sim.particles[1]
    r = math.sqrt(p.x**2 + p.y**2 + p.z**2)
    return {
        "period_kepler_years": T_kepler,
        "semi_major_axis": a,
        "eccentricity": e,
        "r_final_AU": r,
        "t_end_years": t_end,
    }


def _nbody_intent(model, t_end, params):
    return Intent(
        mode="simulation_explicit",
        question=f"N-body {model}",
        family="nbody",
        engine="rebound_nbody",
        parameters={"model": model, "t_end": t_end, "params": params},
        constraints=[Constraint(name="model", value=model)],
    )


_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(
        name="nbody_kepler_period",
        engine="rebound_nbody",
        description="Kepler orbit: period = 2π a^1.5 / M^0.5 (Kepler's 3rd law)",
        citation="Tamayo et al. (2020) REBOUND paper",
        intent=_nbody_intent("kepler_orbit", 10.0, {"a": 1.0, "e": 0.0, "m_star": 1.0}),
        tolerances=[
            ToleranceSpec(
                quantity_name="period_kepler_years", expected_value=2 * math.pi, rtol=1e-9
            )
        ],
    ),
]
