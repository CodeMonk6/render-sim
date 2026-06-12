"""POST /ask — run a simulation from a natural-language question."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from render.engines.reference import HarmonicOscillatorAdapter
from render.execute.local import run_local
from render.interpret import interpret
from render.llm import get_api_key as _get_api_key
from render.registry import registry
from render.validate import clarify_or_abstain

router = APIRouter(prefix="/ask", tags=["ask"])


class AskRequest(BaseModel):
    question: str = Field(..., description="Natural-language simulation question")
    engine: str | None = Field(None, description="Force a specific engine by name")
    dry_run: bool = Field(False)
    interpret_result: bool = Field(True)


class AskResponse(BaseModel):
    run_id: str | None = None
    engine_name: str | None = None
    engine_status: str | None = None
    quantities: list[dict] = Field(default_factory=list)
    interpretation: str | None = None
    status_badge: str | None = None
    confidence: float | None = None
    assumptions: list[str] = Field(default_factory=list)
    validation_passed: bool = True
    warnings: list[str] = Field(default_factory=list)
    clarify_message: str | None = None
    pathways: list[dict] = Field(default_factory=list)
    replay_cmd: str | None = None


def _ensure_engines() -> None:
    if "harmonic_oscillator" not in registry:
        registry.register(HarmonicOscillatorAdapter())


@router.post("", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    _ensure_engines()
    from render.intent import parse_intent

    api_key = _get_api_key()
    families = list({a.family for a in registry.list_all()})
    engines = [a.name for a in registry.list_all()]

    try:
        intent, proposal = parse_intent(req.question, available_families=families,
                                        available_engines=engines, api_key=api_key)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Intent parsing failed: {exc}") from exc

    # Return pathway table for property-driven questions
    pathway_dicts: list[dict] = []
    if intent.mode == "property_driven" and proposal and proposal.pathways:
        pathway_dicts = [p.model_dump() for p in proposal.pathways]
        # Auto-select first pathway
        if proposal.pathways:
            intent = intent.model_copy(update={
                "engine": proposal.pathways[0].engine, "mode": "simulation_explicit"
            })

    if req.engine:
        intent = intent.model_copy(update={"engine": req.engine})

    try:
        adapter = registry.get(intent.engine)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Engine '{intent.engine}' not registered.") from None  # noqa: E501

    clarify = clarify_or_abstain(adapter, intent)
    if clarify.decision.value == "clarify":
        return AskResponse(clarify_message=clarify.message, validation_passed=False)
    if clarify.decision.value == "abstain":
        raise HTTPException(status_code=422, detail=clarify.message)

    if req.dry_run:
        return AskResponse(engine_name=adapter.name, engine_status=adapter.status,
                           validation_passed=True, pathways=pathway_dicts)

    try:
        manifest = run_local(adapter, intent)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Run failed: {exc}") from exc

    quantities = [
        {"name": q.name, "value": q.value, "unit": q.unit or ""} for q in manifest.bundle.quantities
    ]

    interp_text = status_badge = None
    conf = None
    assumptions: list[str] = []

    if req.interpret_result:
        try:
            iresult = interpret(intent, manifest.bundle, manifest.validation,
                                manifest.engine_status, api_key=api_key)
            interp_text = iresult.text
            status_badge = iresult.status_badge
            conf = iresult.confidence
            assumptions = iresult.assumptions
        except Exception:
            pass

    return AskResponse(
        run_id=str(manifest.run_id),
        engine_name=manifest.engine_name,
        engine_status=manifest.engine_status,
        quantities=quantities,
        interpretation=interp_text,
        status_badge=status_badge,
        confidence=conf,
        assumptions=assumptions,
        validation_passed=manifest.validation.passed,
        warnings=manifest.validation.warnings,
        pathways=pathway_dicts,
        replay_cmd=manifest.replay_cmd,
    )
