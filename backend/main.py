"""FastAPI server for the RiskAndCompliance AI Security Analyst."""
from __future__ import annotations

import time
import uuid
from typing import Any

import requests
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import analyst, conflicts, export, llm, prism
from .config import (
    CORS_ORIGINS,
    ELEVENLABS_AGENT_ID,
    ELEVENLABS_API_KEY,
    llm_provider,
    prism_configured,
)
from .retrieval import get_index
from .store import CONFLICT, UNKNOWN, USER_CONFIRMED, VERIFIED, get_store

app = FastAPI(
    title="RiskAndCompliance — AI Security Analyst",
    version="0.1.0",
    description=(
        "Completes enterprise security questionnaires from a company's own documents. "
        "Searches before asking, cites every answer, detects contradictions, remembers "
        "what it learns, and never invents an answer. Observed end to end in PRISM."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_SESSION = "analyst-session-1"


# ---------------------------------------------------------------- models


class ChatIn(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = DEFAULT_SESSION
    speaker: str = "employee"
    channel: str = "text"


class InvestigateIn(BaseModel):
    question_id: str
    session_id: str = DEFAULT_SESSION
    force: bool = False


class SweepIn(BaseModel):
    session_id: str = DEFAULT_SESSION
    limit: int = 66
    only_unknown: bool = True


class SearchIn(BaseModel):
    query: str = Field(min_length=2)
    k: int = 8


class AnswerIn(BaseModel):
    question_id: str
    answer: str
    status: str = USER_CONFIRMED
    confidence: float = 0.8
    actor: str = "employee"
    reason: str = "manual entry"


class ResolveIn(BaseModel):
    conflict_id: str
    resolution: str
    actor: str = "employee"


class VoiceToolIn(BaseModel):
    """Called by the ElevenLabs agent as a server-side webhook tool."""

    tool: str
    session_id: str = DEFAULT_SESSION
    query: str | None = None
    question_id: str | None = None
    answer: str | None = None
    subject: str | None = None
    statement: str | None = None
    speaker: str = "employee (voice)"


# ---------------------------------------------------------------- status


@app.get("/api/health")
def health() -> dict:
    store = get_store()
    try:
        index_size = get_index().size
        index_files = len(get_index().files())
        index_error = None
    except FileNotFoundError as exc:
        index_size, index_files, index_error = 0, 0, str(exc)

    return {
        "ok": True,
        "llm_provider": llm_provider(),
        "llm_model": llm.model_name(),
        "reasoning_enabled": llm.llm_provider_available(),
        "corpus": {"chunks": index_size, "files": index_files, "error": index_error},
        "prism": {"configured": prism_configured(), **prism.health()["counters"]},
        "voice": {"configured": bool(ELEVENLABS_AGENT_ID and ELEVENLABS_API_KEY)},
        "profile": store.stats(),
    }


@app.get("/api/prism/health")
def prism_health() -> dict:
    return prism.health()


@app.post("/api/bootstrap")
def bootstrap() -> dict:
    return analyst.bootstrap()


# ---------------------------------------------------------------- profile


@app.get("/api/questionnaire")
def questionnaire() -> dict:
    store = get_store()
    meta = {q["id"]: q for q in analyst.load_questionnaire()["questions"]}
    answers = store.all_answers()
    enriched = []
    for a in answers:
        m = meta.get(a["question_id"], {})
        enriched.append(
            {
                **a,
                "control_id": m.get("control_id", ""),
                "control_objective": m.get("control_objective", ""),
                "criticality": m.get("criticality", ""),
                "reviewer_playbook": m.get("reviewer_playbook", ""),
                "priority": m.get("priority", 4),
            }
        )
    return {
        "stats": store.stats(),
        "answers": enriched,
        "topics": sorted({a["topic"] for a in answers}),
    }


@app.get("/api/profile")
def profile() -> dict:
    store = get_store()
    return {
        "stats": store.stats(),
        "facts": store.facts(),
        "conflicts": store.conflicts(),
        "priorities": analyst.next_priority_questions(store, n=6),
    }


@app.get("/api/answer/{question_id}")
def get_answer(question_id: str) -> dict:
    store = get_store()
    answer = store.get_answer(question_id)
    if not answer:
        raise HTTPException(404, f"no such question {question_id}")
    return {**answer, "history": store.history(question_id)}


@app.post("/api/answer")
def set_answer(payload: AnswerIn) -> dict:
    store = get_store()
    if not store.get_answer(payload.question_id):
        raise HTTPException(404, f"no such question {payload.question_id}")
    saved = store.record_answer(
        payload.question_id,
        status=payload.status,
        answer=payload.answer,
        rationale=f"Provided directly by {payload.actor}.",
        confidence=payload.confidence,
        evidence=[
            {
                "citation": f"direct entry by {payload.actor}",
                "source_file": "conversation",
                "locator": "manual entry",
                "text": payload.answer[:600],
                "source_category": "human_attestation",
            }
        ],
        actor=payload.actor,
        reason=payload.reason,
    )
    prism.emit(
        step="human_correction",
        session_id=DEFAULT_SESSION,
        input_text=f"[{payload.question_id}] manual answer by {payload.actor}",
        output_text=payload.answer,
        model="human",
        latency_ms=0,
        user_identifier=payload.actor,
        metadata={"question_id": payload.question_id, "reason": payload.reason},
    )
    return saved


# ---------------------------------------------------------------- analysis


@app.post("/api/investigate")
def investigate(payload: InvestigateIn) -> dict:
    try:
        return analyst.investigate(
            payload.question_id, session_id=payload.session_id, force=payload.force
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/sweep")
def sweep(payload: SweepIn) -> dict:
    return analyst.sweep(
        session_id=payload.session_id,
        limit=payload.limit,
        only_unknown=payload.only_unknown,
    )


@app.post("/api/search")
def search(payload: SearchIn) -> dict:
    hits = get_index().search(payload.query, k=payload.k)
    return {"query": payload.query, "hits": [h.to_dict() for h in hits]}


@app.post("/api/conflicts/detect")
def detect_conflicts(session_id: str = Body(default=DEFAULT_SESSION, embed=True)) -> dict:
    return conflicts.detect(session_id=session_id)


@app.get("/api/conflicts")
def list_conflicts(status: str | None = None) -> dict:
    return {"conflicts": get_store().conflicts(status)}


@app.post("/api/conflicts/resolve")
def resolve_conflict(payload: ResolveIn) -> dict:
    row = get_store().resolve_conflict(payload.conflict_id, payload.resolution, payload.actor)
    if not row:
        raise HTTPException(404, "no such conflict")
    prism.emit(
        step="conflict_resolved",
        session_id=DEFAULT_SESSION,
        input_text=payload.conflict_id,
        output_text=payload.resolution,
        model="human",
        latency_ms=0,
        user_identifier=payload.actor,
        metadata={"conflict_id": payload.conflict_id},
    )
    return row


@app.post("/api/chat")
def chat(payload: ChatIn) -> dict:
    return analyst.chat_turn(
        message=payload.message,
        session_id=payload.session_id,
        speaker=payload.speaker,
        channel=payload.channel,
    )


@app.get("/api/transcript")
def transcript(session_id: str = DEFAULT_SESSION) -> dict:
    return {"messages": get_store().transcript(session_id, limit=200)}


# ---------------------------------------------------------------- voice


@app.get("/api/voice/config")
def voice_config() -> dict:
    """Frontend asks whether voice is available and which agent to dial."""
    return {
        "enabled": bool(ELEVENLABS_AGENT_ID),
        "agent_id": ELEVENLABS_AGENT_ID,
        "has_api_key": bool(ELEVENLABS_API_KEY),
    }


@app.get("/api/voice/signed-url")
def voice_signed_url() -> dict:
    """Mint a short-lived conversation token so the browser never sees the API key."""
    if not (ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID):
        raise HTTPException(400, "ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID must be set in .env")
    try:
        resp = requests.get(
            "https://api.elevenlabs.io/v1/convai/conversation/token",
            params={"agent_id": ELEVENLABS_AGENT_ID},
            headers={"xi-api-key": ELEVENLABS_API_KEY},
            timeout=15,
        )
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"ElevenLabs error: {resp.text[:300]}")
        return resp.json()
    except requests.RequestException as exc:
        raise HTTPException(502, f"could not reach ElevenLabs: {exc}") from exc


@app.post("/api/voice/tool")
def voice_tool(payload: VoiceToolIn) -> dict:
    """Server-side tools the ElevenLabs voice agent can call mid-conversation.

    Keeping these server-side means the voice agent reads from the same evidence
    index and writes to the same persistent profile as the text chat, so a phone
    call and a browser session build one shared security profile.
    """
    store = get_store()
    started = time.time()
    tool = payload.tool

    if tool == "search_company_evidence":
        if not payload.query:
            raise HTTPException(400, "query required")
        hits = get_index().search(payload.query, k=4)
        result: dict[str, Any] = {
            "found": bool(hits),
            "evidence": [
                {
                    "document": h.doc_title,
                    "where": h.locator,
                    "category": h.source_category,
                    "excerpt": h.text[:500],
                    "can_prove_control": h.source_category != "questionnaire"
                    and h.kind != "image_unread",
                }
                for h in hits
            ],
        }

    elif tool == "get_next_question":
        priorities = analyst.next_priority_questions(store, n=3)
        result = {
            "questions": [
                {
                    "question_id": p["question_id"],
                    "question": p["question"],
                    "status": p["status"],
                    "criticality": p.get("criticality", ""),
                    "pending_followup": p["followup"],
                }
                for p in priorities
            ],
            "progress": store.stats(),
        }

    elif tool == "record_answer":
        if not (payload.question_id and payload.answer):
            raise HTTPException(400, "question_id and answer required")
        if not store.get_answer(payload.question_id):
            raise HTTPException(404, f"no such question {payload.question_id}")
        saved = store.record_answer(
            payload.question_id,
            status=USER_CONFIRMED,
            answer=payload.answer,
            rationale=f"Stated verbally by {payload.speaker}.",
            confidence=0.8,
            evidence=[
                {
                    "citation": f"voice conversation ({payload.speaker})",
                    "source_file": "voice_conversation",
                    "locator": payload.session_id,
                    "text": payload.answer[:600],
                    "source_category": "human_attestation",
                }
            ],
            actor=payload.speaker,
            reason="recorded during voice call",
        )
        result = {"recorded": True, "question_id": payload.question_id, "status": saved["status"]}

    elif tool == "record_fact":
        if not payload.statement:
            raise HTTPException(400, "statement required")
        fact = store.add_fact(
            payload.subject or "general", payload.statement, actor=payload.speaker
        )
        result = {"recorded": True, "fact_id": fact["id"]}

    elif tool == "get_open_conflicts":
        rows = store.conflicts("open")
        result = {
            "count": len(rows),
            "conflicts": [
                {
                    "conflict_id": c["id"],
                    "summary": c["summary"],
                    "severity": c["severity"],
                    "stated": c["side_a"][:300],
                    "observed": c["side_b"][:300],
                }
                for c in rows[:3]
            ],
        }

    elif tool == "resolve_conflict":
        if not (payload.question_id and payload.statement):
            raise HTTPException(400, "question_id (conflict id) and statement required")
        row = store.resolve_conflict(payload.question_id, payload.statement, payload.speaker)
        result = {"resolved": bool(row)}

    else:
        raise HTTPException(400, f"unknown tool {tool!r}")

    prism.emit(
        step=f"voice_tool:{tool}",
        session_id=payload.session_id,
        input_text=payload.model_dump_json(),
        output_text=str(result)[:4000],
        model="elevenlabs-voice-agent",
        latency_ms=int((time.time() - started) * 1000),
        user_identifier=payload.speaker,
        metadata={"tool": tool, "channel": "voice"},
    )
    return result


# ---------------------------------------------------------------- export


@app.post("/api/export/workbook")
def export_wb() -> dict:
    path = export.export_workbook()
    return {"file": path.name, "path": str(path), "download": f"/api/download/{path.name}"}


@app.post("/api/export/report")
def export_rep() -> dict:
    path = export.export_report()
    return {"file": path.name, "path": str(path), "download": f"/api/download/{path.name}"}


@app.get("/api/download/{filename}")
def download(filename: str) -> FileResponse:
    from .config import EXPORT_DIR

    # Prevent path traversal: only serve plain names inside the export dir.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "invalid filename")
    path = EXPORT_DIR / filename
    if not path.exists():
        raise HTTPException(404, "no such export")
    return FileResponse(path, filename=filename)


@app.post("/api/reset")
def reset() -> dict:
    store = get_store()
    store.reset()
    return {"reset": True, **analyst.bootstrap()}


def run() -> None:
    import uvicorn

    from .config import API_HOST, API_PORT

    uvicorn.run("backend.main:app", host=API_HOST, port=API_PORT, reload=False)


if __name__ == "__main__":
    run()
