"""Grounded natural-language interpreter for simulation results.

The interpreter calls Claude to produce a plain-language explanation, then
runs a number-grounding check (layer 7) to ensure no values were fabricated.
Every cited number must appear in the ResultBundle.

The output carries a STATUS BADGE reflecting the engine's trust level:
  ✓ CERTIFIED  — validated against published reference cases
  ⚠ EXPERIMENTAL — not yet validated; treat with caution
"""

from __future__ import annotations

from dataclasses import dataclass, field

from render.interpret.grounding import ground_check
from render.llm import get_api_key as _get_api_key
from render.llm import get_default_model as _get_default_model
from render.llm import get_provider as _get_provider
from render.llm import raw_text_call as _raw_text_call
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
    # Try the LLM up to twice: a plain pass, then (if it cited an ungrounded
    # number) a stricter pass that allows only the exact result values. Fall
    # back to the grounded template only if both fail or the API is unavailable.
    text: str | None = None
    grounding: ValidationReport | None = None
    for attempt in range(2):
        try:
            text = _llm_interpret(intent, bundle, validation, engine_status,
                                  model=model, api_key=api_key, strict=(attempt == 1))
        except Exception:
            text = None
            break
        grounding = ground_check(text, bundle)
        if grounding.passed:
            break

    if text is None or grounding is None or not grounding.passed:
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
    strict: bool = False,
) -> str:
    provider = _get_provider(api_key)
    key = _get_api_key(api_key)
    if model == _DEFAULT_MODEL:
        model = _get_default_model(provider)

    qty_lines = "\n".join(
        f"  {q.name} = {q.value} {q.unit}".rstrip() for q in bundle.quantities
    )
    convergence = "converged" if bundle.converged else "DID NOT CONVERGE"
    regime_note = "" if validation.in_regime else " (out of validated regime — treat with caution)"

    system = (
        "You explain scientific simulation results to a curious, intelligent reader who is "
        "NOT a specialist. Write in plain, simple English: short sentences, everyday words, no "
        "jargon (if a technical term is unavoidable, add a 4-5 word gloss). "
        "CRITICAL RULE: only state numbers that appear in the results list below; you may round "
        "them sensibly for readability, but never invent a value. Do NOT cite reference years, "
        "papers, or numbers that aren't in the list."
    )

    strict_note = (
        "\nIMPORTANT: use ONLY the exact numbers listed above (rounding is fine). Do not introduce "
        "any other number, date, or derived figure. A rate such as 0.98 may be written as 98%."
        if strict else
        "\nYou may write a rate like 0.98 as 98%. Keep numbers faithful to the list above."
    )
    user = (
        f"The user asked: {intent.question}\n"
        f"Engine used: {intent.engine} ({engine_status}){regime_note}\n"
        f"Converged: {convergence}\n"
        f"Results:\n{qty_lines}\n"
        f"Warnings: {'; '.join(bundle.warnings + validation.warnings) or 'none'}\n\n"
        "In 2-4 short, simple sentences, explain what this means. Start with the single most "
        "important takeaway in plain language a non-expert would understand, then briefly say "
        "what the key numbers tell us and why they matter. Mention any caveat from the warnings. "
        "Do not restate the question or name the engine." + strict_note
    )

    return _raw_text_call(provider, key, model, system, user, max_tokens=400)


def _fmt(value: object) -> str:
    """Round a numeric value for readable prose; leave non-numbers as-is."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if float(value).is_integer():
        return str(int(value))
    return f"{float(value):.4g}"


def _template_interpret(
    intent: Intent,
    bundle: ResultBundle,
    validation: ValidationReport,
    engine_status: TrustStatus,
) -> str:
    """Fallback plain-language summary — always grounded, used when the LLM is unavailable."""
    if bundle.converged:
        lines = ["The simulation ran successfully. Here is what it found:"]
    else:
        lines = ["The simulation did not fully converge, so treat these numbers with caution:"]
    parts = []
    for q in bundle.quantities:
        unit_str = f" {q.unit}" if q.unit else ""
        parts.append(f"{q.name} = {_fmt(q.value)}{unit_str}")
    if parts:
        lines.append("; ".join(parts) + ".")
    if bundle.warnings:
        lines.append("Note: " + "; ".join(bundle.warnings) + ".")
    if not validation.in_regime:
        lines.append(
            "This run was outside the range the engine has been validated for, "
            "so the results are less certain."
        )
    if engine_status == "experimental":
        lines.append(
            "This engine is experimental — it has not yet been checked against known results."
        )
    return " ".join(lines)
