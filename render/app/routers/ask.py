"""POST /ask — run a simulation from a natural-language question.

Thin HTTP shell over :func:`render.pipeline.run_question` so the API and CLI
share identical behaviour.  Maps the pipeline's ``status`` onto HTTP semantics:
``clarify``/``abstain`` are normal 200 responses (the UI shows the message),
while genuine engine/parse failures surface as 4xx/5xx.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from render.llm import get_api_key as _get_api_key
from render.pipeline import DEFAULT_MANIFEST_DIR, run_question

router = APIRouter(prefix="/ask", tags=["ask"])


class AskRequest(BaseModel):
    question: str = Field(..., description="Natural-language simulation question")
    engine: str | None = Field(None, description="Force a specific engine by name")
    dry_run: bool = Field(False)
    interpret_result: bool = Field(True)


@router.post("")
async def ask(req: AskRequest) -> dict:
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="Question must not be empty.")

    result = run_question(
        req.question,
        engine=req.engine,
        dry_run=req.dry_run,
        interpret_result=req.interpret_result,
        api_key=_get_api_key(),
        manifest_dir=DEFAULT_MANIFEST_DIR,
    )

    if result.status == "error":
        raise HTTPException(status_code=500, detail=result.message)

    return result.model_dump()
