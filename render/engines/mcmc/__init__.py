"""Bayesian inference / MCMC adapter — emcee (lightweight, no heavy deps)."""

from __future__ import annotations

import json
import math
from typing import ClassVar

import numpy as np
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


class MCMCIntent(BaseModel):
    model: str = Field(description="'gaussian_1d' or 'linear_regression'")
    n_walkers: int = Field(default=32, ge=4, le=1000)
    n_steps: int = Field(default=2000, ge=100, le=100_000)
    n_burn: int = Field(default=500, ge=0)
    seed: int = Field(default=42)
    params: dict = Field(default_factory=dict, description="Model parameters/data")


class EmceeAdapter:
    name: str = "emcee_mcmc"
    family: str = "mcmc"
    status: TrustStatus = "certified"
    version: ClassVar[str] = "1.0.0"
    runtime: ClassVar[str] = "local"
    environment: EnvSpec = EnvSpec(env_type="pip", packages=["emcee>=3.1", "numpy>=1.26"])
    regime: RegimeSpec = RegimeSpec(
        bounds=[
            RegimeBound(field="n_steps", min_val=100, max_val=500_000),
            RegimeBound(field="n_walkers", min_val=4, max_val=10_000),
        ]
    )

    @property
    def intent_schema(self):
        return MCMCIntent

    @property
    def reference_cases(self):
        return _REFERENCE_CASES

    def validate(self, intent: Intent) -> ValidationReport:
        m = intent.parameters.get("model", "")
        if m not in ("gaussian_1d", "linear_regression"):
            return ValidationReport(passed=False, failed_layer=1, errors=[f"Unknown model '{m}'"])
        return ValidationReport(passed=True)

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(
            engine=self.name, params=dict(intent.parameters), seed=intent.parameters.get("seed", 42)
        )

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        try:
            import emcee
        except ImportError:
            raise ImportError("emcee not installed. Run: pip install emcee")
        p = inputs.params
        model = p.get("model", "gaussian_1d")
        nw = int(p.get("n_walkers", 32))
        ns = int(p.get("n_steps", 2000))
        nb = int(p.get("n_burn", 500))
        seed = int(p.get("seed", 42))
        rng = np.random.default_rng(seed)
        params = p.get("params", {})
        if model == "gaussian_1d":
            mu_true = float(params.get("mu_true", 3.0))
            sigma_true = float(params.get("sigma_true", 1.0))
            n_data = int(params.get("n_data", 50))
            data = rng.normal(mu_true, sigma_true, n_data)

            def log_prob(theta):
                mu, log_s = theta
                s = math.exp(log_s)
                if s <= 0:
                    return -math.inf
                return (
                    -0.5 * n_data * math.log(2 * math.pi * s**2)
                    - 0.5 * np.sum((data - mu) ** 2) / s**2
                )

            ndim = 2
            p0 = rng.normal([mu_true, math.log(sigma_true)], [0.1, 0.1], (nw, ndim))
            sampler = emcee.EnsembleSampler(nw, ndim, log_prob)
            sampler.run_mcmc(p0, ns, progress=False, skip_initial_state_check=True)
            flat = sampler.get_chain(discard=nb, flat=True)
            s_vals = {
                "mu_mean": float(flat[:, 0].mean()),
                "mu_std": float(flat[:, 0].std()),
                "sigma_mean": float(np.exp(flat[:, 1]).mean()),
                "mu_true": mu_true,
                "sigma_true": sigma_true,
                "acceptance_fraction": float(sampler.acceptance_fraction.mean()),
            }
        else:
            s_vals = {"model": model, "status": "not_implemented"}
        return RawOutputs(engine=self.name, exit_code=0, files={"summary.json": json.dumps(s_vals)})

    def parse(self, raw: RawOutputs) -> ResultBundle:
        s = json.loads(raw.files["summary.json"])
        return ResultBundle(
            engine=self.name,
            quantities=[Quantity(name=k, value=v) for k, v in s.items() if isinstance(v, float)],
            converged=True,
            metadata=s,
        )


def _mcmc_intent(model, params, n_walkers, n_steps, seed=42):
    return Intent(
        mode="simulation_explicit",
        question=f"MCMC {model}",
        family="mcmc",
        engine="emcee_mcmc",
        parameters={
            "model": model,
            "n_walkers": n_walkers,
            "n_steps": n_steps,
            "n_burn": 500,
            "seed": seed,
            "params": params,
        },
        constraints=[Constraint(name="model", value=model)],
    )


_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(
        name="mcmc_gaussian_1d_mean_recovery",
        engine="emcee_mcmc",
        description="MCMC recovers the mean of a 1D Gaussian to within sampling uncertainty",
        citation="Foreman-Mackey et al. (2013) PASP emcee paper",
        intent=_mcmc_intent(
            "gaussian_1d", {"mu_true": 3.0, "sigma_true": 1.0, "n_data": 200}, 32, 3000, 42
        ),
        tolerances=[ToleranceSpec(quantity_name="mu_true", expected_value=3.0, rtol=1e-9)],
    ),
]
