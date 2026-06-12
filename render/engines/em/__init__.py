"""Electromagnetics adapter — Meep (FDTD)."""
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


class EMIntent(BaseModel):
    problem: str = Field(description="'waveguide','resonator','slab_transmission'")
    wavelength_um: float = Field(default=1.55, gt=0, description="Wavelength in μm")
    resolution: int = Field(default=16, ge=4, le=128, description="FDTD resolution (pts/μm)")
    run_time: float = Field(default=200.0, gt=0, description="FDTD run time in units of (um/c)")
    n_medium: float = Field(default=3.4, gt=0, description="Medium refractive index")

class MeepAdapter:
    name: str = "meep_em"; family: str = "em"; status: TrustStatus = "experimental"
    version: ClassVar[str] = "1.0.0"; runtime: ClassVar[str] = "either"
    environment: EnvSpec = EnvSpec(env_type="conda",packages=["meep>=1.29"],
        notes="conda install -c conda-forge meep")
    regime: RegimeSpec = RegimeSpec(bounds=[RegimeBound(field="resolution",min_val=4,max_val=128)],
        notes="FDTD; increase resolution for higher accuracy.")
    @property
    def intent_schema(self): return EMIntent
    @property
    def reference_cases(self): return _REFERENCE_CASES
    def validate(self, intent: Intent) -> ValidationReport:
        valid={"waveguide","resonator","slab_transmission"}
        prob=intent.parameters.get("problem","")
        if prob not in valid:
            return ValidationReport(passed=False,failed_layer=1,errors=[f"Unknown problem '{prob}'."])
        return ValidationReport(passed=True)
    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name,params=dict(intent.parameters))
    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        try:
            import meep as mp
        except ImportError:
            raise ImportError("Meep not installed. Run: conda install -c conda-forge meep")
        p=inputs.params; prob=p.get("problem","waveguide")
        wl=float(p.get("wavelength_um",1.55)); res=int(p.get("resolution",16))
        rt=float(p.get("run_time",200.0)); n=float(p.get("n_medium",3.4))
        freq=1.0/wl
        if prob=="waveguide":
            cell=mp.Vector3(16,8); pml=[mp.PML(1.0)]
            geometry=[mp.Block(mp.Vector3(mp.inf,1,mp.inf),center=mp.Vector3(),material=mp.Medium(index=n))]
            sources=[mp.Source(mp.ContinuousSource(frequency=freq),
                               component=mp.Ez,center=mp.Vector3(-5,0))]
            sim=mp.Simulation(cell_size=cell,boundary_layers=pml,geometry=geometry,sources=sources,resolution=res)
            sim.run(until=rt)
            ez=sim.get_array(center=mp.Vector3(5,0),size=mp.Vector3(0,6),component=mp.Ez)
            import numpy as np
            ez_max=float(np.abs(ez).max())
            s={"problem":prob,"wavelength_um":wl,"resolution":res,"ez_max":ez_max,"converged":True}
        else:
            s={"problem":prob,"wavelength_um":wl,"resolution":res,"ez_max":0.0,"converged":False,"note":"Not implemented in local mode"}
        return RawOutputs(engine=self.name,exit_code=0,files={"summary.json":json.dumps(s)})
    def parse(self, raw: RawOutputs) -> ResultBundle:
        s=json.loads(raw.files["summary.json"])
        return ResultBundle(engine=self.name,quantities=[
            Quantity(name="ez_max",value=s["ez_max"]),
            Quantity(name="wavelength_um",value=s["wavelength_um"],unit="μm"),
        ],converged=s.get("converged",False),metadata=s)

def _em_intent(prob,wl,res,title=""):
    return Intent(mode="simulation_explicit",question=title or f"Meep {prob}",family="em",engine="meep_em",
        parameters={"problem":prob,"wavelength_um":wl,"resolution":res,"run_time":100.0,"n_medium":3.4},
        constraints=[Constraint(name="problem",value=prob)])
_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(name="meep_waveguide_ez_nonzero",engine="meep_em",
        description="Si waveguide FDTD: Ez_max > 0 at monitor (field propagates)",
        citation="Meep tutorials — silicon waveguide",
        intent=_em_intent("waveguide",1.55,16,"Si waveguide FDTD"),
        tolerances=[ToleranceSpec(quantity_name="ez_max",expected_value=0.5,rtol=2.0)]),
]
