#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# c2_go.sh — one-command Render bootstrap for WashU Compute2.
#
# Run it on a C2 login node (in your interactive Duo-authenticated shell):
#
#   curl -fsSL https://raw.githubusercontent.com/CodeMonk6/render-sim/main/hpc/c2_go.sh | bash
#
# Clones (or updates) the repo, installs the conda env + engines into storage,
# then submits the certification jobs.  No API key needed — certification runs
# fixed reference cases deterministically; only the NL web UI uses an LLM.
# -----------------------------------------------------------------------------
set -uo pipefail

echo "================================================================="
echo " Render · Compute2 bootstrap"
echo "================================================================="

# Initialize the RIS module system for non-interactive shells.
source /etc/profile >/dev/null 2>&1 || true
ml load ris >/dev/null 2>&1 || true

REPO="$HOME/render-sim"
if [ -d "$REPO/.git" ]; then
    echo "==> Updating existing repo at $REPO"
    git -C "$REPO" pull --ff-only || echo "    (pull skipped)"
else
    echo "==> Cloning repo to $REPO"
    git clone https://github.com/CodeMonk6/render-sim.git "$REPO"
fi

echo ""
echo "==> Running setup (conda env + engines into storage — this takes a while)"
bash "$REPO/hpc/setup_render_c2.sh" "$REPO"

echo ""
echo "==> Submitting certification jobs"
# shellcheck disable=SC1091
source "$HOME/.render_c2_env" 2>/dev/null || true
bash "$REPO/hpc/certify_all.sh"

echo ""
echo "==> Current queue:"
squeue --me 2>/dev/null || true

echo ""
echo "================================================================="
echo " Submitted. Monitor:   squeue --me"
echo " Collect results:      python $REPO/hpc/collect_results.py"
echo "================================================================="
