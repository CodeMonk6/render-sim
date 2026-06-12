"""Materials utilities adapter — ASE + pymatgen.

Certified: structure creation, format conversion, and basic analysis.
These are workflow utilities (not standalone simulation engines) that feed
into MD/DFT/FreeBird adapters.
"""

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


class MaterialsIntent(BaseModel):
    operation: str = Field(
        description=(
            "'build_bulk','build_molecule','convert_structure','analyze_structure',"
            "'supercell','surface_slab'"
        )
    )
    formula: str = Field(
        default="", description="Chemical formula or material name, e.g. 'Si', 'NaCl', 'H2O'"
    )
    crystal_structure: str = Field(
        default="", description="Spacegroup or prototype, e.g. 'fcc', 'rocksalt', 'diamond'"
    )
    lattice_constant_ang: float = Field(
        default=0.0, description="Lattice constant in Å (0 = use default)"
    )
    input_file: str = Field(
        default="", description="Input structure text (CIF, POSCAR, XYZ) for convert/analyze"
    )
    input_format: str = Field(
        default="", description="Input file format: 'cif','poscar','xyz','pdb'"
    )
    output_format: str = Field(default="xyz", description="Output file format")
    supercell_matrix: list[int] = Field(
        default_factory=lambda: [1, 1, 1], description="Supercell repeats [a,b,c]"
    )
    miller_index: list[int] = Field(
        default_factory=lambda: [0, 0, 1], description="Miller index for slab"
    )
    slab_layers: int = Field(default=4, ge=1)
    cubic: bool = Field(
        default=True, description="Build the conventional cubic cell (vs primitive)"
    )


class ASEAdapter:
    name: str = "ase_materials"
    family: str = "materials_utils"
    status: TrustStatus = "certified"
    description: ClassVar[str] = (
        "materials structure utilities via ASE: build bulk crystals/molecules, supercells, surface "
        "slabs, format conversion (CIF/XYZ/POSCAR), cell volume/atom counts"
    )
    version: ClassVar[str] = "1.0.0"
    runtime: ClassVar[str] = "either"
    environment: EnvSpec = EnvSpec(
        env_type="pip", packages=["ase>=3.23", "pymatgen>=2024.5"], notes="pip install ase pymatgen"
    )
    regime: RegimeSpec = RegimeSpec(
        bounds=[], notes="Utility operations; no physical regime bounds."
    )

    @property
    def intent_schema(self):
        return MaterialsIntent

    @property
    def reference_cases(self):
        return _REFERENCE_CASES

    def validate(self, intent: Intent) -> ValidationReport:
        op = intent.parameters.get("operation", "")
        valid_ops = {
            "build_bulk",
            "build_molecule",
            "convert_structure",
            "analyze_structure",
            "supercell",
            "surface_slab",
        }
        if op not in valid_ops:
            return ValidationReport(
                passed=False,
                failed_layer=1,
                errors=[f"Unknown operation '{op}'. Valid: {sorted(valid_ops)}"],
            )
        return ValidationReport(passed=True)

    def build_inputs(self, intent: Intent) -> EngineInputs:
        return EngineInputs(engine=self.name, params=dict(intent.parameters))

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        try:
            import io

            import numpy as np
            from ase.build import bulk, molecule
            from ase.io import read as ase_read
            from ase.io import write as ase_write
        except ImportError:
            raise ImportError("ASE not installed. Run: pip install ase pymatgen")
        p = inputs.params
        op = p.get("operation", "build_bulk")
        result: dict = {}
        atoms = None
        if op == "build_bulk":
            formula = p.get("formula", "Si")
            cs = p.get("crystal_structure", "diamond")
            a = float(p.get("lattice_constant_ang", 0.0)) or None
            cubic = bool(p.get("cubic", True))
            if a:
                atoms = bulk(formula, crystalstructure=cs, a=a, cubic=cubic)
            else:
                atoms = bulk(formula, crystalstructure=cs, cubic=cubic)
            result = {
                "formula": formula,
                "n_atoms": len(atoms),
                "cell_volume_ang3": float(atoms.get_volume()),
                "positions": atoms.get_positions().tolist(),
            }
        elif op == "build_molecule":
            formula = p.get("formula", "H2O")
            try:
                atoms = molecule(formula)
            except KeyError:
                return RawOutputs(
                    engine=self.name, exit_code=1, stderr=f"Unknown molecule '{formula}'", files={}
                )
            result = {
                "formula": formula,
                "n_atoms": len(atoms),
                "positions": atoms.get_positions().tolist(),
            }
        elif op in ("convert_structure", "analyze_structure"):
            raw_text = p.get("input_file", "")
            fmt = p.get("input_format", "xyz")
            if not raw_text:
                return RawOutputs(
                    engine=self.name, exit_code=1, stderr="input_file required", files={}
                )
            f = io.StringIO(raw_text)
            atoms = ase_read(f, format=fmt)
            result = {
                "n_atoms": len(atoms),
                "chemical_formula": str(atoms.get_chemical_formula()),
                "cell_volume_ang3": float(atoms.get_volume()) if atoms.cell.any() else 0.0,
                "positions": atoms.get_positions().tolist(),
            }
        elif op == "supercell":
            formula = p.get("formula", "Si")
            cs = p.get("crystal_structure", "diamond")
            atoms = bulk(formula, crystalstructure=cs)
            sc = p.get("supercell_matrix", [2, 2, 2])
            import numpy as np
            from ase.build import make_supercell

            atoms = make_supercell(atoms, np.diag(sc))
            result = {
                "n_atoms": len(atoms),
                "supercell_matrix": sc,
                "cell_volume_ang3": float(atoms.get_volume()),
            }
        elif op == "surface_slab":
            formula = p.get("formula", "Si")
            cs = p.get("crystal_structure", "diamond")
            mi = p.get("miller_index", [0, 0, 1])
            layers = int(p.get("slab_layers", 4))
            from ase.build import surface

            slab = surface(bulk(formula, crystalstructure=cs), mi, layers)
            result = {
                "n_atoms": len(slab),
                "miller_index": mi,
                "n_layers": layers,
                "cell_volume_ang3": float(slab.get_volume()),
            }
        else:
            result = {}
        # Write output structure as XYZ if atoms available
        out_files: dict[str, str] = {"summary.json": json.dumps(result)}
        if atoms is not None:
            buf = io.StringIO()
            ase_write(buf, atoms, format=p.get("output_format", "xyz"))
            out_files["structure.xyz"] = buf.getvalue()
        return RawOutputs(engine=self.name, exit_code=0, files=out_files)

    def parse(self, raw: RawOutputs) -> ResultBundle:
        s = json.loads(raw.files.get("summary.json", "{}"))
        quantities = [Quantity(name="n_atoms", value=s.get("n_atoms", 0))]
        if "cell_volume_ang3" in s:
            quantities.append(
                Quantity(name="cell_volume_ang3", value=s["cell_volume_ang3"], unit="Å³")
            )
        return ResultBundle(engine=self.name, quantities=quantities, converged=True, metadata=s)


def _mat_intent(op, formula, cs, title=""):
    return Intent(
        mode="simulation_explicit",
        question=title or f"{op} {formula}",
        family="materials_utils",
        engine="ase_materials",
        parameters={"operation": op, "formula": formula, "crystal_structure": cs},
        constraints=[Constraint(name="operation", value=op)],
    )


_REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(
        name="ase_si_bulk_volume",
        engine="ase_materials",
        description="Silicon FCC conventional cell volume ~160 Å³ (4-atom cell)",
        citation="ASE built-in, NIST Si lattice constant 5.431 Å",
        intent=_mat_intent("build_bulk", "Si", "diamond", "Si diamond bulk"),
        tolerances=[ToleranceSpec(quantity_name="n_atoms", expected_value=8, rtol=0.0, atol=0.5)],
    ),
    ReferenceCase(
        name="ase_h2o_molecule_atoms",
        engine="ase_materials",
        description="H2O molecule has 3 atoms",
        citation="ASE build.molecule('H2O')",
        intent=_mat_intent("build_molecule", "H2O", "", "H2O molecule build"),
        tolerances=[ToleranceSpec(quantity_name="n_atoms", expected_value=3, rtol=0.0, atol=0.5)],
    ),
]
