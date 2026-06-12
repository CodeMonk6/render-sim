"""Discrete-event simulation adapter — SimPy."""
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


class DESIntent(BaseModel):
    model: str = Field(description="'mm1_queue' or 'simple_process'")
    sim_time: float = Field(gt=0)
    arrival_rate: float = Field(default=1.0, gt=0, description="Mean arrivals per time unit")
    service_rate: float = Field(default=2.0, gt=0)
    n_servers: int = Field(default=1, ge=1, le=100)
    seed: int = Field(default=42)

class SimPyAdapter:
    name: str = "simpy_des"; family: str = "des"; status: TrustStatus = "certified"
    version: ClassVar[str] = "1.0.0"; runtime: ClassVar[str] = "local"
    environment: EnvSpec = EnvSpec(env_type="pip", packages=["simpy>=4.0"])
    regime: RegimeSpec = RegimeSpec(bounds=[RegimeBound(field="sim_time",min_val=1,max_val=1e7)])
    @property
    def intent_schema(self): return DESIntent
    @property
    def reference_cases(self): return _REFERENCE_CASES
    def validate(self, intent: Intent) -> ValidationReport:
        m=intent.parameters.get("model","")
        if m not in ("mm1_queue","simple_process"):
            return ValidationReport(passed=False,failed_layer=1,errors=[f"Unknown model '{m}'"])
        return ValidationReport(passed=True)
    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name,params=dict(intent.parameters),seed=intent.parameters.get("seed",42))
    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        try:
            import simpy
        except ImportError:
            raise ImportError("simpy not installed. Run: pip install simpy")
        import random

        import numpy as np
        p=inputs.params; p.get("model","mm1_queue")
        sim_time=float(p["sim_time"]); lam=float(p.get("arrival_rate",1.0))
        mu=float(p.get("service_rate",2.0)); n_srv=int(p.get("n_servers",1))
        seed=int(p.get("seed",42)); rng=random.Random(seed)
        waits=[]; departures=[0]
        def customer(env,res):
            arrival=env.now
            with res.request() as req:
                yield req
                wait=env.now-arrival; waits.append(wait)
                yield env.timeout(rng.expovariate(mu))
                departures[0]+=1
        def arrivals(env,res):
            while True:
                yield env.timeout(rng.expovariate(lam))
                env.process(customer(env,res))
        env=simpy.Environment(); res=simpy.Resource(env,capacity=n_srv)
        env.process(arrivals(env,res)); env.run(until=sim_time)
        rho=lam/(mu*n_srv)
        w_theory=1/mu+rho/((1-rho)*mu) if rho<1 else float("inf")
        s={"mean_wait":float(np.mean(waits)) if waits else 0.0,
           "max_wait":float(max(waits)) if waits else 0.0,
           "n_served":departures[0],"utilization_theory":rho,
           "mean_wait_theory_mm1":w_theory if n_srv==1 and rho<1 else None}
        return RawOutputs(engine=self.name,exit_code=0,files={"summary.json":json.dumps(s)})
    def parse(self, raw: RawOutputs) -> ResultBundle:
        s=json.loads(raw.files["summary.json"])
        return ResultBundle(engine=self.name,quantities=[
            Quantity(name="mean_wait",value=s["mean_wait"],unit="time_units"),
            Quantity(name="n_served",value=s["n_served"]),
            Quantity(name="utilization_theory",value=s["utilization_theory"]),
        ],converged=True,metadata=s)

def _des_intent(model,sim_time,lam,mu,n_srv,seed=42):
    return Intent(mode="simulation_explicit",question=f"{model} lambda={lam} mu={mu}",family="des",
        engine="simpy_des",parameters={"model":model,"sim_time":sim_time,"arrival_rate":lam,
        "service_rate":mu,"n_servers":n_srv,"seed":seed},
        constraints=[Constraint(name="model",value=model)])
_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(name="des_mm1_utilization",engine="simpy_des",
        description="M/M/1 queue: rho = lambda/mu exactly",citation="Kleinrock (1975) Vol 1",
        intent=_des_intent("mm1_queue",10000.0,1.0,2.0,1,42),
        tolerances=[ToleranceSpec(quantity_name="utilization_theory",expected_value=0.5,rtol=1e-9)]),
]
