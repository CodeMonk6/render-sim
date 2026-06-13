"""PySCF method-name aliasing: natural terms must map to canonical methods.

`validate()` only checks the normalized method against the allowed set, so these
tests run without the PySCF backend installed.
"""

from __future__ import annotations

import pytest

from render.engines.dft import PySCFAdapter, _normalize_method
from render.types import Intent


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("hartree_fock", "hf"),
        ("Hartree-Fock", "hf"),
        ("HARTREE FOCK", "hf"),
        ("RHF", "hf"),
        ("scf", "hf"),
        ("kohn-sham", "dft"),
        ("RKS", "dft"),
        ("ccsdt", "ccsd(t)"),
        ("hf", "hf"),
        ("dft", "dft"),
        ("nonsense", "nonsense"),  # unknown passes through, rejected in validate
    ],
)
def test_normalize_method(raw: str, expected: str) -> None:
    assert _normalize_method(raw) == expected


def _intent(method: str) -> Intent:
    return Intent(
        mode="simulation_explicit",
        question="q",
        engine="pyscf_dft",
        family="dft",
        parameters={"molecule": "H2", "method": method, "basis": "sto-3g"},
    )


def test_validate_accepts_natural_method_names() -> None:
    adapter = PySCFAdapter()
    assert adapter.validate(_intent("hartree_fock")).passed is True
    assert adapter.validate(_intent("Kohn-Sham")).passed is True


def test_validate_still_rejects_unknown_method() -> None:
    adapter = PySCFAdapter()
    assert adapter.validate(_intent("flux_capacitor")).passed is False
