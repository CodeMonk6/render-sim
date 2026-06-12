#!/bin/bash
#SBATCH --job-name=render-certify-openmm
#SBATCH --partition=general-cpu
#SBATCH --account=compute2-workshop
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00

set -euo pipefail

source /etc/profile >/dev/null 2>&1
ml load ris >/dev/null 2>&1
source "$HOME/.render_c2_env"

echo "=== OpenMM certification ==="
echo "Node: $(hostname)"
echo "Date: $(date)"

# Try to load OpenMM module if available; fall back to conda env
ml load OpenMM 2>/dev/null || true

python - <<'EOF'
import json, pathlib, os, sys

OUT_DIR = pathlib.Path(os.environ.get("SLURM_SUBMIT_DIR", os.path.expanduser("~/.render_cert_jobs")))
OUT_DIR.mkdir(parents=True, exist_ok=True)

results = []

try:
    from render.engines.md import OpenMMAdapter
    from render.execute.local import run_local
    from render.types import Intent, Constraint

    adapter = OpenMMAdapter()

    # Reference case 1: water dimer energy
    intent1 = Intent(
        mode="simulation_explicit",
        question="OpenMM water dimer energy minimization",
        family="md",
        engine="openmm_md",
        parameters={
            "system": "water",
            "n_molecules": 2,
            "forcefield": "tip3p",
            "temperature": 300.0,
            "pressure": 1.0,
            "n_steps": 1000,
            "timestep_fs": 2.0,
            "ensemble": "NVT",
        },
        constraints=[],
    )

    m1 = run_local(adapter, intent1)
    results.append({
        "case": "water_nvt",
        "passed": m1.validation.passed,
        "engine_status": m1.engine_status,
        "quantities": {q.name: q.value for q in m1.bundle.quantities},
    })
    print(f"  Case 1 (water NVT): {'PASS' if m1.validation.passed else 'FAIL'}")

    # Reference case 2: alanine dipeptide NVT
    intent2 = intent1.model_copy(update={
        "question": "OpenMM alanine dipeptide NVT at 300K",
        "parameters": {
            "system": "alanine_dipeptide",
            "forcefield": "amber14",
            "temperature": 300.0,
            "n_steps": 5000,
            "timestep_fs": 2.0,
            "ensemble": "NVT",
        },
    })
    m2 = run_local(adapter, intent2)
    results.append({
        "case": "alanine_nvt",
        "passed": m2.validation.passed,
        "engine_status": m2.engine_status,
        "quantities": {q.name: q.value for q in m2.bundle.quantities},
    })
    print(f"  Case 2 (alanine NVT): {'PASS' if m2.validation.passed else 'FAIL'}")

    all_passed = all(r["passed"] for r in results)
    print(f"\nOpenMM certification: {'CERTIFIED' if all_passed else 'FAILED'}")

except ImportError as e:
    print(f"  OpenMM not importable: {e}")
    results.append({"case": "import", "passed": False, "error": str(e)})
except Exception as e:
    print(f"  Error: {e}")
    results.append({"case": "runtime", "passed": False, "error": str(e)})

(OUT_DIR / "certify_openmm.json").write_text(json.dumps(results, indent=2))
print(f"\nResults written to {OUT_DIR}/certify_openmm.json")

all_passed = all(r.get("passed", False) for r in results)
sys.exit(0 if all_passed else 1)
EOF

echo "=== Done at $(date) ==="
