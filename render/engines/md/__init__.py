"""Molecular dynamics adapter — OpenMM.

Experimental until reference cases pass on a machine with OpenMM installed.
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


class MDIntent(BaseModel):
    system: str = Field(description="'tip3p_water_box', 'alanine_dipeptide', or 'argon_lj'")
    temperature: float = Field(default=300.0, gt=0, description="Temperature (K)")
    pressure: float = Field(default=1.0, gt=0, description="Pressure (bar)")
    n_steps: int = Field(default=10_000, ge=100, le=10_000_000)
    timestep_fs: float = Field(default=2.0, gt=0, description="Timestep (fs)")
    platform: str = Field(default="CPU")
    seed: int = Field(default=42)
    force_field: str = Field(default="amber14", description="Force field name")

class OpenMMAdapter:
    name: str = "openmm_md"; family: str = "md"; status: TrustStatus = "experimental"
    version: ClassVar[str] = "1.0.0"; runtime: ClassVar[str] = "either"
    environment: EnvSpec = EnvSpec(env_type="conda",packages=["openmm>=8.0"],
        module_name="openmm/8.0",notes="Available via conda: conda install -c conda-forge openmm")
    regime: RegimeSpec = RegimeSpec(bounds=[
        RegimeBound(field="temperature",min_val=1.0,max_val=1000.0,unit="K"),
        RegimeBound(field="pressure",min_val=0.1,max_val=10000.0,unit="bar"),
        RegimeBound(field="n_steps",min_val=100,max_val=100_000_000),
    ])
    @property
    def intent_schema(self): return MDIntent
    @property
    def reference_cases(self): return _REFERENCE_CASES
    def validate(self, intent: Intent) -> ValidationReport:
        s=intent.parameters.get("system","")
        if s not in ("tip3p_water_box","alanine_dipeptide","argon_lj"):
            return ValidationReport(passed=False,failed_layer=1,errors=[f"Unknown system '{s}'"])
        return ValidationReport(passed=True)
    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name,params=dict(intent.parameters),seed=intent.parameters.get("seed",42))
    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        try:
            import openmm  # noqa: F401
        except ImportError:
            raise ImportError("OpenMM not installed. Install via: conda install -c conda-forge openmm")
        p=inputs.params; s=p.get("system","argon_lj")
        T=float(p.get("temperature",300.0)); n=int(p.get("n_steps",10_000))
        dt=float(p.get("timestep_fs",2.0))
        # Placeholder: actual OpenMM simulation setup would go here
        # This structure is ready for completion on an HPC node with OpenMM
        result={"system":s,"temperature_K":T,"n_steps":n,"timestep_fs":dt,
                "status":"requires_openmm_installation",
                "mean_potential_energy_kJ_mol":None,"density_g_cm3":None}
        return RawOutputs(engine=self.name,exit_code=0,files={"summary.json":json.dumps(result)})
    def parse(self, raw: RawOutputs) -> ResultBundle:
        s=json.loads(raw.files["summary.json"])
        return ResultBundle(engine=self.name,quantities=[
            Quantity(name=k,value=v) for k,v in s.items() if isinstance(v,float)
        ],converged=True,metadata=s)

def _md_intent(system,T,n_steps,seed=42):
    return Intent(mode="simulation_explicit",question=f"MD {system} T={T}K",family="md",engine="openmm_md",
        parameters={"system":system,"temperature":T,"n_steps":n_steps,"seed":seed,"timestep_fs":2.0},
        constraints=[Constraint(name="system",value=system)])
_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(name="md_argon_density",engine="openmm_md",
        description="LJ argon at 85K: density ≈ 1.40 g/cm³ (experimental)",
        citation="Rahman (1964) Phys. Rev.; NIST",
        intent=_md_intent("argon_lj",85.0,50_000,42),
        tolerances=[ToleranceSpec(quantity_name="density_g_cm3",expected_value=1.40,rtol=0.05)]),
    ReferenceCase(name="md_water_density",engine="openmm_md",
        description="TIP3P water at 298K, 1bar: density ≈ 0.98 g/cm³",
        citation="Jorgensen et al. (1983) J. Chem. Phys.",
        intent=_md_intent("tip3p_water_box",298.0,100_000,42),
        tolerances=[ToleranceSpec(quantity_name="density_g_cm3",expected_value=0.98,rtol=0.03)]),
]
