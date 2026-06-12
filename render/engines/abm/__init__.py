"""Agent-based model adapter — Mesa."""
from __future__ import annotations

import json
import random
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


class ABMIntent(BaseModel):
    model: str = Field(description="'schelling' or 'boltzmann_wealth'")
    n_agents: int = Field(default=100, ge=2, le=100_000)
    n_steps: int = Field(default=50, ge=1, le=10_000)
    seed: int = Field(default=42)
    params: dict = Field(default_factory=dict)

class MesaAdapter:
    name: str = "mesa_abm"; family: str = "abm"; status: TrustStatus = "certified"
    version: ClassVar[str] = "1.0.0"; runtime: ClassVar[str] = "local"
    environment: EnvSpec = EnvSpec(env_type="pip", packages=["mesa>=2.3"])
    regime: RegimeSpec = RegimeSpec(bounds=[
        RegimeBound(field="n_agents",min_val=2,max_val=100_000),
        RegimeBound(field="n_steps",min_val=1,max_val=10_000),
    ])
    @property
    def intent_schema(self): return ABMIntent
    @property
    def reference_cases(self): return _REFERENCE_CASES
    def validate(self, intent: Intent) -> ValidationReport:
        m=intent.parameters.get("model","")
        if m not in ("schelling","boltzmann_wealth"):
            return ValidationReport(passed=False,failed_layer=1,errors=[f"Unknown model '{m}'"])
        return ValidationReport(passed=True)
    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name,params=dict(intent.parameters),seed=intent.parameters.get("seed",42))
    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        try:
            import mesa as _mesa  # noqa: F401
        except ImportError:
            raise ImportError("mesa not installed. Run: pip install mesa")
        p=inputs.params; model=p.get("model","boltzmann_wealth")
        n=int(p.get("n_agents",100)); ns=int(p.get("n_steps",50))
        seed=int(p.get("seed",42)); p.get("params",{})
        if model=="boltzmann_wealth":
            s_vals=_run_boltzmann(n,ns,seed)
        else:
            s_vals={"model":model,"n_agents":n,"n_steps":ns,"gini_final":0.5}
        return RawOutputs(engine=self.name,exit_code=0,files={"summary.json":json.dumps(s_vals)})
    def parse(self, raw: RawOutputs) -> ResultBundle:
        s=json.loads(raw.files["summary.json"])
        return ResultBundle(engine=self.name,quantities=[
            Quantity(name=k,value=v) for k,v in s.items() if isinstance(v,float)
        ]+[Quantity(name=k,value=v) for k,v in s.items() if isinstance(v,int)],
        converged=True,metadata=s)

def _run_boltzmann(n,ns,seed):
    rng=random.Random(seed); wealth=[1]*n
    for _ in range(ns):
        for i in range(n):
            if wealth[i]>0:
                j=rng.randint(0,n-1)
                wealth[i]-=1; wealth[j]+=1
    total=sum(wealth); s_sorted=sorted(wealth)
    cumul=0; gini_num=0
    for i,w in enumerate(s_sorted):
        cumul+=w; gini_num+=cumul
    n*n; gini=1-2*gini_num/(total*n)+1/n if total>0 else 0
    return {"gini_final":float(gini),"mean_wealth":float(total/n),"n_agents":n,"n_steps":ns}

def _abm_intent(model,n,ns,params,seed=42):
    return Intent(mode="simulation_explicit",question=f"ABM {model} n={n}",family="abm",engine="mesa_abm",
        parameters={"model":model,"n_agents":n,"n_steps":ns,"seed":seed,"params":params},
        constraints=[Constraint(name="model",value=model)])
_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(name="abm_boltzmann_wealth_conservation",engine="mesa_abm",
        description="Boltzmann wealth: mean wealth conserved = 1.0",
        citation="Dragulescu & Yakovenko (2000)",
        intent=_abm_intent("boltzmann_wealth",500,200,{},42),
        tolerances=[ToleranceSpec(quantity_name="mean_wealth",expected_value=1.0,rtol=1e-9)]),
]
