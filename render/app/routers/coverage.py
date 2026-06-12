"""GET /coverage — the engine coverage scoreboard.

Reports the full registered engine matrix (family, trust status, runtime, and
reference-case coverage) **without running anything**.  This is the data source
for the web-UI scoreboard, so it must be instant and side-effect-free — unlike
``/eval``, which actually executes reference cases and needs the engine backends
installed.

Any bootstrap config error (a canonical adapter that failed to register) is
surfaced in ``registration_errors`` rather than silently dropped — the registry
must never be quietly incomplete.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from render.registry import registry
from render.registry.bootstrap import register_all_engines

router = APIRouter(prefix="/coverage", tags=["coverage"])


class EngineCoverage(BaseModel):
    name: str
    family: str
    status: str  # certified | experimental
    runtime: str  # local | hpc | either
    reference_cases: int
    reference_case_names: list[str] = Field(default_factory=list)
    env_type: str = ""
    env_summary: str = ""


class FamilyCoverage(BaseModel):
    family: str
    engines: list[EngineCoverage]
    certified: int
    experimental: int


class CoverageResponse(BaseModel):
    families: list[FamilyCoverage]
    total_engines: int
    certified: int
    experimental: int
    family_count: int
    total_reference_cases: int
    registration_errors: list[str] = Field(default_factory=list)


def _env_summary(env) -> str:  # type: ignore[no-untyped-def]
    """One-line human summary of an EnvSpec."""
    if env is None:
        return ""
    if getattr(env, "module_name", ""):
        return f"module: {env.module_name}"
    if getattr(env, "container_image", ""):
        return f"container: {env.container_image}"
    pkgs = getattr(env, "packages", []) or []
    if pkgs:
        head = ", ".join(pkgs[:4])
        more = f" +{len(pkgs) - 4}" if len(pkgs) > 4 else ""
        return f"{getattr(env, 'env_type', 'pip')}: {head}{more}"
    return getattr(env, "env_type", "") or ""


@router.get("", response_model=CoverageResponse)
async def coverage() -> CoverageResponse:
    report = register_all_engines(registry)

    by_family: dict[str, list[EngineCoverage]] = {}
    total_ref = 0
    for adapter in registry.list_all():
        cases = list(adapter.reference_cases)
        total_ref += len(cases)
        env = getattr(adapter, "environment", None)
        ec = EngineCoverage(
            name=adapter.name,
            family=adapter.family,
            status=adapter.status,
            runtime=adapter.runtime,
            reference_cases=len(cases),
            reference_case_names=[c.name for c in cases],
            env_type=getattr(env, "env_type", "") or "",
            env_summary=_env_summary(env),
        )
        by_family.setdefault(adapter.family, []).append(ec)

    families: list[FamilyCoverage] = []
    cert_total = exp_total = 0
    for fam in sorted(by_family):
        engines = sorted(by_family[fam], key=lambda e: e.name)
        c = sum(1 for e in engines if e.status == "certified")
        x = sum(1 for e in engines if e.status == "experimental")
        cert_total += c
        exp_total += x
        families.append(FamilyCoverage(family=fam, engines=engines, certified=c, experimental=x))

    errors = [f"{spec}: {reason}" for spec, reason in report.errors]

    return CoverageResponse(
        families=families,
        total_engines=len(registry),
        certified=cert_total,
        experimental=exp_total,
        family_count=len(families),
        total_reference_cases=total_ref,
        registration_errors=errors,
    )
