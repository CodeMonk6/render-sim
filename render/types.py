"""Core types for Render.

Every module in the system imports from here.  These are pure data containers —
no IO, no engine-specific logic, no external dependencies beyond Pydantic and
the standard library.

Design rules:
  - All models are frozen (immutable after construction).
  - UUIDs and timestamps are generated on construction, never mutated.
  - The interpreter may ONLY cite quantities present in a ResultBundle.
  - RunManifest is sufficient to replay a run from scratch.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

# ── Primitive aliases ──────────────────────────────────────────────────────────

TrustStatus = Literal["certified", "experimental"]
IntentMode = Literal["simulation_explicit", "property_driven"]
RuntimeTarget = Literal["local", "hpc", "either"]
EnvType = Literal["pip", "conda", "module", "container"]
ConstraintSource = Literal["user", "default"]


# ── Environment specification ─────────────────────────────────────────────────


class EnvSpec(BaseModel):
    """Software environment needed to run an engine on local or HPC."""

    env_type: EnvType
    packages: list[str] = Field(default_factory=list)
    module_name: str = ""
    container_image: str = ""
    python_requires: str = ">=3.11"
    notes: str = ""

    model_config = {"frozen": True}


# ── Resource request ──────────────────────────────────────────────────────────


class ResourceSpec(BaseModel):
    """Computational resources for a single run."""

    nodes: int = 1
    cores_per_node: int = 1
    memory_gb: float = 4.0
    walltime_hours: float = 1.0
    gpu: bool = False
    partition: str = ""

    model_config = {"frozen": True}


# ── Intent ────────────────────────────────────────────────────────────────────


class Constraint(BaseModel):
    """One named parameter with its origin (user-stated vs. system default)."""

    name: str
    value: Any
    source: ConstraintSource = "user"
    unit: str = ""

    model_config = {"frozen": True}


class Intent(BaseModel):
    """Typed, structured representation of a researcher's simulation request.

    Separates user-stated constraints from system-selected defaults.
    In property_driven mode the engine field may be empty until the user
    chooses a pathway.
    """

    intent_id: UUID = Field(default_factory=uuid4)
    mode: IntentMode
    question: str
    family: str
    engine: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    constraints: list[Constraint] = Field(default_factory=list)
    defaults_applied: list[Constraint] = Field(default_factory=list)
    resources: ResourceSpec = Field(default_factory=ResourceSpec)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}


# ── Pathway proposal (property-driven mode) ───────────────────────────────────


class Pathway(BaseModel):
    """A candidate modeling approach for a property-driven question."""

    engine: str
    family: str
    description: str
    estimated_cost: str
    fidelity: str
    assumptions: list[str] = Field(default_factory=list)
    status: TrustStatus

    model_config = {"frozen": True}


class PathwayProposal(BaseModel):
    """Ranked candidate pathways returned in property_driven mode."""

    question: str
    pathways: list[Pathway]
    recommendation: str = ""

    model_config = {"frozen": True}


# ── Validation ────────────────────────────────────────────────────────────────


class ValidationReport(BaseModel):
    """Result of the 7-layer validation stack.

    Layers:
      1 — Pydantic schema
      2 — physical constraints + units (Pint)
      3 — in-regime check
      4 — pre-flight dry-run
      5 — post-run sanity (NaN/Inf, convergence)
      6 — reference-case regression
      7 — interpretation number-grounding
    """

    passed: bool
    failed_layer: int | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    in_regime: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("failed_layer")
    @classmethod
    def _layer_range(cls, v: int | None) -> int | None:
        if v is not None and not (1 <= v <= 7):
            raise ValueError(f"failed_layer must be 1-7, got {v}")
        return v

    model_config = {"frozen": True}


# ── Engine I/O ────────────────────────────────────────────────────────────────


class EngineInputs(BaseModel):
    """Prepared input files and parameters ready for engine execution."""

    engine: str
    files: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None


class RawOutputs(BaseModel):
    """Unprocessed output directly from the engine process."""

    engine: str
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    files: dict[str, str] = Field(default_factory=dict)
    wall_time_s: float = 0.0


# ── Result bundle ─────────────────────────────────────────────────────────────


class Quantity(BaseModel):
    """A single named scalar quantity in a result.

    The interpreter may ONLY cite quantities present in the ResultBundle —
    never invent values.
    """

    name: str
    value: Any
    unit: str = ""
    uncertainty: float | None = None

    model_config = {"frozen": True}


class ResultBundle(BaseModel):
    """Typed, parsed engine outputs.  The ground-truth for the interpreter."""

    engine: str
    quantities: list[Quantity] = Field(default_factory=list)
    figure_paths: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    converged: bool = True
    warnings: list[str] = Field(default_factory=list)

    def get(self, name: str) -> Quantity | None:
        """Return the quantity with the given name, or None."""
        for q in self.quantities:
            if q.name == name:
                return q
        return None


# ── Provenance manifest ───────────────────────────────────────────────────────


class RunManifest(BaseModel):
    """Complete provenance record of a finished run.

    Contains everything needed to reproduce the run from scratch via
    ``render replay <run_id>``.
    """

    run_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime
    intent: Intent
    engine_name: str
    engine_version: str
    engine_status: TrustStatus
    environment: EnvSpec
    inputs: EngineInputs
    raw_outputs: RawOutputs
    bundle: ResultBundle
    validation: ValidationReport
    platform: str = ""
    seed: int | None = None
    replay_cmd: str = ""


# ── Reference case ────────────────────────────────────────────────────────────


class ToleranceSpec(BaseModel):
    """Statistical tolerance for a single quantity in a reference-case test."""

    quantity_name: str
    expected_value: float
    rtol: float = 0.01
    atol: float = 0.0
    seed: int | None = None

    model_config = {"frozen": True}


class ReferenceCase(BaseModel):
    """A published result that an engine must reproduce to be Certified.

    Passing all reference_cases for an engine promotes it from
    Experimental to Certified.
    """

    name: str
    engine: str
    description: str
    citation: str = ""
    intent: Intent
    tolerances: list[ToleranceSpec]

    model_config = {"frozen": True}
