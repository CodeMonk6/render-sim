#!/bin/bash
#SBATCH --job-name=render-smoke
#SBATCH --partition=general-cpu
#SBATCH --account=compute2-workshop
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mem=4G
#SBATCH --time=00:10:00

set -euo pipefail

source /etc/profile >/dev/null 2>&1
ml load ris >/dev/null 2>&1
source "$HOME/.render_c2_env"

echo "=== Render smoke test ==="
echo "Node: $(hostname)"
echo "Date: $(date)"
echo "Python: $(python --version)"
echo "Render: $(render --version 2>/dev/null || python -c 'import render; print(render.__version__)')"
echo ""

python - <<'EOF'
from render.engines.reference import HarmonicOscillatorAdapter
from render.execute.local import run_local
from render.interpret import interpret
from render.types import Intent, Constraint

intent = Intent(
    mode="simulation_explicit",
    question="Harmonic oscillator omega0=1 x0=1 for one full period",
    family="ode",
    engine="harmonic_oscillator",
    parameters={"omega0": 1.0, "x0": 1.0, "v0": 0.0, "zeta": 0.0,
                "t_end": 6.28318, "n_points": 100},
    constraints=[Constraint(name="omega0", value=1.0)],
)

adapter = HarmonicOscillatorAdapter()
manifest = run_local(adapter, intent)

assert manifest.validation.passed, f"Validation failed: {manifest.validation.errors}"
assert manifest.engine_status == "certified"

for q in manifest.bundle.quantities:
    print(f"  {q.name} = {q.value}")

result = interpret(intent, manifest.bundle, manifest.validation,
                   engine_status="certified", api_key="x")
print(f"\nStatus badge: {result.status_badge}")
print(f"Confidence:   {result.confidence:.2f}")

import json, pathlib, os
out_dir = pathlib.Path(os.environ.get("SLURM_SUBMIT_DIR", "."))
(out_dir / "smoke_manifest.json").write_text(manifest.model_dump_json(indent=2))
print("\nSMOKE TEST PASSED")
EOF

echo ""
echo "=== Done at $(date) ==="
