"""Compartmental epidemiology / PK adapter — SIR/SEIR via SciPy."""
from __future__ import annotations

import json
from typing import ClassVar

import numpy as np
from pydantic import BaseModel, Field
from scipy.integrate import solve_ivp

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


class EpiIntent(BaseModel):
    model: str = Field(description="'SIR' or 'SEIR'")
    N: float = Field(gt=0, description="Total population")
    t_end: float = Field(gt=0, description="Simulation duration (days)")
    beta: float = Field(default=0.3, gt=0, description="Transmission rate (1/day)")
    gamma: float = Field(default=0.1, gt=0, description="Recovery rate (1/day)")
    sigma: float = Field(default=0.2, gt=0, description="Incubation rate (1/day, SEIR)")
    I0: float = Field(default=1.0, gt=0, description="Initial infectious")
    E0: float = Field(default=0.0, ge=0, description="Initial exposed (SEIR)")
    n_points: int = Field(default=500, ge=10, le=10_000)

class EpiAdapter:
    name: str = "epi_sir_seir"; family: str = "epi"; status: TrustStatus = "certified"
    description: ClassVar[str] = (
        "compartmental epidemic models SIR and SEIR; use for outbreaks, R0, "
        "transmission/recovery rates, attack rate, epidemic peak"
    )
    version: ClassVar[str] = "1.0.0"; runtime: ClassVar[str] = "local"
    environment: EnvSpec = EnvSpec(env_type="pip", packages=["scipy>=1.13","numpy>=1.26"])
    regime: RegimeSpec = RegimeSpec(bounds=[
        RegimeBound(field="N", min_val=10, max_val=1e10),
        RegimeBound(field="t_end", min_val=1, max_val=3650, unit="days"),
        RegimeBound(field="beta", min_val=1e-5, max_val=100.0),
        RegimeBound(field="gamma", min_val=1e-5, max_val=100.0),
    ])
    @property
    def intent_schema(self): return EpiIntent
    @property
    def reference_cases(self): return _REFERENCE_CASES
    def validate(self, intent: Intent) -> ValidationReport:
        m = intent.parameters.get("model", "")
        if m not in ("SIR","SEIR"):
            return ValidationReport(passed=False, failed_layer=1, errors=[f"Unknown model '{m}'"])
        return ValidationReport(passed=True)
    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name, params=dict(intent.parameters))
    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        p = inputs.params; model=p.get("model","SIR"); N=float(p["N"])
        t_end=float(p["t_end"]); beta=float(p.get("beta",0.3)); gamma=float(p.get("gamma",0.1))
        sigma=float(p.get("sigma",0.2)); I0=float(p.get("I0",1.0)); E0=float(p.get("E0",0.0))
        n=int(p.get("n_points",500)); t_eval=np.linspace(0,t_end,n)
        if model=="SIR":
            y0=[N-I0,I0,0.0]
            rhs=lambda t,y: [-beta*y[0]*y[1]/N, beta*y[0]*y[1]/N-gamma*y[1], gamma*y[1]]
            idx=1
        else:
            y0=[N-E0-I0,E0,I0,0.0]
            rhs=lambda t,y: [-beta*y[0]*y[2]/N, beta*y[0]*y[2]/N-sigma*y[1], sigma*y[1]-gamma*y[2], gamma*y[2]]
            idx=2
        sol=solve_ivp(rhs,[0,t_end],y0,t_eval=t_eval,rtol=1e-8,atol=1e-10)
        I_t=sol.y[idx]; R_final=float(sol.y[-1,-1]); peak_I=float(I_t.max()); peak_t=float(sol.t[int(I_t.argmax())])
        # Downsampled trajectory for plotting (cap ~200 points, keep figures light).
        labels=(["S","I","R"] if model=="SIR" else ["S","E","I","R"])
        step=max(1,len(sol.t)//200)
        series={"title":f"{model} epidemic curve","x":{"name":"time","unit":"days",
                "values":[round(float(t),4) for t in sol.t[::step]]},
                "y":[{"name":lab,"values":[round(float(v),3) for v in sol.y[i][::step]]}
                     for i,lab in enumerate(labels)]}
        s={"model":model,"R0":beta/gamma,"peak_I":peak_I,"peak_t_days":peak_t,
           "R_final":R_final,"attack_rate":R_final/N,"S_final":float(sol.y[0,-1]),"series":series}
        return RawOutputs(engine=self.name, exit_code=0, files={"summary.json":json.dumps(s)})
    def parse(self, raw: RawOutputs) -> ResultBundle:
        s=json.loads(raw.files["summary.json"])
        return ResultBundle(engine=self.name, quantities=[
            Quantity(name="R0",value=s["R0"]),
            Quantity(name="peak_infected",value=s["peak_I"],unit="persons"),
            Quantity(name="peak_day",value=s["peak_t_days"],unit="days"),
            Quantity(name="total_recovered",value=s["R_final"],unit="persons"),
            Quantity(name="attack_rate",value=s["attack_rate"]),
        ], converged=True, metadata=s)

def _intent(model,N,beta,gamma,I0,t_end):
    return Intent(mode="simulation_explicit",question=f"{model} R0={beta/gamma:.1f}",family="epi",
        engine="epi_sir_seir",parameters={"model":model,"N":N,"beta":beta,"gamma":gamma,"I0":I0,"t_end":t_end,"n_points":1000},
        constraints=[Constraint(name="model",value=model)])
_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(name="sir_r0_threshold",engine="epi_sir_seir",
        description="SIR: R0 = beta/gamma exactly",citation="Kermack & McKendrick (1927)",
        intent=_intent("SIR",10000.0,0.3,0.1,1.0,160.0),
        tolerances=[ToleranceSpec(quantity_name="R0",expected_value=3.0,rtol=1e-9)]),
    ReferenceCase(name="sir_subcritical",engine="epi_sir_seir",
        description="SIR R0<1: attack_rate near 0",citation="Anderson & May (1991)",
        intent=_intent("SIR",10000.0,0.05,0.1,1.0,200.0),
        tolerances=[ToleranceSpec(quantity_name="R0",expected_value=0.5,rtol=1e-9),
                    ToleranceSpec(quantity_name="attack_rate",expected_value=0.0,atol=0.02)]),
]
