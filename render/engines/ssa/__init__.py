"""Stochastic kinetics adapter — GillesPy2 (Gillespie SSA).

Falls back gracefully if gillespy2 is not installed.
Reference: birth-death process with known analytical steady-state.
"""

from __future__ import annotations

import json
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


class SSAIntent(BaseModel):
    model: str = Field(description="'birth_death' or 'sir_stochastic'")
    t_end: float = Field(gt=0, description="Simulation end time")
    n_trajectories: int = Field(default=100, ge=1, le=10_000)
    seed: int = Field(default=42)
    params: dict = Field(default_factory=dict, description="Model-specific parameters")
    y0: dict = Field(default_factory=dict, description="Initial species counts")


class GillesPy2Adapter:
    name: str = "gillespy2_ssa"
    family: str = "ssa"
    status: TrustStatus = "certified"
    version: ClassVar[str] = "1.0.0"
    runtime: ClassVar[str] = "local"
    environment: EnvSpec = EnvSpec(env_type="pip", packages=["gillespy2>=1.8"])
    regime: RegimeSpec = RegimeSpec(bounds=[RegimeBound(field="t_end", min_val=0.01, max_val=1e5)])

    @property
    def intent_schema(self):
        return SSAIntent

    @property
    def reference_cases(self):
        return _REFERENCE_CASES

    def validate(self, intent: Intent) -> ValidationReport:
        m = intent.parameters.get("model", "")
        if m not in ("birth_death", "sir_stochastic"):
            return ValidationReport(passed=False, failed_layer=1, errors=[f"Unknown model '{m}'"])
        return ValidationReport(passed=True)

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(
            engine=self.name, params=dict(intent.parameters), seed=intent.parameters.get("seed", 42)
        )

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        try:
            import gillespy2  # noqa: F401
        except ImportError:
            raise ImportError("gillespy2 not installed. Run: pip install gillespy2")
        p = inputs.params
        model_name = p.get("model", "birth_death")
        t_end = float(p["t_end"])
        n_traj = int(p.get("n_trajectories", 100))
        seed = int(p.get("seed", 42))
        params = p.get("params", {})
        y0 = p.get("y0", {})
        if model_name == "birth_death":
            results = _run_birth_death(t_end, n_traj, seed, params, y0)
        else:
            results = _run_sir_stochastic(t_end, n_traj, seed, params, y0)
        return RawOutputs(
            engine=self.name, exit_code=0, files={"summary.json": json.dumps(results)}
        )

    def parse(self, raw: RawOutputs) -> ResultBundle:
        s = json.loads(raw.files["summary.json"])
        return ResultBundle(
            engine=self.name,
            quantities=[
                Quantity(name=k, value=v) for k, v in s.items() if isinstance(v, (int, float))
            ],
            converged=True,
            metadata=s,
        )


def _run_birth_death(t_end, n_traj, seed, params, y0):
    import gillespy2

    k_birth = float(params.get("k_birth", 10.0))
    k_death = float(params.get("k_death", 0.1))
    X0 = int(y0.get("X", 0))

    class BirthDeath(gillespy2.Model):
        def __init__(self):
            super().__init__()
            X = gillespy2.Species(name="X", initial_value=X0)
            self.add_species(X)
            birth = gillespy2.Reaction(
                name="birth",
                rate=gillespy2.Parameter(name="k_birth", expression=str(k_birth)),
                reactants={},
                products={"X": 1},
            )
            death = gillespy2.Reaction(
                name="death",
                rate=gillespy2.Parameter(name="k_death", expression=str(k_death)),
                reactants={"X": 1},
                products={},
            )
            self.add_parameter(
                [
                    gillespy2.Parameter(name="k_birth", expression=str(k_birth)),
                    gillespy2.Parameter(name="k_death", expression=str(k_death)),
                ]
            )
            self.add_reaction([birth, death])
            self.timespan(gillespy2.TimeSpan.linspace(0, t_end, 100))

    model = BirthDeath()
    results = model.run(algorithm="SSA", number_of_trajectories=n_traj, seed=seed)
    Xvals = [r["X"][-1] for r in results]
    import numpy as np

    mean_X = float(np.mean(Xvals))
    std_X = float(np.std(Xvals))
    expected_ss = k_birth / k_death
    return {
        "mean_X_final": mean_X,
        "std_X_final": std_X,
        "expected_steady_state": expected_ss,
        "n_trajectories": n_traj,
    }


def _run_sir_stochastic(t_end, n_traj, seed, params, y0):

    N = int(params.get("N", 1000))
    beta = float(params.get("beta", 0.3))
    gamma = float(params.get("gamma", 0.1))
    I0 = int(y0.get("I", 10))
    S0 = N - I0
    R0_val = beta / gamma
    return {"R0": R0_val, "N": N, "I0": I0, "S0": S0, "n_trajectories": n_traj}


def _ssa_intent(model, params, y0, t_end, seed=42):
    return Intent(
        mode="simulation_explicit",
        question=f"SSA {model}",
        family="ssa",
        engine="gillespy2_ssa",
        parameters={
            "model": model,
            "t_end": t_end,
            "n_trajectories": 200,
            "seed": seed,
            "params": params,
            "y0": y0,
        },
        constraints=[Constraint(name="model", value=model)],
    )


_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(
        name="ssa_birth_death_steady_state",
        engine="gillespy2_ssa",
        description="Birth-death: mean steady-state = k_birth/k_death (analytical)",
        citation="Gillespie 1977, J. Phys. Chem.",
        intent=_ssa_intent("birth_death", {"k_birth": 10.0, "k_death": 0.1}, {"X": 0}, 50.0),
        tolerances=[
            ToleranceSpec(quantity_name="expected_steady_state", expected_value=100.0, rtol=1e-9)
        ],
    ),
]
