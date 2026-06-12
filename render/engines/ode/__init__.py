"""ODE / Dynamical Systems adapter — SciPy solve_ivp.

Certified: reproduces standard textbook solutions for simple ODE systems.
"""

from __future__ import annotations

import json
import math
from typing import ClassVar

import numpy as np
from pydantic import BaseModel, Field
from scipy.integrate import solve_ivp  # type: ignore[import-untyped]

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


class ODEIntent(BaseModel):
    """Parameters for generic ODE integration via SciPy solve_ivp."""

    system: str = Field(
        description="ODE system name or 'custom'. Built-in: 'exponential_decay', "
        "'lotka_volterra', 'van_der_pol', 'sir'.",
    )
    t_end: float = Field(gt=0, description="Integration end time")
    t_start: float = Field(default=0.0, description="Integration start time")
    n_points: int = Field(default=200, ge=2, le=10_000)
    method: str = Field(default="RK45", description="Scipy solve_ivp method")
    rtol: float = Field(default=1e-6, gt=0)
    atol: float = Field(default=1e-9, gt=0)
    params: dict[str, float] = Field(
        default_factory=dict,
        description="System-specific parameters (e.g. {'k': 0.5} for decay)",
    )
    y0: list[float] = Field(
        default_factory=list,
        description="Initial conditions vector; if omitted a standard default for the "
        "chosen system is used.",
    )


# Built-in ODE systems
def _exponential_decay(t: float, y: list[float], k: float = 1.0) -> list[float]:
    return [-k * y[0]]


def _lotka_volterra(
    t: float, y: list[float], alpha: float = 1.0, beta: float = 0.1,
    delta: float = 0.075, gamma: float = 1.5
) -> list[float]:
    x, p = y
    return [alpha * x - beta * x * p, delta * x * p - gamma * p]


def _van_der_pol(t: float, y: list[float], mu: float = 1.0) -> list[float]:
    return [y[1], mu * (1 - y[0] ** 2) * y[1] - y[0]]


def _sir(
    t: float, y: list[float], beta: float = 0.3, gamma: float = 0.1
) -> list[float]:
    S, I, R = y
    N = S + I + R
    return [-beta * S * I / N, beta * S * I / N - gamma * I, gamma * I]


_SYSTEMS = {
    "exponential_decay": _exponential_decay,
    "lotka_volterra": _lotka_volterra,
    "van_der_pol": _van_der_pol,
    "sir": _sir,
}

# Friendly state-variable labels per system for plot legends.
_STATE_LABELS = {
    "exponential_decay": ["y"],
    "lotka_volterra": ["prey", "predator"],
    "van_der_pol": ["x", "x'"],
    "sir": ["S", "I", "R"],
}

# Standard initial conditions used when the user doesn't state y0.
_DEFAULT_Y0 = {
    "exponential_decay": [1.0],
    "lotka_volterra": [10.0, 5.0],
    "van_der_pol": [1.0, 0.0],
    "sir": [999.0, 1.0, 0.0],
}


class SciPyODEAdapter:
    """Certified ODE adapter: SciPy solve_ivp."""

    name: str = "scipy_ode"
    family: str = "ode"
    description: ClassVar[str] = (
        "generic ODE integration for these systems ONLY: exponential_decay, "
        "lotka_volterra (predator-prey), van_der_pol, sir. Not for harmonic oscillators."
    )
    status: TrustStatus = "certified"
    version: ClassVar[str] = "1.0.0"
    runtime: ClassVar[str] = "local"
    environment: EnvSpec = EnvSpec(env_type="pip", packages=["scipy>=1.13", "numpy>=1.26"])
    regime: RegimeSpec = RegimeSpec(
        bounds=[
            RegimeBound(field="t_end", min_val=1e-9, max_val=1e6, unit="s"),
        ],
        notes="Generic ODE integration; system-specific regimes not encoded here.",
    )

    @property
    def intent_schema(self) -> type[ODEIntent]:
        return ODEIntent

    @property
    def reference_cases(self) -> list[ReferenceCase]:
        return _REFERENCE_CASES

    def validate(self, intent: Intent) -> ValidationReport:
        p = intent.parameters
        system = p.get("system", "")
        if system not in _SYSTEMS and system != "custom":
            return ValidationReport(
                passed=False,
                failed_layer=1,
                errors=[f"Unknown ODE system '{system}'. Choose from: {list(_SYSTEMS)}"],
            )
        return ValidationReport(passed=True)

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name, params=dict(intent.parameters))

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        p = inputs.params
        system_name: str = p.get("system", "exponential_decay")
        t_end: float = p["t_end"]
        t_start: float = p.get("t_start", 0.0)
        n_points: int = int(p.get("n_points", 200))
        method: str = p.get("method", "RK45")
        rtol: float = float(p.get("rtol", 1e-6))
        atol: float = float(p.get("atol", 1e-9))
        params: dict[str, float] = p.get("params", {})
        y0: list[float] = p.get("y0") or _DEFAULT_Y0.get(system_name, [1.0])

        sys_fn = _SYSTEMS.get(system_name)
        if sys_fn is None:
            raise ValueError(f"Unknown system: {system_name}")

        # Only pass parameters the chosen system actually accepts — the NL layer
        # may extract extra/foreign keys, and an unexpected kwarg would otherwise
        # crash the integration.  Dropped keys are recorded for transparency.
        import inspect
        accepted = set(inspect.signature(sys_fn).parameters) - {"t", "y"}
        used = {k: v for k, v in params.items() if k in accepted}
        ignored = sorted(set(params) - accepted)

        t_eval = np.linspace(t_start, t_end, n_points)
        sol = solve_ivp(
            lambda t, y: sys_fn(t, y, **used),
            [t_start, t_end],
            y0,
            method=method,
            t_eval=t_eval,
            rtol=rtol,
            atol=atol,
            dense_output=False,
        )

        # Downsampled trajectory for plotting (cap ~200 points).
        labels = _STATE_LABELS.get(system_name) or [f"y{j}" for j in range(sol.y.shape[0])]
        step = max(1, len(sol.t) // 200)
        series = {
            "title": f"{system_name} trajectory",
            "x": {"name": "time", "unit": "", "values": [round(float(t), 5) for t in sol.t[::step]]},
            "y": [{"name": labels[j] if j < len(labels) else f"y{j}",
                   "values": [round(float(v), 6) for v in sol.y[j][::step]]}
                  for j in range(sol.y.shape[0])],
        }

        summary = {
            "system": system_name,
            "success": bool(sol.success),
            "t_end": float(sol.t[-1]),
            "y_final": sol.y[:, -1].tolist(),
            "y_max": sol.y.max(axis=1).tolist(),
            "y_min": sol.y.min(axis=1).tolist(),
            "nfev": int(sol.nfev),
            "ignored_params": ignored,
            "series": series,
        }
        # Store trajectory as CSV-like text in stdout
        rows = ["\t".join([str(sol.t[i])] + [str(sol.y[j, i]) for j in range(sol.y.shape[0])])
                for i in range(len(sol.t))]
        return RawOutputs(
            engine=self.name,
            exit_code=0 if sol.success else 1,
            stdout="\n".join(rows),
            files={"summary.json": json.dumps(summary)},
        )

    def parse(self, raw: RawOutputs) -> ResultBundle:
        summary = json.loads(raw.files["summary.json"])
        quantities = [
            Quantity(name="t_end", value=summary["t_end"], unit="s"),
            Quantity(name="success", value=summary["success"]),
            Quantity(name="nfev", value=summary["nfev"]),
        ]
        for i, yf in enumerate(summary["y_final"]):
            quantities.append(Quantity(name=f"y{i}_final", value=yf))
        for i, ym in enumerate(summary["y_max"]):
            quantities.append(Quantity(name=f"y{i}_max", value=ym))
        return ResultBundle(
            engine=self.name,
            quantities=quantities,
            converged=summary["success"],
            metadata=summary,
        )


# Reference cases

def _ode_intent(system: str, y0: list[float], t_end: float, params: dict) -> Intent:
    return Intent(
        mode="simulation_explicit",
        question=f"Integrate {system} ODE",
        family="ode",
        engine="scipy_ode",
        parameters={
            "system": system, "y0": y0, "t_end": t_end,
            "params": params, "n_points": 500,
        },
        constraints=[Constraint(name="system", value=system)],
    )


_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(
        name="ode_exponential_decay",
        engine="scipy_ode",
        description="y' = -k*y, y(0)=1 → y(T) = exp(-k*T)",
        citation="Any ODE textbook",
        intent=_ode_intent("exponential_decay", [1.0], 2.0, {"k": 1.0}),
        tolerances=[
            ToleranceSpec(
                quantity_name="y0_final",
                expected_value=math.exp(-2.0),
                rtol=1e-5,
            ),
        ],
    ),
    ReferenceCase(
        name="ode_exponential_decay_conservation",
        engine="scipy_ode",
        description="Exponential decay max value = initial value = 1.0",
        citation="Any ODE textbook",
        intent=_ode_intent("exponential_decay", [1.0], 5.0, {"k": 0.5}),
        tolerances=[
            ToleranceSpec(quantity_name="y0_max", expected_value=1.0, rtol=1e-6),
        ],
    ),
]
