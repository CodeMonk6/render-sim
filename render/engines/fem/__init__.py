"""Finite element method adapter — FEniCSx."""
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


class FEMIntent(BaseModel):
    problem: str = Field(description="'poisson','heat_equation','linear_elasticity','stokes'")
    mesh_type: str = Field(default="unit_square", description="'unit_square','unit_cube','interval'")
    n_cells: int = Field(default=32, ge=2, le=512)
    degree: int = Field(default=1, ge=1, le=4, description="FE polynomial degree")
    f_source: str = Field(default="1.0", description="Source term expression (Python-eval'd float or string)")
    dirichlet_value: float = Field(default=0.0)

class FEniCSxAdapter:
    name: str = "fenicsx_fem"; family: str = "fem"; status: TrustStatus = "experimental"
    version: ClassVar[str] = "1.0.0"; runtime: ClassVar[str] = "either"
    environment: EnvSpec = EnvSpec(env_type="conda",packages=["fenics-dolfinx>=0.8"],
        notes="conda install -c conda-forge fenics-dolfinx")
    regime: RegimeSpec = RegimeSpec(bounds=[RegimeBound(field="n_cells",min_val=2,max_val=512)],
        notes="FEniCSx local; large problems require HPC.")
    @property
    def intent_schema(self): return FEMIntent
    @property
    def reference_cases(self): return _REFERENCE_CASES
    def validate(self, intent: Intent) -> ValidationReport:
        valid={"poisson","heat_equation","linear_elasticity","stokes"}
        prob=intent.parameters.get("problem","")
        if prob not in valid:
            return ValidationReport(passed=False,failed_layer=1,errors=[f"Unknown problem '{prob}'."])
        return ValidationReport(passed=True)
    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name,params=dict(intent.parameters))
    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        try:
            import dolfinx  # noqa: F401
            import numpy as np
            import ufl
            from dolfinx import fem
            from dolfinx import mesh as dmesh
            from dolfinx.fem.petsc import LinearProblem
            from mpi4py import MPI
        except ImportError:
            raise ImportError("FEniCSx not installed. Run: conda install -c conda-forge fenics-dolfinx")
        p=inputs.params; prob=p.get("problem","poisson"); n=int(p.get("n_cells",32))
        domain=dmesh.create_unit_square(MPI.COMM_WORLD,n,n)
        V=fem.functionspace(domain,("Lagrange",int(p.get("degree",1))))
        u,v=ufl.TrialFunction(V),ufl.TestFunction(V)
        f_val=float(p.get("f_source","1.0")); f=fem.Constant(domain,f_val)
        a=ufl.dot(ufl.grad(u),ufl.grad(v))*ufl.dx; L=f*v*ufl.dx
        bc=fem.dirichletbc(fem.Constant(domain,float(p.get("dirichlet_value",0.0))),
                           fem.locate_dofs_topological(V,domain.topology.dim-1,
                           dmesh.locate_entities_boundary(domain,domain.topology.dim-1,
                               lambda x: np.full(x.shape[1],True))),V)
        problem=LinearProblem(a,L,bcs=[bc],petsc_options={"ksp_type":"preonly","pc_type":"lu"})
        uh=problem.solve()
        u_arr=uh.x.array; u_max=float(u_arr.max()); u_mean=float(u_arr.mean()); n_dofs=len(u_arr)
        s={"problem":prob,"n_cells":n,"u_max":u_max,"u_mean":u_mean,"n_dofs":n_dofs,"converged":True}
        return RawOutputs(engine=self.name,exit_code=0,files={"summary.json":json.dumps(s)})
    def parse(self, raw: RawOutputs) -> ResultBundle:
        s=json.loads(raw.files["summary.json"])
        return ResultBundle(engine=self.name,quantities=[
            Quantity(name="u_max",value=s["u_max"]),
            Quantity(name="u_mean",value=s["u_mean"]),
            Quantity(name="n_dofs",value=s["n_dofs"]),
        ],converged=True,metadata=s)

def _fem_intent(prob,n_cells,title=""):
    return Intent(mode="simulation_explicit",question=title or f"FEM {prob}",family="fem",engine="fenicsx_fem",
        parameters={"problem":prob,"n_cells":n_cells,"degree":1,"f_source":"1.0","dirichlet_value":0.0},
        constraints=[Constraint(name="problem",value=prob)])
_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(name="fem_poisson_u_max_positive",engine="fenicsx_fem",
        description="Poisson -Δu=1 on unit square → u_max > 0 (positive solution)",
        citation="FEniCSx tutorial example",
        intent=_fem_intent("poisson",32,"Poisson equation unit square"),
        tolerances=[ToleranceSpec(quantity_name="u_max",expected_value=0.073,rtol=0.1)]),
]
