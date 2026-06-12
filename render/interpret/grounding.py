"""Number-grounding check for interpreter outputs.

The interpreter may ONLY cite quantities present in the ResultBundle.
This module detects fabricated numbers in a generated text string.
"""

from __future__ import annotations

import re

from render.types import ResultBundle, ValidationReport


def ground_check(text: str, bundle: ResultBundle) -> ValidationReport:
    """Verify that the *data* numbers cited in *text* exist in *bundle*.

    Purpose (validation layer 7): catch the interpreter inventing fake result
    values — e.g. reporting an energy of -5.2 Ha when the run produced -1.1.
    It must NOT trip over the ordinary numbers that appear in plain-language
    prose, so before checking we:

      * strip thousands separators ("20,165" → "20165") so a single value is
        not split into "20" and "165";
      * ignore citation years (integers in 1500-2100);
      * ignore small contextual integers (|n| < 32 — counts, "the first 7 days",
        "3 compartments") which are descriptive, not fabricated data.

    A remaining token (a decimal, or an integer ≥ 32) is grounded if it matches
    a bundle quantity within 2 %. Anything left over is a real fabrication.
    """
    numbers = _extract_numbers(text)
    bundle_values = {q.name: _to_float(q.value) for q in bundle.quantities}
    bundle_floats = [v for v in bundle_values.values() if v is not None]

    fabricated: list[str] = []
    for tok in numbers:
        fval = _to_float(tok)
        if fval is None:
            continue
        is_int = abs(fval - round(fval)) < 1e-9
        # Skip benign prose numbers: citation years and small counting integers.
        if is_int and 1500 <= fval <= 2100:
            continue
        if is_int and abs(fval) < 32:
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
    # Drop thousands separators so "20,165" is one number, not "20" + "165".
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    pattern = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
    return re.findall(pattern, text)


def _to_float(val: object) -> float | None:
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _is_grounded(val: float, bundle_floats: list[float], rtol: float = 0.05) -> bool:
    if not bundle_floats:
        return False
    for bv in bundle_floats:
        if bv == 0.0 and abs(val) < 1e-10:
            return True
        if bv == 0.0:
            continue
        # Accept the value directly, as a fraction spoken as a percentage
        # (0.98 → "98%"), or rescaled by a common unit prefix (eV↔meV, s↔ms).
        for cand in (bv, bv * 100.0, bv / 100.0, bv * 1000.0, bv / 1000.0):
            if cand != 0.0 and abs(val - cand) / abs(cand) <= rtol:
                return True
    return False
