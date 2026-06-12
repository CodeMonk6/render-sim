"""End-to-end orchestration: natural language → simulation → interpretation.

A single entry point, :func:`run_question`, that the CLI and the REST API both
call so their behaviour is identical.  It runs the full Render flow:

    register engines → parse intent → (property-driven pathways) →
    bind parameters to the chosen engine's schema → clarify / abstain →
    run locally (provenance) → grounded interpretation

and returns a typed :class:`PipelineResult` (no FastAPI / CLI types leak in).

The parameter-binding step is what makes free-form questions actually run: the
first NL pass picks an engine but emits generic parameter names, so once the
engine is known we re-extract into *its* Pydantic schema.  That second LLM call
is skipped when the first pass already satisfies the schema, so well-formed
requests stay fast.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from render.registry import registry
from render.registry.bootstrap import register_all_engines
from render.validate import clarify_or_abstain

# Where provenance manifests are written. Override with RENDER_RUNS_DIR so a
# container can point this at a mounted volume for persistence across restarts.
DEFAULT_MANIFEST_DIR = Path(os.environ.get("RENDER_RUNS_DIR", ".render_runs"))


class PipelineResult(BaseModel):
    """Outcome of one question, ready to serialize for the API or render in the CLI."""

    status: str  # ok | clarify | abstain | dry_run | error
    message: str = ""

    question: str = ""
    engine_name: str | None = None
    engine_family: str | None = None
    engine_status: str | None = None

    run_id: str | None = None
    quantities: list[dict] = Field(default_factory=list)
    series: dict | None = None

    interpretation: str | None = None
    status_badge: str | None = None
    confidence: float | None = None
    assumptions: list[str] = Field(default_factory=list)

    validation_passed: bool = True
    in_regime: bool = True
    warnings: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)

    pathways: list[dict] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    replay_cmd: str | None = None
    manifest_path: str | None = None


def _params_satisfy_schema(schema_cls: type | None, params: dict) -> bool:
    if schema_cls is None:
        return True
    try:
        schema_cls.model_validate(params)
        return True
    except Exception:
        return False


def run_question(
    question: str,
    *,
    engine: str | None = None,
    dry_run: bool = False,
    interpret_result: bool = True,
    api_key: str | None = None,
    manifest_dir: Path | None = DEFAULT_MANIFEST_DIR,
) -> PipelineResult:
    """Run *question* end-to-end and return a :class:`PipelineResult`.

    Never raises for ordinary control flow (clarify / abstain / bad engine);
    those come back as a result with the matching ``status``.  Genuinely
    unexpected failures return ``status="error"`` with the message.
    """
    from render.execute.local import run_local
    from render.intent import extract_engine_parameters, parse_intent
    from render.interpret import interpret

    register_all_engines(registry)
    families = sorted({a.family for a in registry.list_all()})
    engines = sorted(a.name for a in registry.list_all())
    # Pass short engine descriptions to the parser so it selects the RIGHT engine
    # (e.g. harmonic_oscillator vs scipy_ode) instead of a same-family near-miss.
    engine_hints = sorted(
        (f"{a.name} — {getattr(a, 'description', '')}" if getattr(a, "description", "") else a.name)
        for a in registry.list_all()
    )

    # 1. Parse NL → intent (+ pathway proposal for property-driven questions).
    try:
        intent, proposal = parse_intent(
            question, available_families=families, available_engines=engine_hints, api_key=api_key
        )
    except Exception as exc:
        return PipelineResult(
            status="error", question=question, message=f"Could not understand the question: {exc}"
        )

    # 2. Property-driven → expose pathway table, auto-select the first pathway.
    pathway_dicts: list[dict] = []
    if intent.mode == "property_driven" and proposal and proposal.pathways:
        pathway_dicts = [p.model_dump() for p in proposal.pathways]
        intent = intent.model_copy(
            update={
                "engine": proposal.pathways[0].engine,
                "mode": "simulation_explicit",
            }
        )

    if engine:
        intent = intent.model_copy(update={"engine": engine})

    # 3. Resolve the engine adapter.
    if not intent.engine:
        return PipelineResult(
            status="abstain",
            question=question,
            pathways=pathway_dicts,
            message="I couldn't determine which engine to use for this question.",
        )
    try:
        adapter = registry.get(intent.engine)
    except KeyError:
        return PipelineResult(
            status="abstain",
            question=question,
            pathways=pathway_dicts,
            message=(
                f"No engine named '{intent.engine}' is registered. "
                f"Available engines: {', '.join(engines)}."
            ),
        )

    # 4. Bind parameters to THIS engine's schema (skip the call if already valid).
    schema_cls = getattr(adapter, "intent_schema", None)
    if not _params_satisfy_schema(schema_cls, intent.parameters) and schema_cls is not None:
        refined = extract_engine_parameters(
            question, schema_cls, base_params=intent.parameters, api_key=api_key
        )
        intent = intent.model_copy(update={"parameters": refined})

    # 5. Clarify or abstain.
    clarify = clarify_or_abstain(adapter, intent)
    if clarify.decision.value == "clarify":
        return PipelineResult(
            status="clarify",
            question=question,
            message=clarify.message,
            engine_name=adapter.name,
            engine_family=adapter.family,
            engine_status=adapter.status,
            missing_fields=clarify.missing_fields,
            validation_passed=False,
            pathways=pathway_dicts,
            parameters=dict(intent.parameters),
        )
    if clarify.decision.value == "abstain":
        return PipelineResult(
            status="abstain",
            question=question,
            message=clarify.message,
            engine_name=adapter.name,
            engine_family=adapter.family,
            engine_status=adapter.status,
            validation_passed=False,
            pathways=pathway_dicts,
            parameters=dict(intent.parameters),
        )

    if dry_run:
        return PipelineResult(
            status="dry_run",
            question=question,
            message=clarify.message,
            engine_name=adapter.name,
            engine_family=adapter.family,
            engine_status=adapter.status,
            validation_passed=True,
            in_regime=clarify.validation.in_regime if clarify.validation else True,
            confidence=clarify.confidence,
            assumptions=clarify.assumptions,
            pathways=pathway_dicts,
            parameters=dict(intent.parameters),
        )

    # 6. Run locally with full provenance.
    try:
        manifest = run_local(adapter, intent, manifest_dir=manifest_dir)
    except Exception as exc:
        return PipelineResult(
            status="error",
            question=question,
            engine_name=adapter.name,
            engine_family=adapter.family,
            engine_status=adapter.status,
            message=f"The engine failed to run: {exc}",
        )

    quantities = [
        {"name": q.name, "value": q.value, "unit": q.unit or ""} for q in manifest.bundle.quantities
    ]
    series = manifest.bundle.metadata.get("series") if manifest.bundle.metadata else None

    # 7. Grounded interpretation (optional; never blocks the result).
    interp_text = status_badge = None
    conf = clarify.confidence
    assumptions = list(clarify.assumptions)
    if interpret_result:
        try:
            ir = interpret(
                intent,
                manifest.bundle,
                manifest.validation,
                manifest.engine_status,
                api_key=api_key,
            )
            interp_text = ir.text
            status_badge = ir.status_badge
            conf = ir.confidence
            if ir.assumptions:
                assumptions = ir.assumptions
        except Exception:
            pass

    manifest_path = None
    if manifest_dir is not None:
        manifest_path = str(Path(manifest_dir) / f"{manifest.run_id}.json")

    return PipelineResult(
        status="ok",
        question=question,
        engine_name=manifest.engine_name,
        engine_family=adapter.family,
        engine_status=manifest.engine_status,
        run_id=str(manifest.run_id),
        quantities=quantities,
        series=series,
        interpretation=interp_text,
        status_badge=status_badge,
        confidence=conf,
        assumptions=assumptions,
        validation_passed=manifest.validation.passed,
        in_regime=manifest.validation.in_regime,
        warnings=manifest.validation.warnings,
        pathways=pathway_dicts,
        parameters=dict(intent.parameters),
        replay_cmd=manifest.replay_cmd,
        manifest_path=manifest_path,
    )
