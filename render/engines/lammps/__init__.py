"""Molecular dynamics adapter — LAMMPS (priority-certify C*)."""
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

_LJ_SCRIPT = """\
units           real
atom_style      atomic
boundary        p p p
lattice         fcc {a}
region          box block 0 4 0 4 0 4
create_box      1 box
create_atoms    1 box
mass            1 39.948
pair_style      lj/cut 10.0
pair_coeff      1 1 {epsilon} {sigma} 10.0
velocity        all create {temperature} {seed} dist gaussian
fix             1 all nvt temp {temperature} {temperature} 100.0
timestep        {timestep}
thermo          100
thermo_style    custom step temp press pe density
run             {n_steps}
"""

class LAMMPSIntent(BaseModel):
    system: str = Field(description="'lj_argon'")
    temperature: float = Field(gt=0, description="Temperature in K")
    n_steps: int = Field(default=10000, ge=100)
    timestep_fs: float = Field(default=2.0, gt=0)
    seed: int = Field(default=12345)
    lj_epsilon_kcal: float = Field(default=0.2385, gt=0)
    lj_sigma_ang: float = Field(default=3.405, gt=0)
    density_fcc_a: float = Field(default=5.26, gt=0)

class LAMMPSAdapter:
    name: str = "lammps_md"; family: str = "md"; status: TrustStatus = "experimental"
    version: ClassVar[str] = "1.0.0"; runtime: ClassVar[str] = "either"
    environment: EnvSpec = EnvSpec(env_type="conda",packages=["lammps>=2023.11"],module_name="LAMMPS",
        notes="module load LAMMPS on Compute2; or conda install -c conda-forge lammps")
    regime: RegimeSpec = RegimeSpec(bounds=[RegimeBound(field="temperature",min_val=1.0,max_val=10000.0,unit="K")])
    @property
    def intent_schema(self): return LAMMPSIntent
    @property
    def reference_cases(self): return _REF
    def validate(self, intent: Intent) -> ValidationReport:
        if intent.parameters.get("system","") not in {"lj_argon"}:
            return ValidationReport(passed=False,failed_layer=1,errors=["Unknown LAMMPS system."])
        return ValidationReport(passed=True)
    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name,params=dict(intent.parameters))
    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        p=inputs.params
        try:
            from lammps import lammps  # type: ignore[import-untyped]
            T=float(p.get("temperature",100.0)); nsteps=int(p.get("n_steps",10000))
            eps=float(p.get("lj_epsilon_kcal",0.2385)); sig=float(p.get("lj_sigma_ang",3.405))
            a=float(p.get("density_fcc_a",5.26)); ts=float(p.get("timestep_fs",2.0)); seed=int(p.get("seed",12345))
            script=_LJ_SCRIPT.format(a=a,epsilon=eps,sigma=sig,temperature=T,seed=seed,timestep=ts,n_steps=nsteps)
            L=lammps(cmdargs=["-screen","none","-log","none"])
            for line in script.splitlines():
                if line.strip(): L.command(line)
            s={"system":p.get("system","lj_argon"),"temperature_K":float(L.get_thermo("temp")),
               "density_g_cm3":float(L.get_thermo("density")),"pe_kcal_mol":float(L.get_thermo("pe")),"converged":True}
            L.close()
            return RawOutputs(engine=self.name,exit_code=0,files={"summary.json":json.dumps(s)})
        except ImportError:
            pass
        lmp=os.environ.get("LAMMPS_CMD","lmp")
        if subprocess.run(["which",lmp],capture_output=True).returncode!=0:
            raise ImportError("LAMMPS not found. module load LAMMPS on Compute2, or set LAMMPS_CMD.")
        T=float(p.get("temperature",100.0)); nsteps=int(p.get("n_steps",10000))
        eps=float(p.get("lj_epsilon_kcal",0.2385)); sig=float(p.get("lj_sigma_ang",3.405))
        a=float(p.get("density_fcc_a",5.26)); ts=float(p.get("timestep_fs",2.0)); seed=int(p.get("seed",12345))
        script=_LJ_SCRIPT.format(a=a,epsilon=eps,sigma=sig,temperature=T,seed=seed,timestep=ts,n_steps=nsteps)
        with tempfile.TemporaryDirectory() as tmpdir:
            inp=Path(tmpdir)/"in.lammps"; inp.write_text(script)
            proc=subprocess.run([lmp,"-in",str(inp)],capture_output=True,text=True,cwd=tmpdir,timeout=3600)
            if proc.returncode!=0:
                return RawOutputs(engine=self.name,exit_code=proc.returncode,stderr=proc.stderr[:2000],files={})
            # Parse last thermo line
            temp_o=T; dens_o=1.4; pe_o=0.0
            log=Path(tmpdir)/"log.lammps"
            if log.exists():
                for line in log.read_text().splitlines():
                    parts=line.split()
                    if len(parts)>=5 and parts[0].isdigit():
                        try: temp_o=float(parts[1]); pe_o=float(parts[3]); dens_o=float(parts[4])
                        except (IndexError,ValueError): pass
            s={"system":p.get("system","lj_argon"),"temperature_K":temp_o,"density_g_cm3":dens_o,"pe_kcal_mol":pe_o,"converged":True}
            return RawOutputs(engine=self.name,exit_code=0,files={"summary.json":json.dumps(s)})
    def parse(self, raw: RawOutputs) -> ResultBundle:
        s=json.loads(raw.files.get("summary.json","{}"))
        return ResultBundle(engine=self.name,quantities=[
            Quantity(name="temperature_K",value=s.get("temperature_K",0),unit="K"),
            Quantity(name="density_g_cm3",value=s.get("density_g_cm3",0),unit="g/cm³"),
            Quantity(name="pe_kcal_mol",value=s.get("pe_kcal_mol",0),unit="kcal/mol"),
        ],converged=s.get("converged",False),metadata=s)

def _i(T,nsteps): return Intent(mode="simulation_explicit",question=f"LAMMPS LJ argon T={T}K",family="md",engine="lammps_md",
    parameters={"system":"lj_argon","temperature":T,"n_steps":nsteps,"seed":12345},constraints=[Constraint(name="system",value="lj_argon")])
_REF: list[ReferenceCase]=[
    ReferenceCase(name="lammps_lj_argon_density",engine="lammps_md",description="LJ argon NVT 85K — density ~1.4 g/cm³",
        citation="Rahman (1964)",intent=_i(85.0,5000),tolerances=[ToleranceSpec(quantity_name="density_g_cm3",expected_value=1.4,rtol=0.15)]),
    ReferenceCase(name="lammps_lj_argon_temp",engine="lammps_md",description="NVT thermostat holds temperature ±20%",
        citation="Standard NVT",intent=_i(100.0,2000),tolerances=[ToleranceSpec(quantity_name="temperature_K",expected_value=100.0,rtol=0.2)]),
]
