#!/bin/bash
#SBATCH --job-name=render-certify-pyscf
#SBATCH --partition=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=8
#SBATCH --mem=32G
#SBATCH --time=01:00:00

set -euo pipefail

source "$HOME/.render_c2_env"

echo "=== PySCF certification — HF reference energies ==="
echo "Node: $(hostname)"
echo "Date: $(date)"

python - <<'EOF'
import json, pathlib, os, sys

OUT_DIR = pathlib.Path(os.environ.get("SLURM_SUBMIT_DIR", os.path.expanduser("~/.render_cert_jobs")))
OUT_DIR.mkdir(parents=True, exist_ok=True)

results = []

try:
    from render.engines.dft import PySCFAdapter
    from render.execute.local import run_local
    from render.types import Intent, Constraint

    adapter = PySCFAdapter()

    # Reference case 1: H2 HF/STO-3G — expected −1.1175 Ha
    intent1 = Intent(
        mode="simulation_explicit",
        question="H2 Hartree-Fock energy with STO-3G basis",
        family="dft",
        engine="pyscf_dft",
        parameters={
            "molecule": "H 0 0 0; H 0 0 0.74",
            "basis": "sto-3g",
            "method": "hf",
            "charge": 0,
            "spin": 0,
        },
        constraints=[],
    )

    m1 = run_local(adapter, intent1)
    qty = {q.name: q.value for q in m1.bundle.quantities}
    energy = float(qty.get("energy_hartree", qty.get("energy", 0)))
    expected = -1.1175
    passed1 = abs(energy - expected) / abs(expected) < 0.001
    results.append({
        "case": "H2_HF_STO3G",
        "passed": passed1,
        "engine_status": m1.engine_status,
        "energy_hartree": energy,
        "expected": expected,
        "rtol": abs(energy - expected) / abs(expected),
    })
    print(f"  Case 1 (H2 HF/STO-3G): {'PASS' if passed1 else 'FAIL'}")
    print(f"    energy = {energy:.6f} Ha  (expected {expected:.4f} Ha, rtol {results[-1]['rtol']:.4f})")

    # Reference case 2: H2O HF/STO-3G — expected ~−74.96 Ha
    intent2 = Intent(
        mode="simulation_explicit",
        question="H2O Hartree-Fock energy with STO-3G basis",
        family="dft",
        engine="pyscf_dft",
        parameters={
            "molecule": "O 0 0 0; H 0 0.757 0.586; H 0 -0.757 0.586",
            "basis": "sto-3g",
            "method": "hf",
            "charge": 0,
            "spin": 0,
        },
        constraints=[],
    )

    m2 = run_local(adapter, intent2)
    qty2 = {q.name: q.value for q in m2.bundle.quantities}
    energy2 = float(qty2.get("energy_hartree", qty2.get("energy", 0)))
    expected2 = -74.9659
    passed2 = abs(energy2 - expected2) / abs(expected2) < 0.01
    results.append({
        "case": "H2O_HF_STO3G",
        "passed": passed2,
        "engine_status": m2.engine_status,
        "energy_hartree": energy2,
        "expected": expected2,
        "rtol": abs(energy2 - expected2) / abs(expected2),
    })
    print(f"  Case 2 (H2O HF/STO-3G): {'PASS' if passed2 else 'FAIL'}")
    print(f"    energy = {energy2:.6f} Ha  (expected {expected2:.4f} Ha, rtol {results[-1]['rtol']:.4f})")

    all_passed = all(r["passed"] for r in results)
    print(f"\nPySCF certification: {'CERTIFIED' if all_passed else 'FAILED'}")

except ImportError as e:
    print(f"  PySCF not importable: {e}")
    print("  Install: pip install pyscf")
    results.append({"case": "import", "passed": False, "error": str(e)})
except Exception as e:
    import traceback
    print(f"  Error: {e}")
    traceback.print_exc()
    results.append({"case": "runtime", "passed": False, "error": str(e)})

(OUT_DIR / "certify_pyscf.json").write_text(json.dumps(results, indent=2))
print(f"\nResults written to {OUT_DIR}/certify_pyscf.json")

all_passed = all(r.get("passed", False) for r in results)
sys.exit(0 if all_passed else 1)
EOF

echo "=== Done at $(date) ==="
