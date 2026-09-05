"""PRISM by Block Convey — observability for the analyst.

Why this exists, in one line: the product's central claim is "this system cannot state a fact it
cannot cite", and a claim like that is worth exactly as much as the evidence you have for it. PRISM
is where that evidence lives.

Three things are traced:

1. **Every model call.** `llm.chat` and `llm.chat_stream` are the only two places this app talks to
   a model, so wrapping them covers claim extraction, conflict judging, answer derivation, exception
   drafting, vision passes and every agent turn. Callers attach `qid` / `control` / `phase` through
   the `step()` context manager instead of threading arguments through a dozen signatures.

2. **Every guardrail override.** Status and confidence are computed in code (`engine.derive`), not by
   the model, and the exporter refuses uncited answers. When that machinery overrules the model —
   the model asserted "Yes", the evidence did not support it, and the answer became UNKNOWN — that
   is the single most important event in the system, and it is recorded as its own trace with
   `override=true`. The count of those is the proof that the golden rule is structural.

3. **Every agent turn, as a trajectory.** Tool calls become ordered steps and PRISM evaluates the
   whole trajectory, so "did the analyst search before it asked?" becomes a score rather than a vibe.

Nothing here is allowed to break or slow the analyst: without credentials every entry point is a
no-op, the SDK posts on background threads, and every public function swallows its own exceptions.
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
import time
from collections import deque
from typing import Any

from ..config import settings

# The step currently being executed, e.g. {"phase": "derive", "qid": "12", "control": "mfa"}.
# A contextvar keeps call sites clean: llm.chat() reads it instead of taking a metadata argument.
_step: contextvars.ContextVar[dict] = contextvars.ContextVar("prism_step", default={})

_client = None
_client_lock = threading.Lock()
_init_error: str | None = None

_lock = threading.Lock()
_counters = {"traces": 0, "overrides": 0, "trajectories": 0, "failed": 0, "skipped": 0}
_recent: deque[dict] = deque(maxlen=100)
_trajectories: deque[dict] = deque(maxlen=25)


# --------------------------------------------------------------------------- client


def configured() -> bool:
    return bool(settings.prism_enabled and settings.prism_api_key and settings.prism_project_id)


def client():
    """The PRISMtrace client, or None when unconfigured / the SDK is absent."""
    global _client, _init_error
    if _client is not None or not configured():
        return _client
    with _client_lock:
        if _client is None:
            try:
                from prismtrace import PRISMtrace

                _client = PRISMtrace(
                    api_key=settings.prism_api_key,
                    host=settings.prism_host,
                    project_id=settings.prism_project_id,
                )
            except Exception as e:  # noqa: BLE001 - never break the app over telemetry
                _init_error = f"{type(e).__name__}: {e}"
    return _client


@contextlib.contextmanager
def step(phase: str, **fields: Any):
    """Tag every model call made inside this block, e.g. `with prism.step("derive", qid="12"):`."""
    token = _step.set({**_step.get(), "phase": phase, **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _step.reset(token)


def current_step() -> dict:
    return dict(_step.get())


def _record(kind: str, detail: dict) -> None:
    with _lock:
        _counters[kind] = _counters.get(kind, 0) + 1
        _recent.appendleft({"at": time.time(), "kind": kind, **detail})


# --------------------------------------------------------------------------- traces


def trace_llm(
    *,
    model: str,
    messages: list[dict],
    output: str,
    latency_ms: int,
    tokens_in: int = 0,
    tokens_out: int = 0,
    metadata: dict | None = None,
) -> None:
    """Record one model call. Safe to call from anywhere; never raises."""
    meta = {"source": "ai-security-analyst", **current_step(), **(metadata or {})}
    if not configured():
        _record("skipped", {"phase": meta.get("phase", "llm"), "reason": "prism not configured"})
        return
    c = client()
    if c is None:
        _record("failed", {"phase": meta.get("phase", "llm"), "reason": _init_error or "client unavailable"})
        return
    try:
        c.trace_llm(
            model=model,
            input_messages=_safe_messages(messages),
            output=(output or "")[:12000],
            latency_ms=max(0, int(latency_ms)),
            token_count_input=int(tokens_in),
            token_count_output=int(tokens_out),
            agent_id=settings.prism_agent_id,
            agent_name=settings.prism_agent_name,
            metadata=meta,
        )
        _record("traces", {"phase": meta.get("phase", "llm"), "model": model, "latency_ms": latency_ms})
    except Exception as e:  # noqa: BLE001
        _record("failed", {"phase": meta.get("phase", "llm"), "reason": f"{type(e).__name__}: {e}"[:200]})


def trace_override(
    *,
    qid: str,
    model_answer: str,
    final_status: str,
    confidence: float,
    reasons: list[str],
    dropped_evidence: list[str] | None = None,
) -> None:
    """The guardrail overruled the model. This is the trace that proves the golden rule is structural.

    `model_answer` is what the model wanted to say; `final_status` is what the evidence actually
    supported after `engine.derive._compute_status` ran in code.
    """
    detail = {
        "qid": qid,
        "override": True,
        "model_answer": model_answer,
        "final_status": final_status,
        "confidence": confidence,
        "reasons": reasons,
        "dropped_evidence_ids": dropped_evidence or [],
    }
    with _lock:
        _counters["overrides"] += 1
        _recent.appendleft({"at": time.time(), "kind": "overrides", "phase": "guardrail", **detail})
    if not configured():
        return
    c = client()
    if c is None:
        return
    try:
        c.trace_llm(
            model="guardrail:engine.derive",
            input_messages=[{"role": "user", "content": f"Q{qid}: model proposed {model_answer!r}"}],
            output=f"{final_status} (confidence {confidence}) — " + "; ".join(reasons),
            latency_ms=0,
            agent_id=settings.prism_agent_id,
            agent_name=settings.prism_agent_name,
            metadata={"source": "ai-security-analyst", "phase": "guardrail", **detail},
        )
    except Exception:  # noqa: BLE001
        pass


def submit_trajectory(
    *,
    session: str,
    user_text: str,
    reply: str,
    events: list[dict],
    grounding: dict | None = None,
    duration_ms: int = 0,
) -> None:
    """One analyst turn as an ordered trajectory, for PRISM to evaluate.

    The grounding mode becomes the final status: a turn that asserted facts with no company evidence
    behind them ("no_knowledge") is not a success, and PRISM should see it that way.
    """
    mode = (grounding or {}).get("mode", "conversational")
    steps: list[dict] = [
        {
            "step_type": "tool_call",
            "label": e.get("tool", "tool"),
            "tool_name": e.get("tool", "tool"),
            "input_summary": str(e.get("args", ""))[:500],
            "output_summary": "ok" if e.get("ok") else "error",
            "status": "success" if e.get("ok") else "error",
        }
        for e in (events or [])
    ]
    receipts = (grounding or {}).get("receipts") or []
    steps.append(
        {
            "step_type": "final_answer",
            "label": f"reply ({mode})",
            "input_summary": (user_text or "")[:500],
            "output_summary": (reply or "")[:1000],
            "status": "success" if mode in ("grounded", "conversational") else "error",
            "duration_ms": duration_ms,
        }
    )
    summary = {
        "session": session,
        "mode": mode,
        "tools": [e.get("tool") for e in (events or [])],
        "receipts": len(receipts),
        "uncited": len((grounding or {}).get("uncited") or []),
        "at": time.time(),
    }
    with _lock:
        _counters["trajectories"] += 1
        _trajectories.appendleft(summary)
    if not configured():
        return
    c = client()
    if c is None:
        return
    try:
        c.submit_trajectory(
            steps=steps,
            agent_id=settings.prism_agent_id,
            agent_name=settings.prism_agent_name,
            conversation_id=session,
            model=settings.model_agent,
            final_status="success" if mode in ("grounded", "conversational") else "failure",
            async_send=True,
        )
    except Exception:  # noqa: BLE001
        pass


def flush(timeout: float = 2.0) -> None:
    c = client()
    if c is not None:
        with contextlib.suppress(Exception):
            c.flush(timeout=timeout)


# --------------------------------------------------------------------------- status


def _safe_messages(messages: list[dict]) -> list[dict]:
    """Trim message content and drop image payloads: a base64 diagram is not worth tracing."""
    out = []
    for m in messages or []:
        content = m.get("content")
        if isinstance(content, list):  # vision call
            content = " ".join(p.get("text", "[image]") for p in content if isinstance(p, dict))
        out.append({"role": m.get("role", "user"), "content": str(content or "")[:4000]})
    return out[-12:]


def health() -> dict:
    """What the UI shows: whether PRISM is on, and what has been sent so far."""
    with _lock:
        counters = dict(_counters)
        recent = list(_recent)[:30]
        trajectories = list(_trajectories)[:10]
    return {
        "configured": configured(),
        "enabled": settings.prism_enabled,
        "host": settings.prism_host,
        "project_id_set": bool(settings.prism_project_id),
        "agent_id": settings.prism_agent_id,
        "sdk_error": _init_error,
        "counters": counters,
        "recent": recent,
        "trajectories": trajectories,
    }
