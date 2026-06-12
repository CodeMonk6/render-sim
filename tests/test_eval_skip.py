"""The eval gate must treat a missing backend as SKIPPED, not FAILED.

A CI runner without PySCF/OpenMM/Julia/LAMMPS can't run those engines — that's
an environment limitation, not a reference-case regression, so it must not turn
the eval gate red. A genuine tolerance miss still fails.
"""

from __future__ import annotations

import pytest

from render.engines.reference import HarmonicOscillatorAdapter
from render.eval.runner import _is_missing_backend, eval_engine, run_reference_case


@pytest.fixture()
def adapter() -> HarmonicOscillatorAdapter:
    return HarmonicOscillatorAdapter()


@pytest.mark.parametrize(
    "msg",
    [
        "gillespy2 not installed. Run: pip install gillespy2",
        "OpenMM not installed",
        "LAMMPS not found. module load LAMMPS on Compute2",
        "Package FreeBird not installed in the current environment",
        "No module named 'pyscf'",
    ],
)
def test_missing_backend_detected(msg: str) -> None:
    assert _is_missing_backend(msg) is True


def test_real_failure_not_treated_as_missing() -> None:
    assert _is_missing_backend("Tolerance failure for energy: got 1.0, expected 2.0") is False


def test_missing_backend_is_skipped_not_failed(adapter, monkeypatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("OpenMM not installed. Install via: pip install openmm")

    monkeypatch.setattr(adapter, "run", boom)
    report = eval_engine(adapter)
    assert report.total >= 2
    assert report.skipped == report.total
    assert report.failed == 0
    assert report.ok is True  # gate stays green


def test_genuine_tolerance_failure_still_fails(adapter) -> None:
    case = adapter.reference_cases[0]
    # Move the expected value far from the true result so the tolerance check
    # fails (models are frozen, so rebuild via model_copy rather than mutate).
    bad_tol = case.tolerances[0].model_copy(
        update={
            "expected_value": case.tolerances[0].expected_value + 1e6,
            "rtol": 1e-9,
            "atol": 0.0,
        }
    )
    bad = case.model_copy(update={"tolerances": [bad_tol]})
    result = run_reference_case(adapter, bad)
    assert result.passed is False
    assert result.skipped is False
