"""LLM provider abstraction — Anthropic API or OpenRouter (OpenAI-compatible).

Auto-selects provider:
  OPENROUTER_API_KEY set → OpenRouter  (model: anthropic/claude-haiku-4-5)
  ANTHROPIC_API_KEY  set → Anthropic   (model: claude-haiku-4-5-20251001)

Override with RENDER_LLM_MODEL for a different model on either provider.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
_DEFAULT_OPENROUTER_MODEL = "anthropic/claude-haiku-4-5"


def get_provider(explicit_key: str | None = None) -> str:
    """Return 'openrouter' or 'anthropic' based on available keys."""
    if explicit_key and explicit_key.startswith("sk-or-"):
        return "openrouter"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    return "anthropic"


def get_api_key(explicit_key: str | None = None) -> str:
    """Return the best available API key."""
    if explicit_key:
        return explicit_key
    provider = get_provider()
    if provider == "openrouter":
        return os.environ.get("OPENROUTER_API_KEY", "")
    return os.environ.get("ANTHROPIC_API_KEY", "")


def get_default_model(provider: str | None = None) -> str:
    """Return the default model name for the given (or auto-detected) provider."""
    p = provider or get_provider()
    custom = os.environ.get("RENDER_LLM_MODEL", "")
    if custom:
        return custom
    return _DEFAULT_OPENROUTER_MODEL if p == "openrouter" else _DEFAULT_ANTHROPIC_MODEL


def make_instructor_client(provider: str, key: str) -> Any:
    """Return an instructor-wrapped client for the given provider."""
    import instructor
    if provider == "openrouter":
        import openai
        return instructor.from_openai(
            openai.OpenAI(base_url=_OPENROUTER_BASE, api_key=key)
        )
    import anthropic
    return instructor.from_anthropic(anthropic.Anthropic(api_key=key or None))  # type: ignore[arg-type]


def instructor_create(
    client: Any,
    provider: str,
    model: str,
    system: str,
    user: str,
    response_model: Any,
    max_tokens: int = 1024,
    max_retries: int = 3,
) -> Any:
    """Call instructor in the format appropriate for the provider."""
    if provider == "openrouter":
        return client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_model=response_model,
            max_retries=max_retries,
        )
    return client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        response_model=response_model,
        max_retries=max_retries,
    )


def raw_text_call(
    provider: str,
    key: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 512,
) -> str:
    """Make a raw (non-structured) LLM call and return the text response."""
    if provider == "openrouter":
        import openai
        oc = openai.OpenAI(base_url=_OPENROUTER_BASE, api_key=key)
        msg = oc.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return msg.choices[0].message.content or ""
    import anthropic
    ac = anthropic.Anthropic(api_key=key or None)  # type: ignore[arg-type]
    msg = ac.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text
