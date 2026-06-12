"""Individual validation layer implementations.

Layers 1-3 run before execution; layer 5 runs after.
Layers 4, 6, 7 are handled elsewhere (pre-flight per-engine, reference-case
regression in eval/runner.py, and interpretation grounding in interpret/).
"""

from __future__ import annotations

import math

from pydantic import ValidationError

from render.registry.protocol import EngineAdapter
from render.types import Intent, ResultBundle, ValidationReport
from render.validate.regime import RegimeSpec, check_regime

# ── Physical constraint names that must be strictly positive ──────────────────

_POSITIVE_FIELDS = frozenset(
    {
        "temperature",
        "temp",
        "T",
        "pressure",
        "P",
        "t_end",
        "time",
        "duration",
        "timestep",
        "dt",
        "n_atoms",
        "n_particles",
        "n_steps",
        "n_mols",
        "volume",
        "mass",
        "omega0",
        "frequency",
    }
)


# ── Layer 1: Pydantic schema ──────────────────────────────────────────────────


def layer1_schema(adapter: EngineAdapter, intent: Intent) -> ValidationReport | None:
    """Attempt to parse intent.parameters through the engine's intent_schema.

    Returns a failed ValidationReport if parsing fails, else None (pass).
    """
    schema_cls = adapter.intent_schema
    if schema_cls is None:
        return None
    try:
        schema_cls.model_validate(intent.parameters)
        return None
    except ValidationError as exc:
        errors = [
            str(e["msg"]) + f" (field: {'.'.join(str(p) for p in e['loc'])})" for e in exc.errors()
        ]
        return ValidationReport(passed=False, failed_layer=1, errors=errors)
    except Exception as exc:
        return ValidationReport(passed=False, failed_layer=1, errors=[str(exc)])


# ── Layer 2: Physical / dimensional constraints ───────────────────────────────


def layer2_physics(intent: Intent) -> ValidationReport | None:
    """Check universal physical constraints on named parameters.

    Works from both intent.parameters and intent.constraints so that either
    source of field values is caught.
    """
    errors: list[str] = []

    # Collect candidate values from both parameters dict and constraints list
    candidates: dict[str, float] = {}
    for field, val in intent.parameters.items():
        try:
            candidates[field] = float(val)
        except (TypeError, ValueError):
            pass
    for c in intent.constraints:
        try:
            candidates[c.name] = float(c.value)
        except (TypeError, ValueError):
            pass

    for field, val in candidates.items():
        if field in _POSITIVE_FIELDS and val <= 0:
            errors.append(f"Physical constraint violated: '{field}' = {val} must be > 0.")

    if errors:
        return ValidationReport(passed=False, failed_layer=2, errors=errors)
    return None


# ── Layer 3: In-regime check ──────────────────────────────────────────────────


def layer3_regime(adapter: EngineAdapter, intent: Intent) -> ValidationReport | None:
    """Check that the intent parameters fall within the adapter's regime envelope.

    If the adapter has no ``regime`` attribute, this layer passes silently.
    An out-of-regime request is not a hard failure — it returns a passed report
    with in_regime=False and a lowered confidence so the pipeline can proceed
    with a caveat rather than blocking the user outright.
    """
    regime: RegimeSpec | None = getattr(adapter, "regime", None)
    if regime is None:
        return None

    in_regime, messages = check_regime(intent.parameters, regime)
    if not in_regime:
        confidence = 0.5
        return ValidationReport(
            passed=True,
            in_regime=False,
            warnings=messages,
            confidence=confidence,
        )
    return None


# ── Layer 5: Post-run sanity ──────────────────────────────────────────────────


def layer5_postrun(bundle: ResultBundle) -> ValidationReport | None:
    """Check the ResultBundle for NaN/Inf values and convergence.

    Returns a failed ValidationReport if anything looks pathological,
    else None (pass).
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not bundle.converged:
        errors.append("Engine reported non-convergence. The result may be unreliable.")

    for qty in bundle.quantities:
        try:
            fval = float(qty.value)
        except (TypeError, ValueError):
            continue
        if math.isnan(fval):
            errors.append(f"Quantity '{qty.name}' is NaN.")
        elif math.isinf(fval):
            errors.append(f"Quantity '{qty.name}' is Inf.")
        elif abs(fval) > 1e30:
            warnings.append(
                f"Quantity '{qty.name}' = {fval:.3e} is unexpectedly large; "
                "check for numerical instability."
            )

    if errors:
        return ValidationReport(passed=False, failed_layer=5, errors=errors, warnings=warnings)
    if warnings:
        return ValidationReport(passed=True, warnings=warnings)
    return None
