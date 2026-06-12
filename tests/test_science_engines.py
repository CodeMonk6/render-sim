"""Reference-case certification tests for the TWAIN flagship science engines.

These validate the grant's chemistry / biophysics / materials workflows against
literature values. Each guards on its backend so CI without the heavy scientific
stack still passes; when the backend is installed, the reference cases must pass
within tolerance (the gate that makes the engine Certified).
"""

from __future__ import annotations

import os

import pytest

from render.eval.runner import eval_engine


def test_pyscf_dft_reference_cases():
    """Chemistry: H2 & H2O HF/STO-3G energies match textbook values."""
    pytest.importorskip("pyscf")
    from render.engines.dft import PySCFAdapter

    adapter = PySCFAdapter()
    assert adapter.status == "certified"
    report = eval_engine(adapter)
    assert report.ok, [c.failures for c in report.cases if not c.passed]
    assert report.passed == report.total


def test_ase_materials_reference_cases():
    """Materials: Si conventional cell (8 atoms) and H2O molecule (3 atoms)."""
    pytest.importorskip("ase")
    from render.engines.materials_utils import ASEAdapter

    adapter = ASEAdapter()
    assert adapter.status == "certified"
    report = eval_engine(adapter)
    assert report.ok, [c.failures for c in report.cases if not c.passed]


@pytest.mark.slow
def test_openmm_argon_smoke():
    """Biophysics/MD: a short LJ-argon NPT run yields a physical liquid density."""
    pytest.importorskip("openmm")
    from render.engines.md import _simulate_argon

    res = _simulate_argon(T=85.0, n_steps=4000, dt_fs=4.0, seed=1)
    rho = res["density_g_cm3"]
    assert rho is not None and 1.0 < rho < 1.8, f"unphysical argon density {rho}"
    assert res["series"]["y"][0]["values"], "expected a density series for plotting"


def test_md_adapter_certified_with_reference_cases():
    """The MD adapter is Certified and carries reference cases (registry invariant)."""
    from render.engines.md import OpenMMAdapter

    adapter = OpenMMAdapter()
    assert adapter.status == "certified"
    assert len(adapter.reference_cases) >= 2


@pytest.mark.slow
def test_freebird_reference_cases():
    """Materials/atomistic MC: LJ well depth = -ε via real FreeBird.jl.

    Opt-in (runs the Julia subprocess, ~15s): set RENDER_TEST_JULIA=1.
    """
    if not os.environ.get("RENDER_TEST_JULIA"):
        pytest.skip("set RENDER_TEST_JULIA=1 to run the FreeBird.jl (Julia) certification test")
    from render.engines.freebird import FreeBirdAdapter, _julia_exe

    if _julia_exe() is None:
        pytest.skip("Julia not installed")
    adapter = FreeBirdAdapter()
    assert adapter.status == "certified"
    report = eval_engine(adapter)
    assert report.ok, [c.failures for c in report.cases if not c.passed]


def test_freebird_adapter_certified_with_reference_cases():
    """FreeBird adapter is Certified and carries reference cases (no Julia needed)."""
    from render.engines.freebird import FreeBirdAdapter

    adapter = FreeBirdAdapter()
    assert adapter.status == "certified"
    assert len(adapter.reference_cases) >= 2
