"""Status-aware engine registry.

All adapters self-register at import time via ``register()``.  The registry
enforces that a Certified engine actually has reference cases.
"""

from __future__ import annotations

from render.registry.protocol import EngineAdapter
from render.types import TrustStatus


class EngineRegistry:
    """Thread-safe (append-only) registry mapping engine name → adapter."""

    def __init__(self) -> None:
        self._adapters: dict[str, EngineAdapter] = {}

    def register(self, adapter: EngineAdapter) -> None:
        """Register an adapter.  Raises if the name is already taken."""
        if adapter.name in self._adapters:
            raise ValueError(f"Engine '{adapter.name}' is already registered.")
        if adapter.status == "certified" and not adapter.reference_cases:
            raise ValueError(
                f"Engine '{adapter.name}' is Certified but has no reference cases. "
                "Supply at least one ReferenceCase or mark it Experimental."
            )
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> EngineAdapter:
        """Return the adapter for ``name``, or raise KeyError."""
        if name not in self._adapters:
            raise KeyError(
                f"Engine '{name}' is not registered. Available: {sorted(self._adapters)}"
            )
        return self._adapters[name]

    def list_all(self) -> list[EngineAdapter]:
        return list(self._adapters.values())

    def list_by_status(self, status: TrustStatus) -> list[EngineAdapter]:
        return [a for a in self._adapters.values() if a.status == status]

    def list_by_family(self, family: str) -> list[EngineAdapter]:
        return [a for a in self._adapters.values() if a.family == family]

    def __len__(self) -> int:
        return len(self._adapters)

    def __contains__(self, name: str) -> bool:
        return name in self._adapters


# Module-level singleton — the live registry used by the pipeline.
registry = EngineRegistry()
