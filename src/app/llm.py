"""Thin LLM client over OpenRouter's OpenAI-compatible API.

Provides: chat (with optional tools), json (structured output parsed from text), vision.
All calls are synchronous; callers parallelise with threads where needed.
"""

from __future__ import annotations

import base64
import json
import re
import time
from typing import Any

from openai import OpenAI

from .config import settings

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set (see .env.example)")
        _client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/regodit-security-analyst",
                "X-Title": "AI Security Analyst",
            },
        )
    return _client


def chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    retries: int = 3,
) -> Any:
    """Return the raw first choice message (has .content and .tool_calls)."""
    kwargs: dict[str, Any] = dict(
        model=model or settings.model_agent,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client().chat.completions.create(**kwargs)
            return resp.choices[0].message
        except Exception as e:  # noqa: BLE001 - retry on any transport/rate error
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"LLM call failed after {retries} attempts: {last}")


class StreamedMessage:
    """Accumulates a streamed assistant turn into the same shape as a non-streamed message."""

    def __init__(self):
        self.content = ""
        self._tools: dict[int, dict] = {}

    def add_tool_delta(self, d) -> None:
        slot = self._tools.setdefault(d.index, {"id": "", "name": "", "arguments": ""})
        if d.id:
            slot["id"] = d.id
        if d.function and d.function.name:
            slot["name"] += d.function.name
        if d.function and d.function.arguments:
            slot["arguments"] += d.function.arguments

    @property
    def tool_calls(self) -> list[dict]:
        return [self._tools[i] for i in sorted(self._tools)]


def chat_stream(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
):
    """Yield ("delta", text) as tokens arrive, then ("message", StreamedMessage) once the turn is complete."""
    kwargs: dict[str, Any] = dict(model=model or settings.model_agent, messages=messages, temperature=temperature,
                                  max_tokens=max_tokens, stream=True)
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    acc = StreamedMessage()
    for chunk in client().chat.completions.create(**kwargs):
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        if delta.content:
            acc.content += delta.content
            yield "delta", delta.content
        for tc in delta.tool_calls or []:
            acc.add_tool_delta(tc)
    yield "message", acc


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(text: str) -> Any:
    """Extract the first JSON object/array from a model reply."""
    if not text:
        raise ValueError("empty model reply")
    m = _JSON_BLOCK.search(text)
    candidate = m.group(1) if m else text
    candidate = candidate.strip()
    # Trim to the outermost bracket pair
    start = min([i for i in (candidate.find("{"), candidate.find("[")) if i != -1], default=-1)
    if start == -1:
        raise ValueError(f"no JSON in reply: {text[:200]}")
    end = max(candidate.rfind("}"), candidate.rfind("]"))
    return json.loads(candidate[start : end + 1])


def json_call(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> Any:
    """Ask for JSON and parse it. Retries once with a nudge if parsing fails."""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    msg = chat(msgs, model=model or settings.model_fast, max_tokens=max_tokens, temperature=temperature)
    try:
        return parse_json(msg.content or "")
    except (ValueError, json.JSONDecodeError):
        msgs.append({"role": "assistant", "content": msg.content or ""})
        msgs.append({"role": "user", "content": "Reply with ONLY valid JSON, no prose."})
        msg = chat(msgs, model=model or settings.model_fast, max_tokens=max_tokens, temperature=0.0)
        return parse_json(msg.content or "")


def describe_image(path: str, prompt: str) -> str:
    """Vision call for diagrams / scanned documents."""
    data = base64.b64encode(open(path, "rb").read()).decode()
    ext = path.rsplit(".", 1)[-1].lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
    msg = chat(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
                ],
            }
        ],
        model=settings.model_vision,
        max_tokens=1500,
    )
    return msg.content or ""
