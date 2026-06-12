"""GET /runs — run history and provenance manifest download.

Every successful run writes a full :class:`RunManifest` JSON to the manifest
directory (default ``.render_runs/``).  These endpoints expose them so the web
UI can show a run history and let the user download the complete provenance
record for any run — the artifact behind ``render replay``.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from render.pipeline import DEFAULT_MANIFEST_DIR

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
async def list_runs(limit: int = 25) -> dict:
    """Return recent runs (newest first), summarised for the history panel."""
    d = DEFAULT_MANIFEST_DIR
    if not d.exists():
        return {"runs": []}

    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    runs = []
    for f in files:
        try:
            m = json.loads(f.read_text())
        except Exception:
            continue
        runs.append(
            {
                "run_id": m.get("run_id"),
                "engine_name": m.get("engine_name"),
                "engine_status": m.get("engine_status"),
                "timestamp": m.get("timestamp"),
                "question": (m.get("intent") or {}).get("question", ""),
                "validation_passed": (m.get("validation") or {}).get("passed", None),
            }
        )
    return {"runs": runs}


@router.get("/{run_id}")
async def get_run(run_id: str) -> JSONResponse:
    """Return the full provenance manifest for one run (download target)."""
    # Guard against path traversal — run_id must be a bare UUID-like token.
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(status_code=400, detail="Invalid run id.")
    path = DEFAULT_MANIFEST_DIR / f"{run_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No manifest for run {run_id}.")
    return JSONResponse(content=json.loads(path.read_text()))
