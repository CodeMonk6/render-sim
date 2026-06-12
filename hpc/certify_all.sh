#!/usr/bin/env bash
# certify_all.sh — Submit all engine certification jobs to Slurm
#
# Usage (from hpc/ directory, with render_env active):
#   source ~/.render_c2_env
#   cd ~/render-sim/hpc
#   bash certify_all.sh [--partition general] [--account ""]
#
# Each job runs the engine's reference cases and writes a RunManifest JSON.
# After all jobs finish, run:
#   python collect_results.py
# to get the certification scorecard.
set -euo pipefail

PARTITION="${RENDER_PARTITION:-general-cpu}"
ACCOUNT="${RENDER_ACCOUNT:-compute2-workshop}"
JOB_DIR="$HOME/.render_cert_jobs"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --partition) PARTITION="$2"; shift 2 ;;
        --account)   ACCOUNT="$2";   shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

mkdir -p "$JOB_DIR"

submit() {
    local name="$1"
    local script="$2"
    local job_id
    job_id=$(sbatch \
        --partition="$PARTITION" \
        ${ACCOUNT:+--account="$ACCOUNT"} \
        --output="$JOB_DIR/${name}-%j.out" \
        --error="$JOB_DIR/${name}-%j.err" \
        "$script" 2>&1 | awk '{print $NF}')
    echo "  Submitted $name — job ID $job_id"
    echo "$job_id" > "$JOB_DIR/${name}.jobid"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "================================================================="
echo " Submitting Render engine certification jobs"
echo " Partition: $PARTITION"
echo " Output dir: $JOB_DIR"
echo "================================================================="
echo ""

submit "smoke_test"       "$SCRIPT_DIR/jobs/smoke_test.sbatch"
submit "certify_openmm"   "$SCRIPT_DIR/jobs/certify_openmm.sbatch"
submit "certify_lammps"   "$SCRIPT_DIR/jobs/certify_lammps.sbatch"
submit "certify_gromacs"  "$SCRIPT_DIR/jobs/certify_gromacs.sbatch"
submit "certify_pyscf"    "$SCRIPT_DIR/jobs/certify_pyscf.sbatch"
submit "certify_freebird" "$SCRIPT_DIR/jobs/certify_freebird.sbatch"

echo ""
echo "All jobs submitted. Monitor with:"
echo "  squeue -u \$USER"
echo ""
echo "When all jobs are COMPLETED, collect results with:"
echo "  source ~/.render_c2_env"
echo "  python $SCRIPT_DIR/collect_results.py --job-dir $JOB_DIR"
