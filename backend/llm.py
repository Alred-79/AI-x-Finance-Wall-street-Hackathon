"""LLM access with a hard no-invention contract, traced to PRISM.

Two providers (OpenAI-compatible, Anthropic) plus an honest 'none' mode: with no
API key the app still runs, retrieval still returns real citations, and answers
are marked `unknown` rather than guessed. Degrading to silence is correct
behaviour for a compliance tool; degrading to a guess is not.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from . import prism
from .config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    llm_provider,
)


class LLMUnavailable(RuntimeError):
    """Raised when no reasoning backend is configured."""


def llm_provider_available() -> bool:
    """True when a reasoning backend is configured."""
    return llm_provider() != "none"


def model_name() -> str:
    provider = llm_provider()
    if provider == "openai":
        return OPENAI_MODEL
    if provider == "anthropic":
        return ANTHROPIC_MODEL
    return "evidence-only-no-llm"


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    start = -1
    raise ValueError(f"no JSON object in model reply: {text[:300]}")


def complete(
    *,
    system: str,
    user: str,
    step: str,
    session_id: str,
    metadata: dict | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1200,
    expect_json: bool = True,
) -> tuple[str, dict]:
    """Run one completion. Returns (raw_text, usage). Always emits a PRISM trace."""
    provider = llm_provider()
    if provider == "none":
        raise LLMUnavailable("No OPENAI_API_KEY or ANTHROPIC_API_KEY configured")

    started = time.time()
    tokens_in = tokens_out = 0
    text = ""
    error: str | None = None

    try:
        if provider == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
            kwargs: dict[str, Any] = {
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if expect_json:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            text = resp.choices[0].message.content or ""
            if resp.usage:
                tokens_in = resp.usage.prompt_tokens or 0
                tokens_out = resp.usage.completion_tokens or 0
        else:
            import anthropic

            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model=ANTHROPIC_MODEL,
                system=system,
                messages=[{"role": "user", "content": user}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = "".join(
                block.text for block in resp.content if getattr(block, "type", "") == "text"
            )
            tokens_in = resp.usage.input_tokens
            tokens_out = resp.usage.output_tokens
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        latency = int((time.time() - started) * 1000)
        prism.emit(
            step=step,
            session_id=session_id,
            input_text=f"[system]\n{system}\n\n[user]\n{user}",
            output_text=text or f"ERROR: {error}",
            model=model_name(),
            latency_ms=latency,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            metadata={**(metadata or {}), "provider": provider, "error": error},
        )

    return text, {"tokens_in": tokens_in, "tokens_out": tokens_out}


def complete_json(**kwargs: Any) -> dict[str, Any]:
    text, _ = complete(**kwargs)
    return _extract_json(text)
