"""PRISM by Block Convey — trace emission.

PRISM is the hackathon's mandatory observability layer. Every reasoning step the
analyst takes becomes one PRISM trace, so the Build -> Observe -> Improve ->
Prove loop runs on real telemetry instead of a screenshot.

Design notes:
  * Non-blocking. Traces go out on a background thread; a PRISM outage can
    never break the analyst or slow the demo.
  * session_id = the analyst session, so all turns assemble into one PRISM
    session and the whole investigation is reviewable as a single trajectory.
  * metadata carries the compliance semantics (question id, control id,
    decision status, confidence, evidence citations) so PRISM can be filtered
    by "which answers were unknown" or "which turns hit a conflict".
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

import requests

from .config import (
    PRISM_AGENT_ID,
    PRISM_AGENT_NAME,
    PRISM_API_KEY,
    PRISM_HOST,
    PRISM_PROJECT_ID,
    prism_configured,
)

TIMEOUT = 8
_recent: deque[dict] = deque(maxlen=200)
_lock = threading.Lock()
_counters = {"sent": 0, "failed": 0, "skipped": 0}


def _post(payload: dict) -> None:
    try:
        resp = requests.post(
            f"{PRISM_HOST}/api/traces",
            headers={
                "Content-Type": "application/json",
                "X-PRISMtrace-Key": PRISM_API_KEY,
            },
            json=payload,
            timeout=TIMEOUT,
        )
        ok = resp.status_code == 200
        with _lock:
            _counters["sent" if ok else "failed"] += 1
            _recent.appendleft(
                {
                    "at": time.time(),
                    "status": resp.status_code,
                    "step": payload.get("metadata", {}).get("step"),
                    "ok": ok,
                    "detail": None if ok else resp.text[:300],
                }
            )
    except Exception as exc:  # network hiccup must never break the analyst
        with _lock:
            _counters["failed"] += 1
            _recent.appendleft(
                {
                    "at": time.time(),
                    "status": None,
                    "step": payload.get("metadata", {}).get("step"),
                    "ok": False,
                    "detail": str(exc)[:300],
                }
            )


def emit(
    *,
    step: str,
    session_id: str,
    input_text: str,
    output_text: str,
    model: str,
    latency_ms: int,
    tokens_in: int = 0,
    tokens_out: int = 0,
    user_identifier: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Fire one PRISM trace. Safe to call from anywhere; never raises."""
    if not prism_configured():
        with _lock:
            _counters["skipped"] += 1
            _recent.appendleft(
                {
                    "at": time.time(),
                    "status": "unconfigured",
                    "step": step,
                    "ok": False,
                    "detail": "PRISM credentials not set in .env",
                }
            )
        return

    payload = {
        "project_id": PRISM_PROJECT_ID,
        "model": model,
        "input_messages": [{"role": "user", "content": input_text[:12000]}],
        "output_message": output_text[:12000],
        "latency_ms": max(0, int(latency_ms)),
        "token_count_input": int(tokens_in),
        "token_count_output": int(tokens_out),
        "session_id": session_id,
        "agent_id": PRISM_AGENT_ID,
        "agent_name": PRISM_AGENT_NAME,
        "metadata": {"step": step, "source": "risk-and-compliance", **(metadata or {})},
    }
    if user_identifier:
        payload["user_identifier"] = user_identifier

    threading.Thread(target=_post, args=(payload,), daemon=True).start()


def health() -> dict:
    with _lock:
        return {
            "configured": prism_configured(),
            "host": PRISM_HOST,
            "project_id_set": bool(PRISM_PROJECT_ID),
            "agent_id": PRISM_AGENT_ID,
            "counters": dict(_counters),
            "recent": list(_recent)[:25],
        }
