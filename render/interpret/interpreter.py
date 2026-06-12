"""Grounded natural-language interpreter for simulation results.

The interpreter calls Claude to produce a plain-language explanation, then
runs a number-grounding check (layer 7) to ensure no values were fabricated.
Every cited number must appear in the ResultBundle.

The output carries a STATUS BADGE reflecting the engine's trust level:
  ✓ CERTIFIED  — validated against published reference cases
  ⚠ EXPERIMENTAL — not yet validated; treat with caution
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from render.interpret.grounding import ground_check
from render.types import Intent, ResultBundle, TrustStatus, ValidationReport

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_STATUS_BADGE = {
    "certified": "✓ CERTIFIED ENGINE",
    "experimental": "⚠ EXPERIMENTAL ENGINE (not yet validated against reference cases)",
}


@dataclass
class InterpretResult:
    """Full interpretation of a simulation result."""

    text: str
    status_badge: str
    grounding: ValidationReport
    confidence: float
    assumptions: list[str] = field(default_factory=list)
    figure_paths: list[str] = field(default_factory=list)

    def formatted(self) -> str:
        """Return a console-ready formatted string."""
        badge = f"[{self.status_badge}]"
        confidence_str = f"Confidence: {self.confidence:.0%}"
        parts = [badge, "", self.text]
        if self.assumptions:
            parts += ["", "Assumptions:", *[f"  • {a}" for a in self.assumptions]]
        parts += ["", confidence_str]
        if not self.grounding.passed:
            parts += [
                "",
                "⚠ Grounding warning: " + "; ".join(self.grounding.errors),
            ]
        if self.figure_paths:
            parts += ["", "Figures:", *[f"  • {p}" for p in self.figure_paths]]
        return "\n".join(parts)


def interpret(
    intent: Intent,
    bundle: ResultBundle,
    validation: ValidationReport,
    engine_status: TrustStatus = "certified",
    *,
    model: str = _DEFAULT_MODEL,
    api_key: str | None = None,
) -> InterpretResult:
    """Produce a grounded natural-language interpretation of a completed run.

    Falls back to a template-based interpretation if the Anthropic API is
    unavailable, so the pipeline always produces *some* output.
    """
    try:
        text = _llm_interpret(intent, bundle, validation, engine_status, model=model, api_key=api_key)
    except Exception:
        text = _template_interpret(intent, bundle, validation, engine_status)

    grounding = ground_check(text, bundle)

    if not grounding.passed:
        # Replace the fabricated numbers paragraph with a safe template
        text = _template_interpret(intent, bundle, validation, engine_status)
        grounding = ground_check(text, bundle)

    confidence = min(validation.confidence, 1.0 if engine_status == "certified" else 0.6)

    return InterpretResult(
        text=text,
        status_badge=_STATUS_BADGE[engine_status],
        grounding=grounding,
        confidence=confidence,
        assumptions=intent.assumptions + list(validation.warnings),
        figure_paths=bundle.figure_paths,
    )


def _llm_interpret(
    intent: Intent,
    bundle: ResultBundle,
    validation: ValidationReport,
    engine_status: TrustStatus,
    *,
    model: str,
    api_key: str | None,
) -> str:
    import anthropic

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=key or None)  # type: ignore[arg-type]

    qty_lines = "\n".join(
        f"  {q.name} = {q.value} {q.unit}".rstrip() for q in bundle.quantities
    )
    convergence = "converged" if bundle.converged else "DID NOT CONVERGE"
    regime_note = "" if validation.in_regime else " (out of validated regime — treat with caution)"
    badge = _STATUS_BADGE[engine_status]

    system = (
        "You are a scientific simulation interpreter for the Render platform. "
        "Your job is to explain simulation results in clear, accurate language. "
        "CRITICAL RULE: you must ONLY cite numbers that appear in the provided "
        "ResultBundle quantities list. Never invent or paraphrase numerical values. "
        f"The engine trust status is: {badge}."
    )

    user = (
        f"Question: {intent.question}\n"
        f"Engine: {intent.engine} ({engine_status}){regime_note}\n"
        f"Status: {convergence}\n"
        f"ResultBundle quantities:\n{qty_lines}\n"
        f"Warnings: {'; '.join(bundle.warnings + validation.warnings) or 'none'}\n\n"
        "Write a concise (3-6 sentences) plain-language interpretation of these results. "
        "Cite specific numbers from the ResultBundle. State what the numbers mean physically. "
        "Note any caveats from warnings."
    )

    msg = client.messages.create(
        model=model,
        max_tokens=512,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


def _template_interpret(
    intent: Intent,
    bundle: ResultBundle,
    validation: ValidationReport,
    engine_status: TrustStatus,
) -> str:
    """Fallback template-based interpretation — always grounded."""
    lines = [
        f"Simulation completed using engine '{intent.engine}' for the question: "
        f'"{intent.question}".',
    ]
    if not bundle.converged:
        lines.append("Warning: the simulation did not converge — results may be unreliable.")
    for q in bundle.quantities:
        unit_str = f" {q.unit}" if q.unit else ""
        lines.append(f"Result: {q.name} = {q.value}{unit_str}.")
    if bundle.warnings:
        lines.append("Simulation warnings: " + "; ".join(bundle.warnings) + ".")
    if not validation.in_regime:
        lines.append(
            "Note: this run was outside the engine's validated parameter regime; "
            "interpret with caution."
        )
    if engine_status == "experimental":
        lines.append(
            "This engine has not yet been validated against published reference cases."
        )
    return " ".join(lines)
