#!/usr/bin/env bash
# check_modules.sh — Report what simulation software is available on Compute2
#
# Run on a login node: bash check_modules.sh
# Produces a summary of which Render engines can be loaded from modules.
set -uo pipefail

echo "================================================================="
echo " Render Engine Availability Report — WashU Compute2"
echo " $(date)"
echo "================================================================="
echo ""

check_module() {
    local label="$1"
    local pattern="$2"
    local found
    found=$(ml avail 2>&1 | grep -iE "$pattern" | head -3 | sed 's/^ */    /')
    if [[ -n "$found" ]]; then
        echo "  [FOUND]   $label"
        echo "$found"
    else
        echo "  [ABSENT]  $label — not in module system (use conda install)"
    fi
}

check_cmd() {
    local label="$1"
    local cmd="$2"
    if command -v "$cmd" &>/dev/null; then
        local ver
        ver=$("$cmd" --version 2>&1 | head -1) || ver="(version unknown)"
        echo "  [FOUND]   $label — $ver"
    else
        echo "  [ABSENT]  $label — not in PATH"
    fi
}

echo "--- Lmod modules ---"
check_module "LAMMPS"   "lammps"
check_module "GROMACS"  "gromacs"
check_module "OpenMM"   "openmm"
check_module "PySCF"    "pyscf"
check_module "Julia"    "julia"
check_module "FEniCSx"  "fenics|dolfinx"
check_module "Meep"     "meep|pymeep"
check_module "Anaconda" "anaconda|miniconda"
check_module "Python3"  "python3|python/3"

echo ""
echo "--- PATH commands ---"
check_cmd "conda"   "conda"
check_cmd "mamba"   "mamba"
check_cmd "python3" "python3"
check_cmd "julia"   "julia"
check_cmd "lmp"     "lmp"
check_cmd "gmx"     "gmx"
check_cmd "gmx_mpi" "gmx_mpi"

echo ""
echo "--- Slurm partitions ---"
sinfo -o "%P %a %l %D %t" 2>/dev/null || echo "  sinfo not available"

echo ""
echo "--- Current environment ---"
echo "  USER:   ${USER:-unknown}"
echo "  HOME:   ${HOME:-unknown}"
echo "  PWD:    $(pwd)"
echo "  Loaded modules:"
ml list 2>&1 | sed 's/^/    /'

echo ""
echo "================================================================="
echo " Copy this output and share with the Render setup script."
echo "================================================================="
