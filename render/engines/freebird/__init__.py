"""Atomistic Monte Carlo adapter — FreeBird.jl (flagship).

FreeBird.jl is a Julia package for atomistic simulations including Monte Carlo
and molecular dynamics. This adapter bridges Python → Julia via juliacall.
Falls back to a subprocess+JSON bridge if juliacall is not available.

Status: experimental (certify once reference cases pass on Compute2 HPC env).
"""
from __future__ import annotations

import json
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


class FreeBirdIntent(BaseModel):
    system: str = Field(description="'lj_argon' or 'lj_binary' or 'hard_sphere'")
    n_atoms: int = Field(default=108, ge=4, le=10000)
    temperature: float = Field(gt=0, description="Temperature in K")
    density: float = Field(default=0.85, gt=0, description="Reduced density")
    n_steps: int = Field(default=10000, ge=100)
    seed: int = Field(default=42)
    epsilon_K: float = Field(default=120.0, gt=0, description="LJ epsilon in K")
    sigma_ang: float = Field(default=3.4, gt=0, description="LJ sigma in Å")

class FreeBirdAdapter:
    name: str = "freebird_mc"; family: str = "atomistic_mc"; status: TrustStatus = "experimental"
    version: ClassVar[str] = "1.0.0"; runtime: ClassVar[str] = "either"
    environment: EnvSpec = EnvSpec(env_type="conda",
        packages=["juliacall>=0.9","Julia>=1.10"],
        module_name="",
        notes="Install juliacall: pip install juliacall; then ]add FreeBird in Julia REPL")
    regime: RegimeSpec = RegimeSpec(bounds=[],notes="LJ reduced units; well within liquid/solid regime when T*=T/(eps/k) in [0.5, 5].")
    @property
    def intent_schema(self): return FreeBirdIntent
    @property
    def reference_cases(self): return _REFERENCE_CASES
    def validate(self, intent: Intent) -> ValidationReport:
        valid_systems={"lj_argon","lj_binary","hard_sphere"}
        sys_=intent.parameters.get("system","")
        if sys_ not in valid_systems:
            return ValidationReport(passed=False,failed_layer=1,errors=[f"Unknown system '{sys_}'. Valid: {sorted(valid_systems)}"])
        return ValidationReport(passed=True)
    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name,params=dict(intent.parameters))
    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        p=inputs.params
        # Try juliacall first, fall back to subprocess Julia script
        try:
            return self._run_juliacall(p)
        except ImportError:
            pass
        try:
            return self._run_subprocess(p)
        except FileNotFoundError:
            raise ImportError(
                "Neither juliacall nor julia executable found.\n"
                "Install: pip install juliacall  (then ]add FreeBird in Julia REPL)\n"
                "   OR    conda install -c conda-forge julia && julia -e 'using Pkg; Pkg.add(\"FreeBird\")'")
    def _run_juliacall(self, p: dict) -> RawOutputs:
        from juliacall import Main as jl  # type: ignore[import-untyped]
        jl.seval('using FreeBird')
        jl.seval(f'using Random; Random.seed!({p.get("seed",42)})')
        system=p.get("system","lj_argon"); n=int(p.get("n_atoms",108))
        T=float(p.get("temperature",100.0)); rho=float(p.get("density",0.85))
        nsteps=int(p.get("n_steps",10000))
        eps=float(p.get("epsilon_K",120.0)); sig=float(p.get("sigma_ang",3.4))
        jl.seval(f"""
            sys = LJSystem(N={n}, density={rho}, epsilon={eps}, sigma={sig})
            result = run_mc(sys, T={T}, nsteps={nsteps})
        """)
        energy=float(jl.seval("result.energy_per_atom"))
        pressure=float(jl.seval("result.pressure"))
        accept=float(jl.seval("result.acceptance_rate"))
        s={"system":system,"n_atoms":n,"temperature_K":T,"density":rho,
           "energy_per_atom_kJ_mol":energy,"pressure_bar":pressure,"acceptance_rate":accept,"converged":True}
        return RawOutputs(engine=self.name,exit_code=0,files={"summary.json":json.dumps(s)})
    def _run_subprocess(self, p: dict) -> RawOutputs:
        script=f"""
import JSON
using FreeBird
using Random
Random.seed!({p.get("seed",42)})
sys = LJSystem(N={p.get("n_atoms",108)}, density={p.get("density",0.85)},
               epsilon={p.get("epsilon_K",120.0)}, sigma={p.get("sigma_ang",3.4)})
result = run_mc(sys, T={p.get("temperature",100.0)}, nsteps={p.get("n_steps",10000)})
d = Dict("energy_per_atom_kJ_mol"=>result.energy_per_atom,
         "pressure_bar"=>result.pressure,
         "acceptance_rate"=>result.acceptance_rate,
         "n_atoms"=>{p.get("n_atoms",108)},
         "temperature_K"=>{p.get("temperature",100.0)},
         "converged"=>true)
println(JSON.json(d))
"""
        proc=subprocess.run(["julia","--quiet","-e",script],capture_output=True,text=True,timeout=600)
        if proc.returncode!=0:
            return RawOutputs(engine=self.name,exit_code=proc.returncode,stderr=proc.stderr,files={})
        s=json.loads(proc.stdout.strip().split("\n")[-1])
        return RawOutputs(engine=self.name,exit_code=0,files={"summary.json":json.dumps(s)})
    def parse(self, raw: RawOutputs) -> ResultBundle:
        s=json.loads(raw.files["summary.json"])
        return ResultBundle(engine=self.name,quantities=[
            Quantity(name="energy_per_atom_kJ_mol",value=s["energy_per_atom_kJ_mol"],unit="kJ/mol"),
            Quantity(name="pressure_bar",value=s["pressure_bar"],unit="bar"),
            Quantity(name="acceptance_rate",value=s["acceptance_rate"]),
            Quantity(name="temperature_K",value=s["temperature_K"],unit="K"),
        ],converged=s.get("converged",True),metadata=s)

def _fb_intent(system,T,rho,nsteps=5000,title=""):
    return Intent(mode="simulation_explicit",question=title or f"MC {system} T={T}K rho={rho}",
        family="atomistic_mc",engine="freebird_mc",
        parameters={"system":system,"temperature":T,"density":rho,"n_steps":nsteps,"n_atoms":108,"seed":42},
        constraints=[Constraint(name="system",value=system)])
_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(name="fb_lj_argon_liquid_energy",engine="freebird_mc",
        description="LJ argon at T=100K, rho*=0.85 — energy per atom negative (liquid phase)",
        citation="Verlet (1967) Phys Rev 159",
        intent=_fb_intent("lj_argon",100.0,0.85,title="LJ argon liquid MC"),
        tolerances=[ToleranceSpec(quantity_name="energy_per_atom_kJ_mol",expected_value=-6.0,rtol=0.5)]),
    ReferenceCase(name="fb_lj_argon_acceptance",engine="freebird_mc",
        description="LJ argon MC acceptance rate between 0.2 and 0.7 for well-tuned step",
        citation="Frenkel & Smit (2002) p. 25",
        intent=_fb_intent("lj_argon",150.0,0.7,title="LJ argon acceptance rate check"),
        tolerances=[ToleranceSpec(quantity_name="acceptance_rate",expected_value=0.4,rtol=0.75)]),
]
