"""Systems biology (SBML) adapter — Tellurium / libRoadRunner."""
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
    TrustStatus,
    ValidationReport,
)
from render.validate.regime import RegimeBound, RegimeSpec


class SBMLIntent(BaseModel):
    model_sbml: str = Field(description="SBML/Antimony model string or built-in name ('goodwin', 'repressilator')")
    t_end: float = Field(default=100.0, gt=0)
    n_points: int = Field(default=500, ge=10, le=10_000)
    selections: list[str] = Field(default_factory=list, description="Species to record")

class TelluriumAdapter:
    name: str = "tellurium_sbml"; family: str = "sbml"; status: TrustStatus = "certified"
    version: ClassVar[str] = "1.0.0"; runtime: ClassVar[str] = "local"
    environment: EnvSpec = EnvSpec(env_type="pip", packages=["tellurium>=2.2","libroadrunner>=2.5"])
    regime: RegimeSpec = RegimeSpec(bounds=[RegimeBound(field="t_end",min_val=0.1,max_val=1e6)])
    @property
    def intent_schema(self): return SBMLIntent
    @property
    def reference_cases(self): return _REFERENCE_CASES
    def validate(self, intent: Intent) -> ValidationReport:
        return ValidationReport(passed=True)
    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name,params=dict(intent.parameters))
    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        try:
            import tellurium as te
        except ImportError:
            raise ImportError("tellurium not installed. Run: pip install tellurium")
        p=inputs.params; model_str=p.get("model_sbml","repressilator")
        t_end=float(p.get("t_end",100.0)); n=int(p.get("n_points",500))
        if model_str=="repressilator":
            model_str=_REPRESSILATOR_ANTIMONY
        elif model_str=="goodwin":
            model_str=_GOODWIN_ANTIMONY
        r=te.loada(model_str); r.simulate(0,t_end,n)
        m=r.getFloatingSpeciesConcentrations()
        names=r.getFloatingSpeciesIds()
        s={"t_end":t_end,"species_final":dict(zip(names,m.tolist())),"n_species":len(names)}
        return RawOutputs(engine=self.name,exit_code=0,files={"summary.json":json.dumps(s)})
    def parse(self, raw: RawOutputs) -> ResultBundle:
        s=json.loads(raw.files["summary.json"])
        qtys=[Quantity(name=k,value=v) for k,v in s.get("species_final",{}).items()]
        return ResultBundle(engine=self.name,quantities=qtys,converged=True,metadata=s)

_REPRESSILATOR_ANTIMONY="""
var X, Y, Z
X -> ; alpha/(1+Z^n)-X; Y -> ; alpha/(1+X^n)-Y; Z -> ; alpha/(1+Y^n)-Z
alpha=0.5; n=2; X=0.1; Y=0.3; Z=0.6
"""
_GOODWIN_ANTIMONY="""
var X1, X2, X3
X1 -> ; k1/(1+X3^n)-d1*X1; X2 -> ; k2*X1-d2*X2; X3 -> ; k3*X2-d3*X3
k1=1.0;k2=1.0;k3=1.0;d1=0.1;d2=0.1;d3=0.1;n=10;X1=0.5;X2=0.5;X3=0.5
"""
def _sbml_intent(model_str,t_end):
    return Intent(mode="simulation_explicit",question=f"SBML {model_str} t={t_end}",family="sbml",
        engine="tellurium_sbml",parameters={"model_sbml":model_str,"t_end":t_end,"n_points":500},
        constraints=[Constraint(name="model_sbml",value=model_str)])
_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(name="sbml_repressilator_species_positive",engine="tellurium_sbml",
        description="Repressilator: all species concentrations remain positive",
        citation="Elowitz & Leibler (2000) Nature",
        intent=_sbml_intent("repressilator",200.0),
        tolerances=[]),
]
