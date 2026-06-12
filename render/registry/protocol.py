"""EngineAdapter Protocol — the uniform contract every engine must satisfy.

Adding a new engine = implement this interface + supply reference cases.
Nothing else in the pipeline changes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from render.types import (
    EngineInputs,
    EnvSpec,
    Intent,
    RawOutputs,
    ReferenceCase,
    ResourceSpec,
    ResultBundle,
    RuntimeTarget,
    TrustStatus,
    ValidationReport,
)


@runtime_checkable
class EngineAdapter(Protocol):
    """Uniform interface every simulation engine adapter must satisfy."""

    name: str
    family: str
    status: TrustStatus
    runtime: RuntimeTarget
    environment: EnvSpec

    @property
    def intent_schema(self) -> type:
        """Pydantic model class describing the valid intent parameters."""
        ...

    @property
    def reference_cases(self) -> list[ReferenceCase]:
        """Published results the engine must reproduce to be/remain Certified."""
        ...

    def validate(self, intent: Intent) -> ValidationReport:
        """Run layers 1-3 of the validation stack (schema, physics, regime)."""
        ...

    def build_inputs(self, intent: Intent) -> EngineInputs:
        """Translate a validated intent into engine-ready input files + params."""
        ...

    def run(self, inputs: EngineInputs, resources: ResourceSpec) -> RawOutputs:
        """Execute the engine and return raw outputs."""
        ...

    def parse(self, raw: RawOutputs) -> ResultBundle:
        """Parse raw engine output into a typed ResultBundle."""
        ...
