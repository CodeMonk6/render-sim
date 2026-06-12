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

from typing import Any

import anthropic
import instructor
from pydantic import BaseModel, Field

from render.llm import (
    get_api_key as _get_api_key,
)
from render.llm import (
    get_default_model as _get_default_model,
)
from render.llm import (
    get_provider as _get_provider,
)
from render.llm import (
    instructor_create as _instructor_create,
)
from render.llm import (
    make_instructor_client as _make_instructor_client,
)
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
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the mapping (lower if ambiguous)",
    )
    resources_cores: int = Field(default=1, description="CPU cores needed")
    resources_memory_gb: float = Field(default=4.0, description="RAM needed in GB")
    resources_walltime_hours: float = Field(default=1.0, description="Walltime in hours")
    resources_gpu: bool = Field(default=False, description="Requires GPU")


class _PathwayExtraction(BaseModel):
    """Schema for property-driven mode: a list of candidate pathways."""

    pathways: list[_ExtractedPathway]
    recommendation: str = Field(default="", description="Brief reason for the recommended pathway")


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
    provider = _get_provider(api_key)
    key = _get_api_key(api_key)
    if model == _DEFAULT_MODEL:
        model = _get_default_model(provider)

    # Use module-level anthropic/instructor imports so test mocks remain valid
    # for the Anthropic path; the OpenRouter path goes through render.llm.
    if provider == "anthropic":
        client = instructor.from_anthropic(anthropic.Anthropic(api_key=key or None))  # type: ignore[arg-type]
    else:
        client = _make_instructor_client(provider, key)

    families_str = ", ".join(available_families or _DEFAULT_FAMILIES)
    engines_str = ", ".join(available_engines or [])

    system = _build_system_prompt(families_str, engines_str)

    try:
        extraction: _IntentExtraction = _instructor_create(
            client,
            provider,
            model,
            system,
            question,
            _IntentExtraction,
            max_tokens=1024,
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
            question, intent.family, client=client, provider=provider, model=model, system=system
        )

    return intent, proposal


def extract_engine_parameters(
    question: str,
    schema_cls: type[BaseModel],
    *,
    base_params: dict[str, Any] | None = None,
    model: str = _DEFAULT_MODEL,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Re-extract parameters from *question* into a specific engine's schema.

    The first generic pass (``parse_intent``) picks the engine and family but
    produces free-form parameter names ("natural_frequency"), which rarely match
    an engine's exact field names ("omega0").  This second pass binds extraction
    to the *selected engine's own Pydantic schema* — the system's single contract
    for what that engine accepts — so names line up and Pydantic validates types.

    To preserve "ask, don't guess", every field is mirrored as Optional/None and
    the model is told to leave a field null unless the value is explicitly stated
    or unambiguously implied.  Only the fields the model actually set are returned
    and merged over ``base_params``; genuinely-missing required fields stay absent
    so the clarify/abstain controller can ask for them.
    """
    from pydantic import create_model

    provider = _get_provider(api_key)
    key = _get_api_key(api_key)
    if model == _DEFAULT_MODEL:
        model = _get_default_model(provider)

    # Build an all-optional mirror of the engine schema so unstated fields stay null.
    optional_fields: dict[str, Any] = {}
    descriptions: list[str] = []
    for fname, finfo in schema_cls.model_fields.items():
        ann = finfo.annotation
        desc = finfo.description or ""
        optional_fields[fname] = (ann | None, Field(default=None, description=desc))
        descriptions.append(f"  - {fname}: {desc}" if desc else f"  - {fname}")
    mirror = create_model(f"_{schema_cls.__name__}_Optional", **optional_fields)

    if provider == "anthropic":
        client = instructor.from_anthropic(anthropic.Anthropic(api_key=key or None))  # type: ignore[arg-type]
    else:
        client = _make_instructor_client(provider, key)

    system = (
        "You map a researcher's question onto the exact parameters of a chosen "
        "simulation engine. Fill ONLY fields whose values are explicitly stated or "
        "unambiguously implied by the question. Leave every other field null — do "
        "not invent or assume values. Convert units to the field's stated unit when "
        "one is given.\n\nEngine parameters:\n" + "\n".join(descriptions)
    )

    try:
        filled = _instructor_create(
            client,
            provider,
            model,
            system,
            question,
            mirror,
            max_tokens=1024,
            max_retries=MAX_RETRIES,
        )
    except Exception:
        return dict(base_params or {})

    params: dict[str, Any] = dict(base_params or {})
    for fname in schema_cls.model_fields:
        val = getattr(filled, fname, None)
        if val is not None:
            params[fname] = val
    return params


def _propose_pathways(
    question: str,
    family: str,
    *,
    client: Any,
    provider: str,
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
        pw_ex: _PathwayExtraction = _instructor_create(
            client,
            provider,
            model,
            system,
            prompt,
            _PathwayExtraction,
            max_tokens=1024,
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
    "ode",
    "epi",
    "sbml",
    "ssa",
    "mcmc",
    "des",
    "abm",
    "nbody",
    "md",
    "dft",
    "freebird",
    "materials_utils",
    "fem",
    "em",
    "cfd",
]
