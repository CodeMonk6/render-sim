#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# setup_render_c2.sh — Bootstrap Render on WashU Compute2
#
# Run this script ONCE on a Compute2 login node (or an OOD terminal).
# It will:
#   1. Install Miniconda3 into ~/miniconda3 (if conda not already available)
#   2. Create the `render_env` conda environment with all Python dependencies
#   3. Install heavy simulation engines (LAMMPS, GROMACS, OpenMM, PySCF)
#   4. Install Render in editable mode from ~/render-sim (or wherever this
#      repo is cloned)
#   5. Write ~/.render_c2_env so you can activate at any time with:
#        source ~/.render_c2_env
#
# Usage:
#   bash setup_render_c2.sh [/path/to/render-sim-repo]
#
# If no repo path is given, ~/render-sim is used as the default.
# -----------------------------------------------------------------------------
set -euo pipefail

# Initialize the RIS module system (Lmod) for non-interactive shells, per the
# RIS Compute2 guide.  Without this, `ml`/conda/Slurm are unavailable over SSH.
source /etc/profile >/dev/null 2>&1 || true
ml load ris >/dev/null 2>&1 || true

REPO_DIR="${1:-$HOME/render-sim}"

# CRITICAL (RIS guide §3): /home is a small ~47G mount — never build conda envs
# or package caches there.  Everything heavy lives under a storage allocation.
# Override with RENDER_C2_WORKSPACE; defaults to the DTRC workshop space.
WORKSPACE="${RENDER_C2_WORKSPACE:-/storage2/fs1/mdan/Active/dtrc2026-workshop/users/$USER/render-c2}"
ENV_PREFIX="$WORKSPACE/envs/render_env"
export CONDA_PKGS_DIRS="$WORKSPACE/.conda/pkgs"
CONDA_BASE=""

mkdir -p "$WORKSPACE" "$CONDA_PKGS_DIRS"
echo "==> Workspace (storage, not home): $WORKSPACE"

# ── Step 1: locate or install conda ──────────────────────────────────────────

echo "==> Checking for conda..."

if command -v conda &>/dev/null; then
    CONDA_BASE="$(conda info --base)"
    echo "    Found conda at: $CONDA_BASE"
elif command -v mamba &>/dev/null; then
    CONDA_BASE="$(mamba info --base)"
    echo "    Found mamba at: $CONDA_BASE"
else
    echo "    conda not found — installing Miniconda3 into $WORKSPACE/conda (storage)"
    MINICONDA_INSTALLER="$WORKSPACE/Miniconda3-latest-Linux-x86_64.sh"
    if [[ ! -f "$MINICONDA_INSTALLER" ]]; then
        curl -fsSL \
            "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh" \
            -o "$MINICONDA_INSTALLER"
    fi
    bash "$MINICONDA_INSTALLER" -b -p "$WORKSPACE/conda"
    rm -f "$MINICONDA_INSTALLER"
    CONDA_BASE="$WORKSPACE/conda"
    echo "    Miniconda3 installed at $CONDA_BASE"
fi

# Source conda so this shell can use it
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"

# ── Step 2: create render_env (prefix env in storage) ─────────────────────────

echo ""
echo "==> Creating conda environment at '$ENV_PREFIX' (Python 3.11)..."

if [[ -d "$ENV_PREFIX" ]]; then
    echo "    Environment already exists at $ENV_PREFIX — updating."
else
    conda create -y -p "$ENV_PREFIX" python=3.11
fi

conda activate "$ENV_PREFIX"

# ── Step 3: install Python deps ───────────────────────────────────────────────

echo ""
echo "==> Installing core Python packages via pip..."

pip install --upgrade pip

# Core Render dependencies
pip install \
    "pydantic>=2.0" \
    "instructor>=1.0" \
    "anthropic>=0.30" \
    "pint>=0.24" \
    "scipy>=1.13" \
    "numpy>=1.26" \
    "matplotlib>=3.9" \
    "typer>=0.12" \
    "click>=8.1" \
    "fastapi>=0.111" \
    "uvicorn[standard]>=0.30" \
    "httpx>=0.27" \
    "rich>=13.0" \
    "pytest>=8.0" \
    "pytest-cov>=5.0" \
    "ruff>=0.5"

# Tier-A simulation engines (pure-Python, always install)
pip install \
    "ase>=3.23" \
    "pymatgen>=2024.6" \
    "gillespy2>=1.8" \
    "simpy>=4.1" \
    "mesa>=2.3" \
    "emcee>=3.1" \
    "rebound>=4.2" \
    "tellurium>=2.2" \
    "pyscf>=2.5"

# ── Step 4: install heavy engines via conda-forge ─────────────────────────────

echo ""
echo "==> Installing heavy simulation engines via conda-forge..."

# OpenMM (most reliable via conda-forge)
echo "    OpenMM..."
conda install -y -c conda-forge openmm || {
    echo "    WARNING: openmm conda install failed — trying pip fallback"
    pip install openmm || echo "    SKIP openmm (install manually)"
}

# LAMMPS (lammps Python package via conda-forge)
echo "    LAMMPS..."
conda install -y -c conda-forge lammps || {
    echo "    WARNING: lammps conda install failed"
    echo "    Try: conda install -c conda-forge lammps"
    echo "    Or:  ml load LAMMPS && export LAMMPS_MODULE=1"
}

# GROMACS (gromacs-mpi via conda-forge)
echo "    GROMACS..."
conda install -y -c conda-forge gromacs || {
    echo "    WARNING: gromacs conda install failed"
    echo "    Try: ml avail 2>&1 | grep -i gromacs"
    echo "    Or:  conda install -c conda-forge gromacs"
}

# FEniCSx (FEM)
echo "    FEniCSx (FEM)..."
conda install -y -c conda-forge fenics-dolfinx || {
    echo "    SKIP fenics-dolfinx (not critical for initial setup)"
}

# Meep (EM)
echo "    Meep (electrodynamics)..."
conda install -y -c conda-forge pymeep || {
    echo "    SKIP pymeep (not critical for initial setup)"
}

# ── Step 5: install Render itself ─────────────────────────────────────────────

echo ""
echo "==> Installing Render from $REPO_DIR..."

if [[ ! -d "$REPO_DIR" ]]; then
    echo "    Repo not found at $REPO_DIR"
    echo "    Clone it first: git clone <your-render-repo-url> $REPO_DIR"
    echo "    Then re-run this script."
    exit 1
fi

pip install -e "$REPO_DIR"

# ── Step 6: write the activation env file ─────────────────────────────────────

ENV_FILE="$HOME/.render_c2_env"
cat > "$ENV_FILE" <<ENVBLOCK
# Render — Compute2 environment activation
# Source this file: source ~/.render_c2_env

source /etc/profile >/dev/null 2>&1 || true
ml load ris >/dev/null 2>&1 || true

export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS}"
source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate ${ENV_PREFIX}

# Load API key from ~/.render_secrets if it exists
if [[ -f "\$HOME/.render_secrets" ]]; then
    source "\$HOME/.render_secrets"
fi

# Warn if no key is set
if [[ -z "\${OPENROUTER_API_KEY:-}" && -z "\${ANTHROPIC_API_KEY:-}" ]]; then
    echo "WARNING: No LLM API key found."
    echo "  Add your OpenRouter key:"
    echo "    echo 'export OPENROUTER_API_KEY=sk-or-v1-...' >> ~/.render_secrets"
    echo "    chmod 600 ~/.render_secrets"
fi

export RENDER_PARTITION="general-cpu"
export RENDER_ACCOUNT="compute2-workshop"
export RENDER_REPO="${REPO_DIR}"
export RENDER_C2_WORKSPACE="${WORKSPACE}"
ENVBLOCK

chmod 600 "$ENV_FILE"

# ── Step 7: prompt for API key ────────────────────────────────────────────────

echo ""
if [[ -z "${OPENROUTER_API_KEY:-}" && -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "==> No LLM API key set."
    echo "    Add your OpenRouter key to ~/.render_secrets:"
    echo ""
    echo "      echo 'export OPENROUTER_API_KEY=sk-or-v1-...' >> ~/.render_secrets"
    echo "      chmod 600 ~/.render_secrets"
    echo ""
else
    echo "==> LLM API key found (${OPENROUTER_API_KEY:+OpenRouter}${ANTHROPIC_API_KEY:+Anthropic})."
fi

# ── Step 8: smoke test ────────────────────────────────────────────────────────

echo ""
echo "==> Running smoke test (no API key needed)..."
python - <<'PYCHECK'
from render.engines.reference import HarmonicOscillatorAdapter
from render.execute.local import run_local
from render.types import Intent, Constraint
intent = Intent(
    mode="simulation_explicit", question="smoke test",
    family="ode", engine="harmonic_oscillator",
    parameters={"omega0": 1.0, "x0": 1.0, "v0": 0.0, "zeta": 0.0,
                "t_end": 6.28318, "n_points": 10},
    constraints=[Constraint(name="omega0", value=1.0)],
)
m = run_local(HarmonicOscillatorAdapter(), intent)
assert m.validation.passed, "validation failed"
print("  Smoke test PASSED — render_env is working.")
PYCHECK

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "================================================================="
echo " Setup complete!"
echo ""
echo " To activate Render in any future session:"
echo "   source ~/.render_c2_env"
echo ""
echo " To run the full certification suite:"
echo "   source ~/.render_c2_env"
echo "   cd $REPO_DIR/hpc"
echo "   bash certify_all.sh"
echo ""
echo " To start the web UI (on a login node or OOD session):"
echo "   source ~/.render_c2_env"
echo "   render serve --host 0.0.0.0 --port 8000"
echo "================================================================="
