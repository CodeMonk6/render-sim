"""Number-grounding check for interpreter outputs.

The interpreter may ONLY cite quantities present in the ResultBundle.
This module detects fabricated numbers in a generated text string.
"""

from __future__ import annotations

import re

from render.types import ResultBundle, ValidationReport


def ground_check(text: str, bundle: ResultBundle) -> ValidationReport:
    """Verify that every number cited in *text* exists in *bundle*.

    Strategy: extract numeric-looking tokens from the text (e.g. "6.28",
    "2.3e-4") and check each one against the bundle quantities.  A token is
    considered grounded if it matches (within 1 %) the value of at least one
    quantity in the bundle, OR if it appears verbatim as a quantity value.

    Returns a ValidationReport with layer=7; passed=False lists fabrications.
    """
    numbers = _extract_numbers(text)
    bundle_values = {q.name: _to_float(q.value) for q in bundle.quantities}
    bundle_floats = [v for v in bundle_values.values() if v is not None]

    fabricated: list[str] = []
    for tok in numbers:
        fval = _to_float(tok)
        if fval is None:
            continue
        if _is_grounded(fval, bundle_floats):
            continue
        fabricated.append(tok)

    if fabricated:
        return ValidationReport(
            passed=False,
            failed_layer=7,
            errors=[
                f"Interpreter cited numbers not found in ResultBundle: "
                f"{', '.join(fabricated[:5])}"
            ],
            warnings=[],
            confidence=0.0,
        )
    return ValidationReport(passed=True)


def _extract_numbers(text: str) -> list[str]:
    pattern = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
    return re.findall(pattern, text)


def _to_float(val: object) -> float | None:
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _is_grounded(val: float, bundle_floats: list[float], rtol: float = 0.01) -> bool:
    if not bundle_floats:
        return False
    for bv in bundle_floats:
        if bv == 0.0 and abs(val) < 1e-10:
            return True
        if bv != 0.0 and abs(val - bv) / abs(bv) <= rtol:
            return True
    return False
