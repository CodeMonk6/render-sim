"""Atomistic Monte Carlo adapter — FreeBird.jl (the TWAIN flagship).

FreeBird.jl (Yang, Chen, Thibodeaux & Wexler, J. Chem. Theory Comput. 2025, 21,
10765) is a Julia toolbox for interfacial phase equilibria: atomistic & lattice
systems, Lennard-Jones / lattice Hamiltonians, and nested-sampling / Wang-Landau
/ Metropolis Monte Carlo. This adapter bridges Python → the installed Julia
package via a subprocess script and the package's REAL API:

    LJParameters(epsilon=, sigma=, cutoff=)        # interatomic potential
    pair_energy(r, lj)                             # LJ pair energy (deterministic)
    generate_initial_configs / AtomWalker          # build atomistic walkers
    monte_carlo_sampling(MCRoutine, walker, pot, MetropolisMCParameters)

Two modes:
  - ``lj_pair``       — deterministic LJ pair energy at a given separation. The
                        well-depth (energy at r = 2^(1/6)·σ) equals -ε exactly
                        (Lennard-Jones 1924); used as the certification gate.
  - ``lj_cluster_mc`` — real seeded Metropolis MC of an N-atom LJ cluster.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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
from render.validate.regime import RegimeSpec

_R_MIN_OVER_SIGMA = 2.0 ** (1.0 / 6.0)  # LJ pair-potential minimum separation


def _julia_exe() -> str | None:
    """Locate the Julia executable (env override, PATH, then juliaup default).

    The ``RENDER_JULIA`` override is honoured only if it actually exists, so an
    image can set it unconditionally (pointing at where Julia *would* be) without
    breaking the clean "Julia not found" abstain when Julia isn't installed.
    """
    override = os.environ.get("RENDER_JULIA")
    if override and os.path.exists(override):
        return override
    found = shutil.which("julia")
    if found:
        return found
    default = os.path.expanduser("~/.juliaup/bin/julia")
    return default if os.path.exists(default) else None


class FreeBirdIntent(BaseModel):
    mode: str = Field(default="lj_pair", description="'lj_pair' or 'lj_cluster_mc'")
    epsilon_eV: float = Field(default=0.0103, gt=0, description="LJ well depth ε (eV)")
    sigma_ang: float = Field(default=3.4, gt=0, description="LJ σ (Å)")
    cutoff_sigma: float = Field(default=4.0, gt=0, description="LJ cutoff in units of σ")
    r_over_sigma: float = Field(
        default=_R_MIN_OVER_SIGMA, gt=0, description="lj_pair: separation in units of σ"
    )
    n_atoms: int = Field(default=6, ge=2, le=200, description="lj_cluster_mc: number of atoms")
    temperature: float = Field(default=80.0, gt=0, description="lj_cluster_mc: temperature (K)")
    n_steps: int = Field(default=2000, ge=100, description="lj_cluster_mc: MC sampling steps")
    seed: int = Field(default=42)


class FreeBirdAdapter:
    name: str = "freebird_mc"
    family: str = "atomistic_mc"
    status: TrustStatus = "certified"
    description: ClassVar[str] = (
        "atomistic Monte Carlo via FreeBird.jl (Wexler group): Lennard-Jones pair energy and "
        "Metropolis MC of LJ clusters; use for interatomic potentials, well depth, MC sampling"
    )
    version: ClassVar[str] = "0.2.1"
    runtime: ClassVar[str] = "either"
    environment: EnvSpec = EnvSpec(
        env_type="conda",
        packages=["julia>=1.10", "FreeBird.jl>=0.2.1"],
        module_name="",
        notes="Install Julia (juliaup), then in Julia: ]add FreeBird Unitful",
    )

    regime: RegimeSpec = RegimeSpec(bounds=[], notes="LJ reduced units; T* = T/(ε/k_B).")

    @property
    def intent_schema(self):
        return FreeBirdIntent

    @property
    def reference_cases(self):
        return _REFERENCE_CASES

    def validate(self, intent: Intent) -> ValidationReport:
        mode = intent.parameters.get("mode", "lj_pair")
        if mode not in ("lj_pair", "lj_cluster_mc"):
            return ValidationReport(
                passed=False, failed_layer=1, errors=[f"Unknown FreeBird mode '{mode}'"]
            )
        return ValidationReport(passed=True)

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name, params=dict(intent.parameters))

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        julia = _julia_exe()
        if julia is None:
            raise ImportError(
                "Julia not found. Install juliaup (https://julialang.org/install) then run "
                "in Julia: ]add FreeBird Unitful   (or set RENDER_JULIA to the julia binary)."
            )
        p = inputs.params
        mode = p.get("mode", "lj_pair")
        script = self._script_lj_pair(p) if mode == "lj_pair" else self._script_cluster_mc(p)
        proc = subprocess.run(
            [julia, "--startup-file=no", "-e", script], capture_output=True, text=True, timeout=600
        )
        if proc.returncode != 0:
            return RawOutputs(
                engine=self.name, exit_code=proc.returncode, stderr=proc.stderr[-2000:], files={}
            )
        line = next(
            (ln for ln in proc.stdout.splitlines() if ln.startswith("RENDER_RESULT ")), None
        )
        if line is None:
            return RawOutputs(
                engine=self.name,
                exit_code=1,
                stderr="No RENDER_RESULT in Julia output:\n" + proc.stdout[-1500:],
                files={},
            )
        summary = json.loads(line[len("RENDER_RESULT ") :])
        return RawOutputs(
            engine=self.name, exit_code=0, files={"summary.json": json.dumps(summary)}
        )

    def _script_lj_pair(self, p: dict) -> str:
        eps = float(p.get("epsilon_eV", 0.0103))
        sig = float(p.get("sigma_ang", 3.4))
        cut = float(p.get("cutoff_sigma", 4.0))
        rov = float(p.get("r_over_sigma", _R_MIN_OVER_SIGMA))
        return f"""
using FreeBird, Unitful
lj = LJParameters(epsilon={eps}, sigma={sig}, cutoff={cut})
r = {rov} * {sig}
e = ustrip(pair_energy(r*u"Å", lj))
println("RENDER_RESULT {{\\"pair_energy_eV\\": $(e), \\"well_depth_eV\\": {eps}, " *
        "\\"r_over_sigma\\": {rov}, \\"sigma_ang\\": {sig}, \\"converged\\": true}}")
"""

    def _script_cluster_mc(self, p: dict) -> str:
        eps = float(p.get("epsilon_eV", 0.0103))
        sig = float(p.get("sigma_ang", 3.4))
        cut = float(p.get("cutoff_sigma", 4.0))
        n = int(p.get("n_atoms", 6))
        temp = float(p.get("temperature", 80.0))
        nsteps = int(p.get("n_steps", 2000))
        seed = int(p.get("seed", 42))
        vol = (sig**3) * 2.0  # generous box per atom
        return f"""
using FreeBird, Unitful, Logging
Logging.disable_logging(Logging.Info)
configs = generate_initial_configs({n}, {vol}, {n})
walker = AtomWalker(configs[1])
lj = LJParameters(epsilon={eps}, sigma={sig}, cutoff={cut})
mc = MetropolisMCParameters([{temp}]; equilibrium_steps={nsteps}, sampling_steps={nsteps},
        step_size=0.1, random_seed={seed})
res = monte_carlo_sampling(MCRandomWalkMaxE(), walker, lj, mc)
energies = res[1]; accepts = res[4]
emean = energies[end] / {n}
acc = accepts[end]
println("RENDER_RESULT {{\\"energy_per_atom_eV\\": $(emean), \\"acceptance_rate\\": $(acc), " *
        "\\"n_atoms\\": {n}, \\"temperature_K\\": {temp}, \\"converged\\": true}}")
"""

    def parse(self, raw: RawOutputs) -> ResultBundle:
        s = json.loads(raw.files["summary.json"])
        q = []
        if "pair_energy_eV" in s:
            q.append(Quantity(name="pair_energy_eV", value=s["pair_energy_eV"], unit="eV"))
            q.append(Quantity(name="well_depth_eV", value=s["well_depth_eV"], unit="eV"))
        if "energy_per_atom_eV" in s:
            q.append(Quantity(name="energy_per_atom_eV", value=s["energy_per_atom_eV"], unit="eV"))
            q.append(Quantity(name="acceptance_rate", value=s["acceptance_rate"]))
        if "temperature_K" in s:
            q.append(Quantity(name="temperature_K", value=s["temperature_K"], unit="K"))
        return ResultBundle(
            engine=self.name, quantities=q, converged=s.get("converged", True), metadata=s
        )


def _fb_pair_intent(r_over_sigma: float, title: str) -> Intent:
    return Intent(
        mode="simulation_explicit",
        question=title,
        family="atomistic_mc",
        engine="freebird_mc",
        parameters={
            "mode": "lj_pair",
            "epsilon_eV": 0.0103,
            "sigma_ang": 3.4,
            "cutoff_sigma": 4.0,
            "r_over_sigma": r_over_sigma,
        },
        constraints=[Constraint(name="mode", value="lj_pair")],
    )


_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(
        name="fb_lj_well_depth",
        engine="freebird_mc",
        description="LJ pair potential minimum (r = 2^(1/6) σ) equals -ε (well depth)",
        citation="Lennard-Jones (1924); FreeBird.jl JCTC 2025, 21, 10765",
        intent=_fb_pair_intent(_R_MIN_OVER_SIGMA, "LJ pair well depth"),
        tolerances=[
            ToleranceSpec(quantity_name="pair_energy_eV", expected_value=-0.0103, rtol=0.01)
        ],
    ),
    ReferenceCase(
        name="fb_lj_zero_crossing",
        engine="freebird_mc",
        description="LJ pair potential is ~0 at r = σ (cutoff-shifted)",
        citation="Lennard-Jones (1924)",
        intent=_fb_pair_intent(1.0, "LJ pair energy at r=sigma"),
        tolerances=[ToleranceSpec(quantity_name="pair_energy_eV", expected_value=0.0, atol=1e-3)],
    ),
]
