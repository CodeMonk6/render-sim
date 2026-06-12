"""Validation stack orchestrator.

pre_run_validate  — runs layers 1-3 before execution
post_run_validate — runs layer 5 after execution

Layer 4 (pre-flight dry-run) is per-engine and called by the runner.
Layers 6 and 7 live in eval/ and interpret/ respectively.
"""

from __future__ import annotations

from render.registry.protocol import EngineAdapter
from render.types import Intent, ResultBundle, ValidationReport
from render.validate.layers import layer1_schema, layer2_physics, layer3_regime, layer5_postrun


def _merge(base: ValidationReport, override: ValidationReport) -> ValidationReport:
    """Merge two reports: if override fails, fail; accumulate warnings."""
    return ValidationReport(
        passed=override.passed and base.passed,
        failed_layer=override.failed_layer if not override.passed else base.failed_layer,
        errors=base.errors + override.errors,
        warnings=base.warnings + override.warnings,
        in_regime=base.in_regime and override.in_regime,
        confidence=min(base.confidence, override.confidence),
    )


def pre_run_validate(adapter: EngineAdapter, intent: Intent) -> ValidationReport:
    """Run layers 1-3 (schema → physics → regime) in order.

    Stops at the first hard failure (non-passing report).
    Layer 3 never hard-fails — an out-of-regime request gets in_regime=False
    and a lowered confidence but is still runnable.
    """
    result = ValidationReport(passed=True)

    for layer_fn, args in [
        (layer1_schema, (adapter, intent)),
        (layer2_physics, (intent,)),
        (layer3_regime, (adapter, intent)),
    ]:
        report = layer_fn(*args)
        if report is None:
            continue
        result = _merge(result, report)
        if not result.passed:
            return result

    # Also call the adapter's own validate() so engine-specific checks run.
    # Merge but don't double-count layer numbers already set.
    adapter_report = adapter.validate(intent)
    if not adapter_report.passed and result.passed:
        result = _merge(result, adapter_report)
    elif adapter_report.warnings or not adapter_report.in_regime:
        result = _merge(result, adapter_report)

    return result


def post_run_validate(bundle: ResultBundle) -> ValidationReport:
    """Run layer 5 (post-run sanity) on the result bundle."""
    report = layer5_postrun(bundle)
    return report if report is not None else ValidationReport(passed=True)
