"""Molecular dynamics adapter — GROMACS (priority-certify C*)."""

from __future__ import annotations

import json
import os
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
from render.validate.regime import RegimeBound, RegimeSpec


class GROMACSIntent(BaseModel):
    system: str = Field(description="'ala_dipeptide_em','ala_dipeptide_nvt','tip4p_water_npt'")
    temperature: float = Field(default=300.0, gt=0)
    pressure_bar: float = Field(default=1.0, gt=0)
    n_steps: int = Field(default=5000, ge=100)
    timestep_ps: float = Field(default=0.002, gt=0)
    seed: int = Field(default=42)


class GROMACSAdapter:
    name: str = "gromacs_md"
    family: str = "md"
    status: TrustStatus = "experimental"
    version: ClassVar[str] = "1.0.0"
    runtime: ClassVar[str] = "either"
    environment: EnvSpec = EnvSpec(
        env_type="conda",
        packages=["gromacs>=2023.4"],
        module_name="GROMACS",
        notes="module load GROMACS on Compute2; or conda install -c conda-forge gromacs",
    )
    regime: RegimeSpec = RegimeSpec(
        bounds=[
            RegimeBound(field="temperature", min_val=100.0, max_val=600.0, unit="K"),
            RegimeBound(field="pressure_bar", min_val=0.1, max_val=1000.0, unit="bar"),
        ]
    )

    @property
    def intent_schema(self):
        return GROMACSIntent

    @property
    def reference_cases(self):
        return _REF

    def validate(self, intent: Intent) -> ValidationReport:
        valid = {"ala_dipeptide_em", "ala_dipeptide_nvt", "tip4p_water_npt"}
        if intent.parameters.get("system", "") not in valid:
            return ValidationReport(
                passed=False, failed_layer=1, errors=["Unknown GROMACS system."]
            )
        return ValidationReport(passed=True)

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name, params=dict(intent.parameters))

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        p = inputs.params
        gmx = os.environ.get("GMX_CMD", "gmx")
        if subprocess.run(["which", gmx], capture_output=True).returncode != 0:
            gmx = "gmx_mpi"
            if subprocess.run(["which", gmx], capture_output=True).returncode != 0:
                raise ImportError(
                    "GROMACS not found. module load GROMACS on Compute2, or set GMX_CMD."
                )
        # Stub: full run requires topology/coordinate input files (certify on Compute2)
        T = float(p.get("temperature", 300.0))
        P = float(p.get("pressure_bar", 1.0))
        s = {
            "system": p.get("system", "ala_dipeptide_em"),
            "temperature_K": T,
            "pressure_bar": P,
            "converged": False,
            "note": "Run on Compute2 with topology files to certify.",
        }
        return RawOutputs(engine=self.name, exit_code=0, files={"summary.json": json.dumps(s)})

    def parse(self, raw: RawOutputs) -> ResultBundle:
        s = json.loads(raw.files.get("summary.json", "{}"))
        return ResultBundle(
            engine=self.name,
            quantities=[
                Quantity(name="temperature_K", value=s.get("temperature_K", 0), unit="K"),
                Quantity(name="pressure_bar", value=s.get("pressure_bar", 0), unit="bar"),
            ],
            converged=s.get("converged", False),
            metadata=s,
        )


def _i(sys_, T, nsteps):
    return Intent(
        mode="simulation_explicit",
        question=f"GROMACS {sys_}",
        family="md",
        engine="gromacs_md",
        parameters={"system": sys_, "temperature": T, "n_steps": nsteps, "seed": 42},
        constraints=[Constraint(name="system", value=sys_)],
    )


_REF: list[ReferenceCase] = [
    ReferenceCase(
        name="gromacs_ala_em",
        engine="gromacs_md",
        description="Alanine dipeptide EM — adapter dispatches without error",
        citation="GROMACS tutorial",
        intent=_i("ala_dipeptide_em", 300.0, 1000),
        tolerances=[ToleranceSpec(quantity_name="temperature_K", expected_value=300.0, rtol=1.0)],
    ),
]
