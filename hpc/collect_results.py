#!/usr/bin/env python3
"""collect_results.py — Gather certification JSON files and print the scorecard.

Usage:
    python collect_results.py [--job-dir ~/.render_cert_jobs]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Render certification scorecard")
    ap.add_argument(
        "--job-dir",
        default=str(Path.home() / ".render_cert_jobs"),
        help="Directory where certification JSON files were written",
    )
    args = ap.parse_args()

    job_dir = Path(args.job_dir)

    engines = [
        ("smoke_test",       "smoke_manifest.json",   "Reference ODE (harmonic oscillator)"),
        ("certify_openmm",   "certify_openmm.json",   "OpenMM (molecular dynamics)"),
        ("certify_lammps",   "certify_lammps.json",   "LAMMPS (molecular dynamics)"),
        ("certify_gromacs",  "certify_gromacs.json",  "GROMACS (biomolecular MD)"),
        ("certify_pyscf",    "certify_pyscf.json",    "PySCF (DFT / electronic structure)"),
        ("certify_freebird", "certify_freebird.json", "FreeBird.jl (atomistic MC)"),
    ]

    print("=" * 70)
    print("  RENDER ENGINE CERTIFICATION SCORECARD")
    print(f"  Job dir: {job_dir}")
    print("=" * 70)

    total = 0
    certified = 0
    failed = 0
    missing = 0

    rows = []

    for _key, filename, label in engines:
        path = job_dir / filename
        if not path.exists():
            rows.append((label, "MISSING", "—", "file not found"))
            missing += 1
            total += 1
            continue

        try:
            data = json.loads(path.read_text())
        except Exception as exc:
            rows.append((label, "ERROR", "—", str(exc)[:60]))
            failed += 1
            total += 1
            continue

        # smoke_manifest.json is a RunManifest; others are lists of case dicts
        if isinstance(data, dict) and "validation" in data:
            passed = data["validation"].get("passed", False)
            cases = "1/1"
            note = ""
        elif isinstance(data, list):
            n_pass = sum(1 for r in data if r.get("passed", False))
            passed = n_pass == len(data) and len(data) > 0
            cases = f"{n_pass}/{len(data)}"
            fails = [r.get("case", "?") for r in data if not r.get("passed", False)]
            note = ", ".join(fails) if fails else ""
        else:
            passed = False
            cases = "?"
            note = "unexpected format"

        total += 1
        if passed:
            certified += 1
            tag = "CERTIFIED"
        else:
            failed += 1
            tag = "FAILED"
            candidates = data if isinstance(data, list) else []
            err = next((r.get("error", "") for r in candidates if r.get("error")), note)
            note = err[:60] if err else note

        rows.append((label, tag, cases, note))

    # Print table
    col_w = [50, 12, 8, 40]
    header = ("Engine", "Status", "Cases", "Notes")
    sep = "  ".join("-" * w for w in col_w)
    fmt = "  ".join(f"{{:<{w}}}" for w in col_w)

    print()
    print(fmt.format(*header))
    print(sep)
    for row in rows:
        tag = row[1]
        line = fmt.format(*[str(c)[:w] for c, w in zip(row, col_w)])
        if tag == "CERTIFIED":
            print(f"\033[32m{line}\033[0m")   # green
        elif tag == "FAILED":
            print(f"\033[31m{line}\033[0m")   # red
        elif tag == "MISSING":
            print(f"\033[33m{line}\033[0m")   # yellow
        else:
            print(line)

    print()
    print(f"  Summary: {certified}/{total} certified  |  {failed} failed  |  {missing} missing")
    print()

    if missing > 0:
        print("  TIP: Missing files mean the certification job hasn't run yet.")
        print("       Check with: squeue -u $USER")
        print("       Or the job's .out file in:", job_dir)
        print()

    sys.exit(0 if failed == 0 and missing == 0 else 1)


if __name__ == "__main__":
    main()
