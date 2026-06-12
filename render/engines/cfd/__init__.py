"""Computational fluid dynamics adapter — SU2 (Experimental stub).

SU2 is a C++ CFD solver. This adapter dispatches SU2 on a Slurm cluster or
locally if the `SU2_RUN` environment variable points to the SU2 binary directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
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

_SU2_TEMPLATE = """\
% SU2 Configuration
SOLVER= EULER
MATH_PROBLEM= DIRECT
RESTART_SOL= NO
MACH_NUMBER= {mach}
AOA= {aoa}
FREESTREAM_PRESSURE= 101325.0
FREESTREAM_TEMPERATURE= 288.15
REF_LENGTH= 1.0
REF_AREA= 1.0
MESH_FILENAME= {mesh_file}
MESH_FORMAT= SU2
CONV_FILENAME= history
SOLUTION_FILENAME= solution_flow.dat
OUTPUT_FILES= RESTART, SURFACE_CSV
INNER_ITER= {n_iter}
CONV_RESIDUAL_MINVAL= -6
"""


class CFDIntent(BaseModel):
    problem: str = Field(description="'euler_naca0012','channel_flow'")
    mach: float = Field(default=0.3, gt=0, lt=5, description="Freestream Mach number")
    aoa_deg: float = Field(default=2.0, description="Angle of attack in degrees")
    n_iter: int = Field(default=500, ge=10, le=10000)


class SU2Adapter:
    name: str = "su2_cfd"
    family: str = "cfd"
    status: TrustStatus = "experimental"
    version: ClassVar[str] = "1.0.0"
    runtime: ClassVar[str] = "either"
    environment: EnvSpec = EnvSpec(
        env_type="conda",
        packages=["su2>=8.0"],
        module_name="SU2",
        notes="module load SU2 on Compute2; or conda install -c conda-forge su2",
    )
    regime: RegimeSpec = RegimeSpec(
        bounds=[RegimeBound(field="mach", min_val=0.01, max_val=4.9)],
        notes="Euler solver; no viscous terms.",
    )

    @property
    def intent_schema(self):
        return CFDIntent

    @property
    def reference_cases(self):
        return _REFERENCE_CASES

    def validate(self, intent: Intent) -> ValidationReport:
        valid = {"euler_naca0012", "channel_flow"}
        prob = intent.parameters.get("problem", "")
        if prob not in valid:
            return ValidationReport(
                passed=False, failed_layer=1, errors=[f"Unknown problem '{prob}'."]
            )
        return ValidationReport(passed=True)

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name, params=dict(intent.parameters))

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        su2_dir = os.environ.get("SU2_RUN", "")
        su2_cfd = Path(su2_dir) / "SU2_CFD" if su2_dir else Path("SU2_CFD")
        if not su2_cfd.exists():
            # Try which
            result = subprocess.run(["which", "SU2_CFD"], capture_output=True, text=True)
            if result.returncode != 0:
                raise ImportError(
                    "SU2 not found. Set SU2_RUN env var or load the SU2 module on Compute2.\n"
                    "  module load SU2  (on WashU Compute2)\n"
                    "  conda install -c conda-forge su2"
                )
            su2_cfd = Path(result.stdout.strip())
        p = inputs.params
        mach = float(p.get("mach", 0.3))
        aoa = float(p.get("aoa_deg", 2.0))
        n_iter = int(p.get("n_iter", 500))
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _SU2_TEMPLATE.format(mach=mach, aoa=aoa, mesh_file="naca0012.su2", n_iter=n_iter)
            cfg_file = Path(tmpdir) / "cfd.cfg"
            cfg_file.write_text(cfg)
            proc = subprocess.run(
                [str(su2_cfd), str(cfg_file)],
                capture_output=True,
                text=True,
                cwd=tmpdir,
                timeout=3600,
            )
            if proc.returncode != 0:
                return RawOutputs(
                    engine=self.name, exit_code=proc.returncode, stderr=proc.stderr[:2000], files={}
                )
            # Parse history CSV for last iteration
            hist = Path(tmpdir) / "history.csv"
            cd = cl = 0.0
            converged = False
            if hist.exists():
                lines = hist.read_text().splitlines()
                if len(lines) > 1:
                    last = lines[-1].split(",")
                    try:
                        cd = float(last[4])
                        cl = float(last[5])
                        converged = True
                    except (IndexError, ValueError):
                        pass
            s = {
                "problem": p.get("problem", "euler_naca0012"),
                "mach": mach,
                "aoa_deg": aoa,
                "cd": cd,
                "cl": cl,
                "converged": converged,
            }
            return RawOutputs(engine=self.name, exit_code=0, files={"summary.json": json.dumps(s)})

    def parse(self, raw: RawOutputs) -> ResultBundle:
        s = json.loads(raw.files.get("summary.json", "{}"))
        return ResultBundle(
            engine=self.name,
            quantities=[
                Quantity(name="cd", value=s.get("cd", 0.0), description="Drag coefficient"),
                Quantity(name="cl", value=s.get("cl", 0.0), description="Lift coefficient"),
                Quantity(name="mach", value=s.get("mach", 0.0)),
            ],
            converged=s.get("converged", False),
            metadata=s,
        )


def _cfd_intent(prob, mach, aoa, title=""):
    return Intent(
        mode="simulation_explicit",
        question=title or f"CFD {prob}",
        family="cfd",
        engine="su2_cfd",
        parameters={"problem": prob, "mach": mach, "aoa_deg": aoa, "n_iter": 500},
        constraints=[Constraint(name="problem", value=prob)],
    )


_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(
        name="cfd_naca0012_cd_positive",
        engine="su2_cfd",
        description="NACA0012 Euler Mach=0.3 AoA=2° — Cd > 0",
        citation="SU2 test suite",
        intent=_cfd_intent("euler_naca0012", 0.3, 2.0, "NACA0012 Euler CFD"),
        tolerances=[ToleranceSpec(quantity_name="cd", expected_value=0.005, rtol=1.0)],
    ),
]
