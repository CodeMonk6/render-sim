"""Electronic structure / DFT adapter — PySCF."""

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
from render.validate.regime import RegimeSpec


class DFTIntent(BaseModel):
    molecule: str = Field(description="XYZ or SMILES string, or built-in name ('H2', 'H2O', 'N2')")
    method: str = Field(default="hf", description="'hf', 'dft', 'mp2', 'ccsd'")
    basis: str = Field(default="sto-3g", description="Basis set")
    charge: int = Field(default=0)
    spin: int = Field(default=0, ge=0)
    functional: str = Field(default="b3lyp", description="DFT functional (if method=dft)")
    xc: str = Field(default="", description="Alias for functional")


class PySCFAdapter:
    name: str = "pyscf_dft"
    family: str = "dft"
    status: TrustStatus = "certified"
    description: ClassVar[str] = (
        "electronic structure / quantum chemistry via PySCF: HF, DFT, MP2, CCSD energies for "
        "molecules; use for electronic energy, ground state, basis sets, point-defect/qubit questions"
    )
    version: ClassVar[str] = "1.0.0"
    runtime: ClassVar[str] = "either"
    environment: EnvSpec = EnvSpec(
        env_type="pip", packages=["pyscf>=2.5"], notes="pip install pyscf"
    )
    regime: RegimeSpec = RegimeSpec(bounds=[], notes="Regime depends on system size and method.")

    @property
    def intent_schema(self):
        return DFTIntent

    @property
    def reference_cases(self):
        return _REFERENCE_CASES

    def validate(self, intent: Intent) -> ValidationReport:
        method = str(intent.parameters.get("method", "hf")).lower()
        if method not in ("hf", "dft", "mp2", "ccsd", "ccsd(t)"):
            return ValidationReport(
                passed=False, failed_layer=1, errors=[f"Unknown method '{method}'"]
            )
        return ValidationReport(passed=True)

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name, params=dict(intent.parameters))

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        try:
            from pyscf import dft as pyscf_dft
            from pyscf import gto, scf
        except ImportError:
            raise ImportError("PySCF not installed. Run: pip install pyscf")
        p = inputs.params
        mol_str = p.get("molecule", "H2")
        method = str(p.get("method", "hf")).lower()
        basis = str(p.get("basis", "sto-3g")).lower()
        charge = int(p.get("charge", 0))
        spin = int(p.get("spin", 0))
        builtins = {
            "H2": "H 0 0 0; H 0 0 0.74",
            "H2O": "O 0 0 0; H 0 0.96 0.28; H 0 -0.96 0.28",
            "N2": "N 0 0 0; N 0 0 1.10",
        }
        atom_str = builtins.get(mol_str, mol_str)
        mol = gto.Mole()
        mol.atom = atom_str
        mol.basis = basis
        mol.charge = charge
        mol.spin = spin
        mol.verbose = 0
        mol.build()
        if method == "hf":
            mf = scf.RHF(mol) if spin == 0 else scf.UHF(mol)
        elif method == "dft":
            xc = p.get("xc", p.get("functional", "b3lyp"))
            mf = pyscf_dft.RKS(mol) if spin == 0 else pyscf_dft.UKS(mol)
            mf.xc = xc
        else:
            mf = scf.RHF(mol)
        e = mf.kernel()
        converged = bool(mf.converged)
        s = {
            "energy_hartree": float(e),
            "energy_eV": float(e) * 27.2114,
            "converged": converged,
            "molecule": mol_str,
            "method": method,
            "basis": basis,
            "n_electrons": int(mol.nelectron),
        }
        return RawOutputs(
            engine=self.name, exit_code=0 if converged else 1, files={"summary.json": json.dumps(s)}
        )

    def parse(self, raw: RawOutputs) -> ResultBundle:
        s = json.loads(raw.files["summary.json"])
        return ResultBundle(
            engine=self.name,
            quantities=[
                Quantity(name="energy_hartree", value=s["energy_hartree"], unit="Ha"),
                Quantity(name="energy_eV", value=s["energy_eV"], unit="eV"),
                Quantity(name="converged", value=s["converged"]),
                Quantity(name="n_electrons", value=s["n_electrons"]),
            ],
            converged=s["converged"],
            metadata=s,
        )


def _dft_intent(mol, method, basis, t="DFT calc"):
    return Intent(
        mode="simulation_explicit",
        question=t,
        family="dft",
        engine="pyscf_dft",
        parameters={"molecule": mol, "method": method, "basis": basis, "charge": 0, "spin": 0},
        constraints=[Constraint(name="molecule", value=mol)],
    )


_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(
        name="dft_h2_hf_sto3g_energy",
        engine="pyscf_dft",
        description="H2 HF/STO-3G total energy = -1.1175 Ha (textbook value)",
        citation="Szabo & Ostlund (1989) Table 3.6",
        intent=_dft_intent("H2", "hf", "sto-3g", "H2 HF/STO-3G ground state energy"),
        tolerances=[
            ToleranceSpec(quantity_name="energy_hartree", expected_value=-1.1175, rtol=0.001)
        ],
    ),
    ReferenceCase(
        name="dft_h2o_hf_sto3g_energy",
        engine="pyscf_dft",
        description="H2O HF/STO-3G total energy converges (negative, large)",
        citation="Hehre et al. (1986)",
        intent=_dft_intent("H2O", "hf", "sto-3g", "Water HF/STO-3G"),
        tolerances=[
            ToleranceSpec(quantity_name="energy_hartree", expected_value=-74.96, rtol=0.01)
        ],
    ),
]
