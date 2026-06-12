#!/bin/bash
#SBATCH --job-name=render-certify-lammps
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

echo "=== LAMMPS certification — LJ argon reference cases ==="
echo "Node: $(hostname)"
echo "Date: $(date)"

# Try to load LAMMPS module; fall back to conda-installed lmp
ml load LAMMPS 2>/dev/null || true

# If lmp is in PATH from module, expose it
if command -v lmp_mpi &>/dev/null && ! command -v lmp &>/dev/null; then
    export GMX_CMD="lmp_mpi"
fi

python - <<'EOF'
import json, pathlib, os, sys

OUT_DIR = pathlib.Path(os.environ.get("SLURM_SUBMIT_DIR", os.path.expanduser("~/.render_cert_jobs")))
OUT_DIR.mkdir(parents=True, exist_ok=True)

results = []

try:
    from render.engines.lammps import LAMMPSAdapter
    from render.execute.local import run_local
    from render.types import Intent, Constraint

    adapter = LAMMPSAdapter()

    # Reference case 1: LJ argon at 85K — density should be ~1.4 g/cm³
    intent1 = Intent(
        mode="simulation_explicit",
        question="LAMMPS LJ argon at 85K 1atm, check liquid density",
        family="md",
        engine="lammps_md",
        parameters={
            "system": "lj_argon",
            "n_atoms": 500,
            "temperature": 85.0,
            "pressure": 1.0,
            "epsilon": 0.2379,
            "sigma": 3.405,
            "mass": 39.948,
            "n_steps": 10000,
            "timestep_fs": 2.0,
            "ensemble": "NPT",
        },
        constraints=[Constraint(name="temperature", value=85.0)],
    )

    m1 = run_local(adapter, intent1)
    results.append({
        "case": "lj_argon_85K",
        "passed": m1.validation.passed,
        "engine_status": m1.engine_status,
        "quantities": {q.name: q.value for q in m1.bundle.quantities},
    })
    print(f"  Case 1 (LJ argon 85K): {'PASS' if m1.validation.passed else 'FAIL'}")
    for q in m1.bundle.quantities:
        print(f"    {q.name} = {q.value}")

    # Reference case 2: LJ argon at 120K — gas phase, low density
    intent2 = intent1.model_copy(update={
        "question": "LAMMPS LJ argon at 120K — gas phase",
        "parameters": {**intent1.parameters, "temperature": 120.0},
        "constraints": [Constraint(name="temperature", value=120.0)],
    })

    m2 = run_local(adapter, intent2)
    results.append({
        "case": "lj_argon_120K",
        "passed": m2.validation.passed,
        "engine_status": m2.engine_status,
        "quantities": {q.name: q.value for q in m2.bundle.quantities},
    })
    print(f"  Case 2 (LJ argon 120K): {'PASS' if m2.validation.passed else 'FAIL'}")
    for q in m2.bundle.quantities:
        print(f"    {q.name} = {q.value}")

    all_passed = all(r["passed"] for r in results)
    print(f"\nLAMMPS certification: {'CERTIFIED' if all_passed else 'FAILED'}")

except ImportError as e:
    print(f"  LAMMPS not importable: {e}")
    print("  Install: conda install -c conda-forge lammps")
    print("  Or:      ml avail 2>&1 | grep -i lammps")
    results.append({"case": "import", "passed": False, "error": str(e)})
except Exception as e:
    import traceback
    print(f"  Error: {e}")
    traceback.print_exc()
    results.append({"case": "runtime", "passed": False, "error": str(e)})

(OUT_DIR / "certify_lammps.json").write_text(json.dumps(results, indent=2))
print(f"\nResults written to {OUT_DIR}/certify_lammps.json")

all_passed = all(r.get("passed", False) for r in results)
sys.exit(0 if all_passed else 1)
EOF

echo "=== Done at $(date) ==="
