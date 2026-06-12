"""Built-in reference engine: damped harmonic oscillator (analytical solution).

Purpose: give the framework a Certified engine with exact known outputs so
every pipeline layer can be tested end-to-end without any external dependency.

Physics:
    x''(t) + 2ζω₀ x'(t) + ω₀² x(t) = 0

    Exact solution for underdamped case (ζ < 1):
        x(t) = A exp(-ζω₀t) cos(ωd t + φ)
        ωd = ω₀ sqrt(1 - ζ²)

With initial conditions x(0) = x0, x'(0) = v0:
    A cos(φ) = x0
    A( -ζω₀ cos(φ) - ωd sin(φ) ) = v0

Reference: any classical mechanics textbook (e.g. Taylor §5.4).
"""

from __future__ import annotations

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


class HarmonicIntent(BaseModel):
    """Parameters for the harmonic oscillator engine."""

    omega0: float = Field(gt=0, description="Natural frequency [rad/s]")
    zeta: float = Field(ge=0, lt=1, description="Damping ratio (underdamped only)")
    x0: float = Field(description="Initial displacement [m]")
    v0: float = Field(default=0.0, description="Initial velocity [m/s]")
    t_end: float = Field(gt=0, description="Simulation end time [s]")
    n_points: int = Field(default=200, ge=10, le=10_000)


class HarmonicOscillatorAdapter:
    """Certified built-in engine: damped harmonic oscillator (exact solution)."""

    name: str = "harmonic_oscillator"
    family: str = "ode"
    description: ClassVar[str] = (
        "exact damped/undamped simple harmonic oscillator (spring-mass, pendulum); "
        "use for any 'harmonic oscillator', natural frequency ω₀, damping ratio ζ question"
    )
    status: TrustStatus = "certified"
    runtime: ClassVar[str] = "local"
    environment: EnvSpec = EnvSpec(env_type="pip", packages=["scipy>=1.13"])
    regime: RegimeSpec = RegimeSpec(
        bounds=[
            RegimeBound(
                field="omega0",
                min_val=1e-6,
                max_val=1e6,
                unit="rad/s",
                description="Natural frequency",
            ),
            RegimeBound(
                field="zeta",
                min_val=0.0,
                max_val=0.999,
                unit="",
                description="Damping ratio (underdamped only)",
            ),
            RegimeBound(
                field="t_end",
                min_val=1e-9,
                max_val=1e4,
                unit="s",
                description="Simulation end time",
            ),
        ],
        notes="Underdamped harmonic oscillator (zeta < 1); exact analytical solution.",
    )

    @property
    def intent_schema(self) -> type[HarmonicIntent]:
        return HarmonicIntent

    @property
    def reference_cases(self) -> list[ReferenceCase]:
        return _REFERENCE_CASES

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self, intent: Intent) -> ValidationReport:
        errors: list[str] = []
        warnings: list[str] = []

        params = intent.parameters
        omega0 = params.get("omega0")
        zeta = params.get("zeta", 0.0)
        t_end = params.get("t_end")

        if omega0 is None or omega0 <= 0:
            errors.append("omega0 must be > 0")
        if zeta is None or not (0 <= zeta < 1):
            errors.append("zeta must be in [0, 1) for the underdamped regime")
        if t_end is None or t_end <= 0:
            errors.append("t_end must be > 0")

        if errors:
            return ValidationReport(passed=False, failed_layer=1, errors=errors)

        assert omega0 is not None and t_end is not None
        if t_end > 1000 / omega0:
            warnings.append(
                "t_end is very long relative to the natural period; "
                "numerical drift may accumulate even with the exact solution."
            )

        return ValidationReport(passed=True, warnings=warnings)

    # ── Input builder ─────────────────────────────────────────────────────────

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name, params=dict(intent.parameters))

    # ── Runner (exact analytical solution) ───────────────────────────────────

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        p = inputs.params
        omega0: float = p["omega0"]
        zeta: float = p.get("zeta", 0.0)
        x0: float = p.get("x0", 1.0)
        v0: float = p.get("v0", 0.0)
        t_end: float = p["t_end"]
        n: int = p.get("n_points", 200)

        omegad = omega0 * math.sqrt(1 - zeta**2)

        # Solve for amplitude and phase from initial conditions:
        # x(0) = A cos(phi) = x0
        # x'(0) = A(-zeta*omega0 cos(phi) - omegad sin(phi)) = v0
        # => tan(phi) = -(v0 + zeta*omega0*x0) / (omegad*x0)
        if abs(omegad * x0) < 1e-300 and abs(v0 + zeta * omega0 * x0) < 1e-300:
            phi = 0.0
            A = 0.0
        else:
            phi = math.atan2(-(v0 + zeta * omega0 * x0), omegad * x0)
            cos_phi = math.cos(phi)
            if abs(cos_phi) > 1e-12:
                A = x0 / cos_phi
            else:
                A = (v0 + zeta * omega0 * x0) / (-omegad * math.sin(phi))

        dt = t_end / (n - 1)
        t_vals = [i * dt for i in range(n)]
        x_vals = [A * math.exp(-zeta * omega0 * t) * math.cos(omegad * t + phi) for t in t_vals]

        # Summary statistics
        x_max = max(abs(x) for x in x_vals)
        period = (2 * math.pi / omegad) if omegad > 0 else float("inf")

        lines = [f"{t:.6e} {x:.10e}" for t, x in zip(t_vals, x_vals)]
        stdout = "\n".join(lines)

        import json

        # Downsampled trajectory for plotting (cap ~200 points).
        step = max(1, len(t_vals) // 200)
        series = {
            "title": "Displacement vs time",
            "x": {"name": "time", "unit": "s", "values": [round(t, 5) for t in t_vals[::step]]},
            "y": [{"name": "x(t)", "unit": "m", "values": [round(x, 6) for x in x_vals[::step]]}],
        }

        summary = json.dumps(
            {
                "omega0": omega0,
                "zeta": zeta,
                "omegad": omegad,
                "period_d": period,
                "x_max": x_max,
                "x0": x0,
                "v0": v0,
                "A": A,
                "phi": phi,
                "series": series,
            }
        )

        return RawOutputs(
            engine=self.name,
            exit_code=0,
            stdout=stdout,
            files={"summary.json": summary},
            wall_time_s=0.0,
        )

    # ── Parser ────────────────────────────────────────────────────────────────

    def parse(self, raw: RawOutputs) -> ResultBundle:
        import json

        summary = json.loads(raw.files["summary.json"])
        quantities = [
            Quantity(name="omega0", value=summary["omega0"], unit="rad/s"),
            Quantity(name="omegad", value=summary["omegad"], unit="rad/s"),
            Quantity(name="period", value=summary["period_d"], unit="s"),
            Quantity(name="x_max", value=summary["x_max"], unit="m"),
            Quantity(name="zeta", value=summary["zeta"], unit=""),
            Quantity(name="amplitude", value=summary["A"], unit="m"),
        ]
        meta = {"series": summary["series"]} if "series" in summary else {}
        return ResultBundle(engine=self.name, quantities=quantities, converged=True, metadata=meta)


# ── Reference cases ───────────────────────────────────────────────────────────


def _make_reference_intent(omega0: float, zeta: float, x0: float, t_end: float) -> Intent:
    return Intent(
        mode="simulation_explicit",
        question=f"Harmonic oscillator: omega0={omega0}, zeta={zeta}, x0={x0}",
        family="ode",
        engine="harmonic_oscillator",
        parameters={"omega0": omega0, "zeta": zeta, "x0": x0, "v0": 0.0, "t_end": t_end},
        constraints=[
            Constraint(name="omega0", value=omega0, unit="rad/s"),
            Constraint(name="zeta", value=zeta),
        ],
    )


_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(
        name="harmonic_undamped_period",
        engine="harmonic_oscillator",
        description="Undamped oscillator: period = 2pi/omega0 exactly",
        citation="Taylor Classical Mechanics 5th ed., §5.2",
        intent=_make_reference_intent(omega0=1.0, zeta=0.0, x0=1.0, t_end=10.0),
        tolerances=[
            ToleranceSpec(
                quantity_name="period",
                expected_value=2 * math.pi,
                rtol=1e-9,
            ),
            ToleranceSpec(
                quantity_name="x_max",
                expected_value=1.0,
                rtol=1e-9,
            ),
        ],
    ),
    ReferenceCase(
        name="harmonic_underdamped_decay",
        engine="harmonic_oscillator",
        description="Underdamped: damped natural frequency ωd = ω0√(1-ζ²)",
        citation="Taylor Classical Mechanics 5th ed., §5.4",
        intent=_make_reference_intent(omega0=2.0, zeta=0.3, x0=1.0, t_end=5.0),
        tolerances=[
            ToleranceSpec(
                quantity_name="omegad",
                expected_value=2.0 * math.sqrt(1 - 0.3**2),
                rtol=1e-9,
            ),
        ],
    ),
]
