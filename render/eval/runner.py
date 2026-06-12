"""Reference-case regression runner.

Checks that a Certified engine reproduces its published reference results
within the stated statistical tolerance.  Returns a structured report and
exits non-zero on failure (used to gate CI).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from render.registry.protocol import EngineAdapter
from render.types import ReferenceCase, ResourceSpec

# Phrases an adapter emits when its backend (Python package, binary, or Julia
# package) simply isn't installed in this environment. These are *environment*
# limitations, not reference-case regressions, so they're reported as SKIPPED
# and do not fail the CI gate — a runner without PySCF/OpenMM/Julia/LAMMPS is
# expected, while a genuine tolerance miss is not.
_MISSING_BACKEND_MARKERS = (
    "not installed",
    "not found",
    "no module named",
    "package freebird not",
    "could not find julia",
    "julia not found",
    "module load",
)


def _is_missing_backend(message: str) -> bool:
    msg = message.lower()
    return any(marker in msg for marker in _MISSING_BACKEND_MARKERS)


@dataclass
class CaseResult:
    case_name: str
    engine: str
    passed: bool
    skipped: bool = False
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    engine: str
    total: int
    passed: int
    failed: int
    skipped: int = 0
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # A report is OK when nothing genuinely failed; skipped cases don't count.
        return self.failed == 0


def run_reference_case(adapter: EngineAdapter, case: ReferenceCase) -> CaseResult:
    """Run one reference case and check all tolerances."""
    failures: list[str] = []
    warnings: list[str] = []

    # Validate
    report = adapter.validate(case.intent)
    if not report.passed:
        return CaseResult(
            case_name=case.name,
            engine=adapter.name,
            passed=False,
            failures=[f"Validation failed (layer {report.failed_layer}): {report.errors}"],
        )
    warnings.extend(report.warnings)

    # Build + run
    resources = ResourceSpec()
    try:
        inputs = adapter.build_inputs(case.intent)
        raw = adapter.run(inputs, resources)
    except Exception as exc:
        msg = f"Run error: {exc}"
        return CaseResult(
            case_name=case.name,
            engine=adapter.name,
            passed=False,
            skipped=_is_missing_backend(str(exc)),
            failures=[msg],
        )

    if raw.exit_code != 0:
        detail = f"Engine exited with code {raw.exit_code}: {raw.stderr[:200]}"
        return CaseResult(
            case_name=case.name,
            engine=adapter.name,
            passed=False,
            skipped=_is_missing_backend(raw.stderr or ""),
            failures=[detail],
        )

    # Parse
    try:
        bundle = adapter.parse(raw)
    except Exception as exc:
        return CaseResult(
            case_name=case.name,
            engine=adapter.name,
            passed=False,
            failures=[f"Parse error: {exc}"],
        )

    # Check tolerances
    for tol in case.tolerances:
        qty = bundle.get(tol.quantity_name)
        if qty is None:
            failures.append(
                f"Quantity '{tol.quantity_name}' not found in ResultBundle. "
                f"Available: {[q.name for q in bundle.quantities]}"
            )
            continue

        actual = float(qty.value)
        expected = tol.expected_value
        rtol = tol.rtol
        atol = tol.atol

        abs_diff = abs(actual - expected)
        threshold = atol + rtol * abs(expected)

        if abs_diff > threshold:
            failures.append(
                f"Tolerance failure for '{tol.quantity_name}': "
                f"got {actual:.6g}, expected {expected:.6g}, "
                f"|diff|={abs_diff:.2e} > rtol={rtol} * |expected| + atol={atol} = {threshold:.2e}"
            )

    return CaseResult(
        case_name=case.name,
        engine=adapter.name,
        passed=len(failures) == 0,
        failures=failures,
        warnings=warnings,
    )


def eval_engine(adapter: EngineAdapter) -> EvalReport:
    """Run all reference cases for a single adapter."""
    cases_results: list[CaseResult] = []
    for case in adapter.reference_cases:
        result = run_reference_case(adapter, case)
        cases_results.append(result)

    passed = sum(1 for r in cases_results if r.passed)
    skipped = sum(1 for r in cases_results if r.skipped)
    # Skipped (missing backend) cases are neither passed nor failed.
    failed = sum(1 for r in cases_results if not r.passed and not r.skipped)
    return EvalReport(
        engine=adapter.name,
        total=len(cases_results),
        passed=passed,
        failed=failed,
        skipped=skipped,
        cases=cases_results,
    )
