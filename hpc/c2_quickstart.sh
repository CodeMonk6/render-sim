#!/usr/bin/env bash
# c2_quickstart.sh — One-shot Render setup for WashU Compute2
#
# Paste this ENTIRE block into your Compute2 OOD terminal and press Enter.
# It clones the repo, sets up the environment, and submits all certification
# jobs in one pass. Takes ~10 minutes.
#
# Prerequisites:
#   - You are logged in to Compute2 (OOD terminal or ssh c2-login-001.ris.wustl.edu)
#   - You have your ANTHROPIC_API_KEY ready
#   - The render-sim repo is accessible (git clone or scp from your Mac)
#
# Usage:
#   bash c2_quickstart.sh [REPO_URL_OR_PATH] [API_KEY]
#
# Example (if you've already scp'd the repo):
#   bash c2_quickstart.sh ~/render-sim sk-ant-...
#
# Example (from GitHub):
#   bash c2_quickstart.sh https://github.com/YOUR_USER/render-sim.git sk-ant-...

set -euo pipefail

REPO="${1:-$HOME/render-sim}"
API_KEY="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$HOME/render-sim/hpc")"

# ── 1. Clone repo if a URL was given ─────────────────────────────────────────
if [[ "$REPO" == https://* || "$REPO" == git@* ]]; then
    TARGET="$HOME/render-sim"
    if [[ -d "$TARGET" ]]; then
        echo "Repo already at $TARGET — pulling latest"
        git -C "$TARGET" pull
    else
        echo "Cloning $REPO → $TARGET"
        git clone "$REPO" "$TARGET"
    fi
    REPO="$TARGET"
    SCRIPT_DIR="$REPO/hpc"
fi

# ── 2. Store API key ──────────────────────────────────────────────────────────
if [[ -n "$API_KEY" ]]; then
    # Detect key type by prefix
    if [[ "$API_KEY" == sk-or-* ]]; then
        echo "export OPENROUTER_API_KEY=$API_KEY" > "$HOME/.render_secrets"
    else
        echo "export ANTHROPIC_API_KEY=$API_KEY" > "$HOME/.render_secrets"
    fi
    chmod 600 "$HOME/.render_secrets"
    echo "API key saved to ~/.render_secrets"
fi

# ── 3. Run full setup ─────────────────────────────────────────────────────────
bash "$SCRIPT_DIR/setup_render_c2.sh" "$REPO"

# ── 4. Submit certification jobs ──────────────────────────────────────────────
echo ""
echo "==> Submitting certification jobs..."
source "$HOME/.render_c2_env"
bash "$SCRIPT_DIR/certify_all.sh"

echo ""
echo "================================================================="
echo " Quickstart complete."
echo ""
echo " Check job status: squeue -u \$USER"
echo ""
echo " When all jobs finish (~30-60 min), run:"
echo "   source ~/.render_c2_env"
echo "   python $SCRIPT_DIR/collect_results.py"
echo ""
echo " To use Render interactively:"
echo "   source ~/.render_c2_env"
echo "   render ask 'What is the ground state energy of H2?'"
echo "================================================================="
