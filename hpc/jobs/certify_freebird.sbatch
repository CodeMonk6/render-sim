#!/bin/bash
#SBATCH --job-name=render-certify-freebird
#SBATCH --partition=general-cpu
#SBATCH --account=compute2-workshop
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=4
#SBATCH --mem=16G
#SBATCH --time=01:30:00

set -euo pipefail

source /etc/profile >/dev/null 2>&1
ml load ris >/dev/null 2>&1
source "$HOME/.render_c2_env"

echo "=== FreeBird.jl certification — LJ argon MC ==="
echo "Node: $(hostname)"
echo "Date: $(date)"

# Install Julia if not present
if ! command -v julia &>/dev/null; then
    ml load julia 2>/dev/null || {
        echo "Julia not found — installing via juliaup"
        curl -fsSL https://install.julialang.org | sh -s -- --yes
        export PATH="$HOME/.juliaup/bin:$PATH"
    }
fi

echo "Julia: $(julia --version 2>/dev/null || echo 'not found')"

# Pre-install FreeBird.jl and juliacall if not present
if command -v julia &>/dev/null; then
    julia --quiet -e '
        using Pkg
        Pkg.add(["FreeBird", "JSON"])
    ' 2>&1 || echo "WARNING: Julia package install failed"

    # Install juliacall Python bridge
    pip install juliacall 2>/dev/null || true
fi

python - <<'EOF'
import json, pathlib, os, sys

OUT_DIR = pathlib.Path(os.environ.get("SLURM_SUBMIT_DIR", os.path.expanduser("~/.render_cert_jobs")))
OUT_DIR.mkdir(parents=True, exist_ok=True)

results = []

try:
    from render.engines.freebird import FreeBirdAdapter
    from render.execute.local import run_local
    from render.types import Intent, Constraint

    adapter = FreeBirdAdapter()

    # Reference case: LJ argon Monte Carlo at 100K
    # Expected: system reaches thermal equilibrium, energy < 0
    intent1 = Intent(
        mode="simulation_explicit",
        question="FreeBird.jl LJ argon MC at 100K",
        family="freebird",
        engine="freebird_mc",
        parameters={
            "system": "lj_argon",
            "n_atoms": 64,
            "temperature": 100.0,
            "n_steps": 10000,
            "box_length": 17.0,
            "epsilon": 0.2379,
            "sigma": 3.405,
        },
        constraints=[Constraint(name="temperature", value=100.0)],
    )

    m1 = run_local(adapter, intent1)
    results.append({
        "case": "lj_argon_100K_mc",
        "passed": m1.validation.passed,
        "engine_status": m1.engine_status,
        "quantities": {q.name: q.value for q in m1.bundle.quantities},
    })
    print(f"  Case 1 (LJ argon 100K MC): {'PASS' if m1.validation.passed else 'FAIL'}")
    for q in m1.bundle.quantities:
        print(f"    {q.name} = {q.value}")

    all_passed = all(r["passed"] for r in results)
    print(f"\nFreeBird certification: {'CERTIFIED' if all_passed else 'FAILED'}")

except ImportError as e:
    print(f"  FreeBird not importable: {e}")
    print("  Julia + juliacall needed. Install:")
    print("    pip install juliacall")
    print("    julia -e 'using Pkg; Pkg.add(\"FreeBird\")'")
    results.append({"case": "import", "passed": False, "error": str(e)})
except Exception as e:
    import traceback
    print(f"  Error: {e}")
    traceback.print_exc()
    results.append({"case": "runtime", "passed": False, "error": str(e)})

(OUT_DIR / "certify_freebird.json").write_text(json.dumps(results, indent=2))
print(f"\nResults written to {OUT_DIR}/certify_freebird.json")

all_passed = all(r.get("passed", False) for r in results)
sys.exit(0 if all_passed else 1)
EOF

echo "=== Done at $(date) ==="
