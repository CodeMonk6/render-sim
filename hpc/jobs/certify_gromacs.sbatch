#!/bin/bash
#SBATCH --job-name=render-certify-gromacs
#SBATCH --partition=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00

set -euo pipefail

source "$HOME/.render_c2_env"

echo "=== GROMACS certification ==="
echo "Node: $(hostname)"
echo "Date: $(date)"

# Try module; then conda; then PATH
ml load GROMACS 2>/dev/null || true

# Prefer gmx_mpi if available
if command -v gmx_mpi &>/dev/null; then
    export GMX_CMD="gmx_mpi"
elif command -v gmx &>/dev/null; then
    export GMX_CMD="gmx"
fi

python - <<'EOF'
import json, pathlib, os, sys

OUT_DIR = pathlib.Path(os.environ.get("SLURM_SUBMIT_DIR", os.path.expanduser("~/.render_cert_jobs")))
OUT_DIR.mkdir(parents=True, exist_ok=True)

results = []

try:
    from render.engines.gromacs import GROMACSAdapter
    from render.execute.local import run_local
    from render.types import Intent, Constraint

    adapter = GROMACSAdapter()

    # Reference case: water box SPC/E 300K NPT
    # Expected: density ~997 kg/m³ at 300K/1atm
    intent1 = Intent(
        mode="simulation_explicit",
        question="GROMACS SPC/E water at 300K 1atm — check density",
        family="md",
        engine="gromacs_md",
        parameters={
            "system": "water_box",
            "n_molecules": 216,
            "forcefield": "spce",
            "temperature": 300.0,
            "pressure": 1.0,
            "n_steps": 50000,
            "timestep_fs": 2.0,
            "ensemble": "NPT",
        },
        constraints=[Constraint(name="temperature", value=300.0)],
    )

    m1 = run_local(adapter, intent1)
    results.append({
        "case": "spce_water_300K",
        "passed": m1.validation.passed,
        "engine_status": m1.engine_status,
        "quantities": {q.name: q.value for q in m1.bundle.quantities},
    })
    print(f"  Case 1 (SPC/E water 300K): {'PASS' if m1.validation.passed else 'FAIL'}")
    for q in m1.bundle.quantities:
        print(f"    {q.name} = {q.value}")

    all_passed = all(r["passed"] for r in results)
    print(f"\nGROMACS certification: {'CERTIFIED' if all_passed else 'FAILED'}")

except ImportError as e:
    print(f"  GROMACS not importable: {e}")
    print("  Install: conda install -c conda-forge gromacs")
    print("  Or load the module: ml load GROMACS")
    results.append({"case": "import", "passed": False, "error": str(e)})
except Exception as e:
    import traceback
    print(f"  Error: {e}")
    traceback.print_exc()
    results.append({"case": "runtime", "passed": False, "error": str(e)})

(OUT_DIR / "certify_gromacs.json").write_text(json.dumps(results, indent=2))
print(f"\nResults written to {OUT_DIR}/certify_gromacs.json")

all_passed = all(r.get("passed", False) for r in results)
sys.exit(0 if all_passed else 1)
EOF

echo "=== Done at $(date) ==="
