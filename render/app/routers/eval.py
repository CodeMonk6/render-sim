"""GET /eval — run reference-case evaluation harness."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from render.eval.runner import eval_engine
from render.registry import registry
from render.registry.bootstrap import register_all_engines

router = APIRouter(prefix="/eval", tags=["eval"])


class EngineScore(BaseModel):
    engine: str
    status: str
    ok: bool
    passed: int
    total: int
    failures: list[str] = []


class EvalResponse(BaseModel):
    scores: list[EngineScore]
    overall_ok: bool


def _ensure_engines() -> None:
    register_all_engines(registry)


@router.get("", response_model=EvalResponse)
async def run_eval(engine: str | None = None) -> EvalResponse:
    _ensure_engines()
    if engine:
        targets = [registry.get(engine)]
    else:
        # A bare /eval must never try to execute uninstalled HPC backends, so the
        # bulk default is limited to locally-runnable engines.  Heavy engines are
        # evaluated only when named explicitly (?engine=...).
        targets = [a for a in registry.list_all() if a.reference_cases and a.runtime == "local"]

    scores: list[EngineScore] = []
    overall_ok = True
    for adapter in targets:
        report = eval_engine(adapter)
        failures = [f for case in report.cases for f in case.failures]
        scores.append(
            EngineScore(
                engine=adapter.name,
                status=adapter.status,
                ok=report.ok,
                passed=report.passed,
                total=report.total,
                failures=failures,
            )
        )
        if not report.ok:
            overall_ok = False
    return EvalResponse(scores=scores, overall_ok=overall_ok)
