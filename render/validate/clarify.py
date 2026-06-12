"""Clarify-or-abstain controller.

Given an adapter and an intent, decides what to do before running:

  PROCEED   — all required fields present, intent is valid or in-regime.
  CLARIFY   — required fields are missing; returns which ones.
  ABSTAIN   — the request is out of scope (engine/family not registered,
              or adapter marks it as out-of-scope).

The caller (pipeline) uses this decision to either run the engine, prompt the
user for missing information, or tell the user the system can't help.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import ValidationError

from render.registry.protocol import EngineAdapter
from render.types import Intent, TrustStatus, ValidationReport
from render.validate.stack import pre_run_validate


class ClarifyDecision(StrEnum):
    PROCEED = "proceed"
    CLARIFY = "clarify"
    ABSTAIN = "abstain"


@dataclass
class ClarifyResponse:
    decision: ClarifyDecision
    message: str
    validation: ValidationReport | None = None
    missing_fields: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    confidence: float = 1.0
    engine_status: TrustStatus = "certified"


def clarify_or_abstain(
    adapter: EngineAdapter,
    intent: Intent,
) -> ClarifyResponse:
    """Decide whether to proceed, clarify, or abstain for a given intent.

    Rules (in order):
    1. Engine not registered / family not supported → ABSTAIN.
    2. Required schema fields missing → CLARIFY (list them).
    3. Schema validation fails for a reason other than missing fields → ABSTAIN
       (the intent is structurally wrong, not just incomplete).
    4. Physics layer fails (impossible values) → ABSTAIN with explanation.
    5. Out of regime → PROCEED with in_regime=False, lowered confidence, caveat.
    6. Experimental engine → PROCEED with hard-label warning in message.
    7. Everything fine → PROCEED.
    """
    # --- Rule 2: check for missing required schema fields --------------------
    schema_cls = adapter.intent_schema
    missing: list[str] = []
    if schema_cls is not None:
        try:
            schema_cls.model_validate(intent.parameters)
        except ValidationError as exc:
            for err in exc.errors():
                if err["type"] in ("missing", "value_error.missing"):
                    loc = ".".join(str(p) for p in err["loc"])
                    missing.append(loc)
                elif err["type"] == "missing":
                    missing.append(".".join(str(p) for p in err["loc"]))
            # Separate truly missing fields from other schema errors
            non_missing_errors = [
                e for e in exc.errors() if e["type"] not in ("missing", "value_error.missing")
            ]
            if missing and not non_missing_errors:
                return ClarifyResponse(
                    decision=ClarifyDecision.CLARIFY,
                    message=(
                        f"I need a few more details to proceed with {adapter.name}. "
                        f"Missing required fields: {', '.join(missing)}."
                    ),
                    missing_fields=missing,
                    engine_status=adapter.status,
                )
            if non_missing_errors:
                msgs = [e["msg"] for e in non_missing_errors]
                return ClarifyResponse(
                    decision=ClarifyDecision.ABSTAIN,
                    message=(
                        f"The parameters for {adapter.name} are structurally invalid and "
                        f"cannot be corrected automatically: {'; '.join(msgs)}."
                    ),
                    engine_status=adapter.status,
                )

    # --- Run layers 1-3 to get a full picture --------------------------------
    report = pre_run_validate(adapter, intent)

    if not report.passed:
        # Layer 2 failure → physically impossible request
        if report.failed_layer == 2:
            return ClarifyResponse(
                decision=ClarifyDecision.ABSTAIN,
                message=(
                    "The request contains physically impossible values and cannot be run: "
                    + "; ".join(report.errors)
                ),
                validation=report,
                engine_status=adapter.status,
            )
        # Other hard failure
        return ClarifyResponse(
            decision=ClarifyDecision.ABSTAIN,
            message=(
                f"Validation failed at layer {report.failed_layer}: " + "; ".join(report.errors)
            ),
            validation=report,
            engine_status=adapter.status,
        )

    # --- Rule 5: out of regime -----------------------------------------------
    assumptions = list(intent.assumptions)
    if intent.defaults_applied:
        assumptions += [
            f"{c.name} = {c.value} {c.unit}".strip() + " (system default)"
            for c in intent.defaults_applied
        ]

    if not report.in_regime:
        caveat = (
            f"Note: this request is outside {adapter.name}'s validated regime. "
            "Results are labelled out-of-regime and confidence is reduced. "
            + " ".join(report.warnings)
        )
        extra_label = (
            " ⚠ EXPERIMENTAL ENGINE — not yet validated against reference cases."
            if adapter.status == "experimental"
            else ""
        )
        return ClarifyResponse(
            decision=ClarifyDecision.PROCEED,
            message=caveat + extra_label,
            validation=report,
            assumptions=assumptions,
            confidence=report.confidence,
            engine_status=adapter.status,
        )

    # --- Rule 6: experimental engine -----------------------------------------
    if adapter.status == "experimental":
        return ClarifyResponse(
            decision=ClarifyDecision.PROCEED,
            message=(
                f"⚠ {adapter.name} is an EXPERIMENTAL engine and has not been validated "
                "against published reference cases. Treat results with caution."
            ),
            validation=report,
            assumptions=assumptions,
            confidence=0.6,
            engine_status=adapter.status,
        )

    # --- Rule 7: all clear ---------------------------------------------------
    return ClarifyResponse(
        decision=ClarifyDecision.PROCEED,
        message="",
        validation=report,
        assumptions=assumptions,
        confidence=report.confidence,
        engine_status=adapter.status,
    )
