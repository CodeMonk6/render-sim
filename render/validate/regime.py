"""Regime specification — defines the tested parameter envelope for an engine.

An adapter may optionally expose a ``regime: RegimeSpec`` attribute.  If it
does, layer 3 of the validation stack uses it to decide whether the request
falls inside the engine's validated operating range.
"""

from __future__ import annotations

from pydantic import BaseModel


class RegimeBound(BaseModel):
    """One-dimensional bound for a named parameter."""

    field: str
    min_val: float | None = None
    max_val: float | None = None
    unit: str = ""
    description: str = ""

    model_config = {"frozen": True}


class RegimeSpec(BaseModel):
    """The validated operating envelope for a simulation engine."""

    bounds: list[RegimeBound] = []
    notes: str = ""

    model_config = {"frozen": True}


def check_regime(
    params: dict,
    regime: RegimeSpec,
) -> tuple[bool, list[str]]:
    """Return (in_regime, out_of_range_messages).

    A parameter that isn't present in ``params`` is silently skipped —
    missing-field errors belong to layer 1.
    """
    messages: list[str] = []
    for bound in regime.bounds:
        val = params.get(bound.field)
        if val is None:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        if bound.min_val is not None and fval < bound.min_val:
            unit_str = f" {bound.unit}" if bound.unit else ""
            messages.append(
                f"'{bound.field}' = {fval}{unit_str} is below the engine's tested minimum "
                f"{bound.min_val}{unit_str}."
            )
        if bound.max_val is not None and fval > bound.max_val:
            unit_str = f" {bound.unit}" if bound.unit else ""
            messages.append(
                f"'{bound.field}' = {fval}{unit_str} exceeds the engine's tested maximum "
                f"{bound.max_val}{unit_str}."
            )
    return len(messages) == 0, messages
