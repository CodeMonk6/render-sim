"""Natural-language → typed Intent parser.

Uses Instructor + Anthropic Claude to convert a researcher's plain-English
question into a structured, validated Intent.  Retries up to MAX_RETRIES
times on Pydantic validation error (Instructor handles this automatically).

Two modes:
  simulation_explicit — "Run LAMMPS with these parameters for TIP4P water."
  property_driven     — "What is the best force field for liquid water at 300K?"

For property_driven queries parse_intent() returns an Intent with empty
`engine` field plus a PathwayProposal; the caller presents the table to the
user who selects a pathway.
"""

from __future__ import annotations

import os
from typing import Any

import anthropic
import instructor
from pydantic import BaseModel, Field

from render.types import (
    Constraint,
    Intent,
    IntentMode,
    Pathway,
    PathwayProposal,
    ResourceSpec,
    TrustStatus,
)

MAX_RETRIES = 3
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# ── Structured extraction schemas for the LLM ─────────────────────────────────


class _ExtractedParameter(BaseModel):
    name: str
    value: Any
    unit: str = ""
    is_user_stated: bool = True


class _IntentExtraction(BaseModel):
    """Schema the LLM must produce — maps to Intent after validation."""

    mode: IntentMode = Field(description="simulation_explicit or property_driven")
    family: str = Field(description="Simulation method family, e.g. 'ode', 'md', 'dft'")
    engine: str = Field(default="", description="Specific engine name if explicitly requested")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Named parameters for the simulation",
    )
    user_stated_constraints: list[_ExtractedParameter] = Field(
        default_factory=list,
        description="Parameters explicitly stated by the user",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions made to fill in unstated parameters",
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Confidence in the mapping (lower if ambiguous)",
    )
    resources_cores: int = Field(default=1, description="CPU cores needed")
    resources_memory_gb: float = Field(default=4.0, description="RAM needed in GB")
    resources_walltime_hours: float = Field(default=1.0, description="Walltime in hours")
    resources_gpu: bool = Field(default=False, description="Requires GPU")


class _PathwayExtraction(BaseModel):
    """Schema for property-driven mode: a list of candidate pathways."""

    pathways: list[_ExtractedPathway]
    recommendation: str = Field(
        default="", description="Brief reason for the recommended pathway"
    )


class _ExtractedPathway(BaseModel):
    engine: str
    family: str
    description: str
    estimated_cost: str = Field(description="e.g. 'seconds (local)' or 'hours (HPC)'")
    fidelity: str = Field(description="e.g. 'high (ab initio)' or 'moderate (empirical FF)'")
    assumptions: list[str] = Field(default_factory=list)
    status: TrustStatus = "experimental"


# ── Public API ─────────────────────────────────────────────────────────────────


def parse_intent(
    question: str,
    available_families: list[str] | None = None,
    available_engines: list[str] | None = None,
    *,
    model: str = _DEFAULT_MODEL,
    api_key: str | None = None,
) -> tuple[Intent, PathwayProposal | None]:
    """Parse *question* into a typed Intent (and optionally a PathwayProposal).

    Returns ``(intent, None)`` for simulation_explicit questions.
    Returns ``(intent, PathwayProposal)`` for property_driven questions — the
    intent has an empty ``engine`` field and the caller must show the user the
    pathway table.

    Raises ``RuntimeError`` if the Anthropic API is unavailable or returns an
    unparseable response after MAX_RETRIES.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    client = instructor.from_anthropic(anthropic.Anthropic(api_key=key or None))  # type: ignore[arg-type]

    families_str = ", ".join(available_families or _DEFAULT_FAMILIES)
    engines_str = ", ".join(available_engines or [])

    system = _build_system_prompt(families_str, engines_str)

    try:
        extraction: _IntentExtraction = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": question}],
            response_model=_IntentExtraction,
            max_retries=MAX_RETRIES,
        )
    except Exception as exc:
        raise RuntimeError(f"Intent parsing failed: {exc}") from exc

    # Build Constraint list
    constraints = [
        Constraint(
            name=p.name,
            value=p.value,
            unit=p.unit,
            source="user" if p.is_user_stated else "default",
        )
        for p in extraction.user_stated_constraints
    ]

    resources = ResourceSpec(
        cores_per_node=max(1, extraction.resources_cores),
        memory_gb=max(0.5, extraction.resources_memory_gb),
        walltime_hours=max(0.1, extraction.resources_walltime_hours),
        gpu=extraction.resources_gpu,
    )

    intent = Intent(
        mode=extraction.mode,
        question=question,
        family=extraction.family,
        engine=extraction.engine,
        parameters=extraction.parameters,
        constraints=constraints,
        resources=resources,
        confidence=extraction.confidence,
        assumptions=extraction.assumptions,
    )

    proposal: PathwayProposal | None = None
    if extraction.mode == "property_driven":
        proposal = _propose_pathways(
            question, intent.family, client=client, model=model, system=system
        )

    return intent, proposal


def _propose_pathways(
    question: str,
    family: str,
    *,
    client: Any,
    model: str,
    system: str,
) -> PathwayProposal:
    prompt = (
        f"The researcher asked: '{question}'\n"
        f"Identified method family: {family}\n"
        "Propose 2-4 candidate modeling pathways for this property-driven question. "
        "Each pathway should specify a different engine or approach with its cost, "
        "fidelity, and key assumptions."
    )
    try:
        pw_ex: _PathwayExtraction = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            response_model=_PathwayExtraction,
            max_retries=MAX_RETRIES,
        )
    except Exception:
        return PathwayProposal(question=question, pathways=[], recommendation="")

    pathways = [
        Pathway(
            engine=p.engine,
            family=p.family,
            description=p.description,
            estimated_cost=p.estimated_cost,
            fidelity=p.fidelity,
            assumptions=p.assumptions,
            status=p.status,
        )
        for p in pw_ex.pathways
    ]
    return PathwayProposal(
        question=question,
        pathways=pathways,
        recommendation=pw_ex.recommendation,
    )


def _build_system_prompt(families: str, engines: str) -> str:
    engines_part = f"\nAvailable engines: {engines}" if engines else ""
    return f"""\
You are a scientific simulation expert assistant for the Render platform.
Your job is to convert a researcher's plain-English question into a structured
simulation intent. Be conservative: only extract parameters that are explicitly
stated or are standard defaults for the method.

Available simulation families: {families}{engines_part}

Rules:
- mode = "simulation_explicit" when the user specifies a method/engine/parameters.
- mode = "property_driven" when the user asks "what is the best method for X?"
  or "how should I model Y?" without specifying a particular approach.
- Extract ONLY user-stated parameters into user_stated_constraints.
- List any assumptions you make in the assumptions field.
- Set confidence < 1.0 when the request is ambiguous.
- If a field is genuinely unknown, omit it from parameters.
"""


_DEFAULT_FAMILIES = [
    "ode", "epi", "sbml", "ssa", "mcmc", "des", "abm", "nbody",
    "md", "dft", "freebird", "materials_utils", "fem", "em", "cfd",
]
