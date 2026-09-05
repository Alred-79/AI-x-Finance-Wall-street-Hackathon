"""The AI Security Analyst: investigate, converse, remember, never invent.

Pipeline per question
  1. recall  — is it already settled in the persistent profile? then stop.
  2. search  — retrieve evidence from the company corpus (+ human-confirmed facts)
  3. judge   — LLM decides verified / conflict / user_confirmed / unknown with citations
  4. guard   — code re-checks the model: citations must exist, questionnaire-form
               rows and unread images can never prove a control, empty answers
               cannot be "verified"
  5. record  — write to the profile with history, register any conflict
Every LLM call is traced to PRISM.
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import llm, prism
from .config import QUESTIONNAIRE_PATH
from .prompts import CONVERSATION_SYSTEM, EXTRACTION_SYSTEM, INVESTIGATOR_SYSTEM
from .retrieval import Hit, get_index
from .store import (
    CONFLICT,
    UNKNOWN,
    USER_CONFIRMED,
    VERIFIED,
    ProfileStore,
    get_store,
)

# Categories that can never, on their own, prove a control is in place.
NON_PROVING = {"questionnaire"}


def load_questionnaire() -> dict:
    if not QUESTIONNAIRE_PATH.exists():
        raise FileNotFoundError(
            f"{QUESTIONNAIRE_PATH} missing. Run: python scripts/extract_questionnaire.py"
        )
    return json.loads(QUESTIONNAIRE_PATH.read_text(encoding="utf-8"))


def bootstrap() -> dict:
    """Load the questionnaire into the persistent profile (idempotent)."""
    data = load_questionnaire()
    store = get_store()
    added = store.seed_questions(data["questions"])
    return {
        "questions": data["question_count"],
        "seeded": added,
        "topics": data["topics"],
        "corpus_chunks": get_index().size,
        "corpus_files": len(get_index().files()),
    }


def _question_meta(question_id: str) -> dict:
    for q in load_questionnaire()["questions"]:
        if q["id"] == question_id:
            return q
    return {}


def _format_evidence(hits: list[Hit]) -> str:
    lines = []
    for i, hit in enumerate(hits, start=1):
        flag = ""
        if hit.source_category in NON_PROVING:
            flag = "  [BLANK FORM / REVIEWER PLAYBOOK - NOT PROOF OF A CONTROL]"
        elif hit.kind == "image_unread":
            flag = "  [IMAGE NOT MACHINE-READ - CANNOT VERIFY]"
        lines.append(
            f"[{i}] file={hit.source_file} | where={hit.locator} | "
            f"category={hit.source_category}{flag}\n{hit.text}"
        )
    return "\n\n".join(lines) if lines else "(no excerpts retrieved)"


def _format_memory(facts: list[dict]) -> str:
    if not facts:
        return "(nothing confirmed by a human yet)"
    return "\n".join(
        f"- {f['subject']}: {f['statement']} (from {f['actor']})" for f in facts
    )


# --------------------------------------------------------------------------
# guardrail: verify the model's own claims before we trust them
# --------------------------------------------------------------------------

def _guard(verdict: dict, hits: list[Hit]) -> tuple[dict, list[str]]:
    """Downgrade any verdict the evidence does not actually support."""
    notes: list[str] = []
    status = verdict.get("status", UNKNOWN)
    raw_ids = verdict.get("evidence_ids") or []

    cited: list[Hit] = []
    for value in raw_ids:
        try:
            idx = int(value)
        except (TypeError, ValueError):
            notes.append(f"dropped non-numeric evidence id {value!r}")
            continue
        if 1 <= idx <= len(hits):
            cited.append(hits[idx - 1])
        else:
            notes.append(f"dropped hallucinated evidence id {idx}")

    if status == VERIFIED:
        usable = [
            h for h in cited
            if h.source_category not in NON_PROVING and h.kind != "image_unread"
        ]
        if not usable:
            status = UNKNOWN
            notes.append(
                "downgraded verified -> unknown: no citation from a proving source "
                "(only blank-form rows or unread images)"
            )
            verdict["answer"] = ""
        cited = usable or cited

    if status == VERIFIED and not (verdict.get("answer") or "").strip():
        status = UNKNOWN
        notes.append("downgraded verified -> unknown: empty answer text")

    if status in {UNKNOWN, CONFLICT} and not (verdict.get("followup_question") or "").strip():
        notes.append("no follow-up question supplied by model")

    confidence = float(verdict.get("confidence") or 0.0)
    if status == UNKNOWN:
        confidence = min(confidence, 0.2)
    confidence = max(0.0, min(1.0, confidence))

    verdict["status"] = status
    verdict["confidence"] = confidence
    verdict["_cited"] = [h.to_dict() for h in cited]
    return verdict, notes


# --------------------------------------------------------------------------
# deterministic fallback when no LLM key is configured
# --------------------------------------------------------------------------

def _no_llm_verdict(question: str, hits: list[Hit]) -> dict:
    """Honest degradation: surface evidence, claim nothing."""
    proving = [
        h for h in hits
        if h.source_category not in NON_PROVING and h.kind != "image_unread"
    ]
    return {
        "status": UNKNOWN,
        "answer": "",
        "rationale": (
            f"No reasoning model configured, so this answer was not decided. "
            f"{len(proving)} candidate evidence excerpts were retrieved and are attached "
            "for human review. Per the golden rule this is reported as unknown rather than guessed."
        ),
        "confidence": 0.0,
        "followup_question": f"Can you confirm the current practice for: {question}",
        "_cited": [h.to_dict() for h in proving[:4]],
        "_notes": ["evidence-only mode: set OPENAI_API_KEY or ANTHROPIC_API_KEY to enable reasoning"],
    }


# --------------------------------------------------------------------------
# public: investigate one question
# --------------------------------------------------------------------------

def investigate(
    question_id: str,
    *,
    session_id: str,
    force: bool = False,
    store: ProfileStore | None = None,
) -> dict:
    store = store or get_store()
    existing = store.get_answer(question_id)
    if existing is None:
        raise KeyError(f"unknown question id {question_id!r}")

    # 1. recall — never redo settled work unless explicitly forced
    if not force and existing["status"] in {VERIFIED, USER_CONFIRMED}:
        return {
            "question_id": question_id,
            "question": existing["question"],
            "from_memory": True,
            **{k: existing[k] for k in ("status", "answer", "rationale", "confidence", "evidence")},
        }

    meta = _question_meta(question_id)
    query = existing["question"]
    if meta.get("control_objective"):
        query = f"{query} {meta['control_objective']}"

    # 2. search
    hits = get_index().search(query, k=8)
    memory = store.search_facts(existing["question"], limit=6)

    started = time.time()
    # 3. judge
    if llm.llm_provider_available():
        user_prompt = (
            f"QUESTION [{question_id}] (topic: {existing['topic']})\n{existing['question']}\n\n"
            f"AFFECTED CONTROL: {meta.get('control_id') or 'n/a'} — "
            f"{meta.get('control_objective') or 'n/a'} (criticality: {meta.get('criticality') or 'n/a'})\n\n"
            f"REVIEWER PLAYBOOK (what the enterprise reviewer does with your answer):\n"
            f"{meta.get('reviewer_playbook') or '(none)'}\n\n"
            f"MEMORY (confirmed by humans):\n{_format_memory(memory)}\n\n"
            f"EVIDENCE:\n{_format_evidence(hits)}"
        )
        try:
            verdict = llm.complete_json(
                system=INVESTIGATOR_SYSTEM,
                user=user_prompt,
                step="investigate_question",
                session_id=session_id,
                metadata={
                    "question_id": question_id,
                    "topic": existing["topic"],
                    "control_id": meta.get("control_id", ""),
                    "criticality": meta.get("criticality", ""),
                    "evidence_count": len(hits),
                    "evidence_files": sorted({h.source_file for h in hits}),
                },
            )
            # Guard only applies to model output: it validates the model's own citations.
            verdict, notes = _guard(verdict, hits)
            verdict.setdefault("_notes", []).extend(notes)
        except Exception as exc:
            verdict = _no_llm_verdict(existing["question"], hits)
            verdict["rationale"] = (
                f"The reasoning model could not be reached ({type(exc).__name__}), so this "
                f"answer was not decided. {len(verdict['_cited'])} candidate evidence excerpts "
                "are attached for human review. Reported as unknown rather than guessed."
            )
            verdict["_notes"] = [f"llm_error: {str(exc)[:200]}"]
    else:
        verdict = _no_llm_verdict(existing["question"], hits)

    # 4/5. record
    status = verdict["status"]
    conflict_row = None
    if status == CONFLICT:
        c = verdict.get("conflict") or {}
        conflict_row = store.add_conflict(
            summary=c.get("summary") or f"Conflicting evidence on question {question_id}",
            side_a=c.get("side_a", ""),
            side_b=c.get("side_b", ""),
            question_id=question_id,
            topic=existing["topic"],
            severity=c.get("severity", "medium"),
            detected_by="analyst",
        )

    saved = store.record_answer(
        question_id,
        status=status,
        answer=verdict.get("answer", ""),
        rationale=verdict.get("rationale", ""),
        confidence=verdict.get("confidence", 0.0),
        evidence=verdict.get("_cited", []),
        followup=verdict.get("followup_question", ""),
        actor="analyst",
        reason="automated investigation",
    )

    prism.emit(
        step="question_decision",
        session_id=session_id,
        input_text=f"[{question_id}] {existing['question']}",
        output_text=json.dumps(
            {
                "status": status,
                "answer": verdict.get("answer", ""),
                "confidence": verdict.get("confidence"),
                "citations": [e["citation"] for e in verdict.get("_cited", [])],
            }
        ),
        model=llm.model_name(),
        latency_ms=int((time.time() - started) * 1000),
        metadata={
            "question_id": question_id,
            "control_id": meta.get("control_id", ""),
            "criticality": meta.get("criticality", ""),
            "decision": status,
            "confidence": verdict.get("confidence"),
            "guard_notes": verdict.get("_notes", []),
            "citation_count": len(verdict.get("_cited", [])),
            "conflict_detected": bool(conflict_row),
        },
    )

    return {
        "question_id": question_id,
        "question": existing["question"],
        "topic": existing["topic"],
        "control_id": meta.get("control_id", ""),
        "criticality": meta.get("criticality", ""),
        "from_memory": False,
        "status": saved["status"],
        "answer": saved["answer"],
        "rationale": saved["rationale"],
        "confidence": saved["confidence"],
        "evidence": saved["evidence"],
        "followup": saved["followup"],
        "conflict": conflict_row,
        "guard_notes": verdict.get("_notes", []),
        "candidates_considered": len(hits),
    }


def sweep(
    *, session_id: str, limit: int = 66, only_unknown: bool = True
) -> dict:
    """Investigate the whole questionnaire, highest-criticality questions first."""
    store = get_store()
    meta_by_id = {q["id"]: q for q in load_questionnaire()["questions"]}
    todo = [
        a for a in store.all_answers()
        if not only_unknown or a["status"] not in {VERIFIED, USER_CONFIRMED}
    ]
    todo.sort(
        key=lambda a: (meta_by_id.get(a["question_id"], {}).get("priority", 4),
                       float(a["question_id"]))
    )

    results = []
    for answer in todo[:limit]:
        results.append(investigate(answer["question_id"], session_id=session_id, store=store))
    return {"investigated": len(results), "results": results, "stats": store.stats()}


# --------------------------------------------------------------------------
# public: conversation turn
# --------------------------------------------------------------------------

def next_priority_questions(store: ProfileStore, n: int = 3) -> list[dict]:
    """Most important unanswered questions: open conflicts, then criticality."""
    meta_by_id = {q["id"]: q for q in load_questionnaire()["questions"]}
    answers = store.all_answers()

    def rank(a: dict) -> tuple:
        meta = meta_by_id.get(a["question_id"], {})
        status_rank = {CONFLICT: 0, UNKNOWN: 1, USER_CONFIRMED: 2, VERIFIED: 3}
        return (
            status_rank.get(a["status"], 4),
            meta.get("priority", 4),
            a["asked_count"],
            float(a["question_id"]),
        )

    open_items = [a for a in answers if a["status"] in {CONFLICT, UNKNOWN}]
    open_items.sort(key=rank)
    out = []
    for a in open_items[:n]:
        meta = meta_by_id.get(a["question_id"], {})
        out.append({**a, "control_id": meta.get("control_id", ""),
                    "criticality": meta.get("criticality", ""),
                    "priority": meta.get("priority", 4)})
    return out


def chat_turn(
    *,
    message: str,
    session_id: str,
    speaker: str = "employee",
    channel: str = "text",
) -> dict:
    """One conversational turn: search, answer or ask, extract, remember."""
    store = get_store()
    store.add_message(session_id, "user", message, channel=channel)
    started = time.time()

    index = get_index()
    hits = index.search(message, k=6)
    memory = store.search_facts(message, limit=6)
    priorities = next_priority_questions(store, n=3)
    open_conflicts = store.conflicts("open")[:3]
    stats = store.stats()

    recorded: dict[str, Any] = {"facts": [], "answers": [], "corrections": [], "conflicts_resolved": []}

    def degraded_reply(reason: str) -> dict:
        """Never crash and never guess: hand back real citations and say why."""
        proving = [
            h for h in hits
            if h.source_category not in NON_PROVING and h.kind != "image_unread"
        ]
        if proving:
            top = proving[0]
            body = (
                f"I searched your company documents and the closest match is "
                f"\"{top.doc_title}\" at {top.locator}. I am not going to interpret it for you "
                f"because {reason}, so this is not recorded as an answer. Here is what that "
                f"document says: {top.text[:320]}"
            )
        else:
            body = (
                f"I searched your company documents and found nothing that answers this. "
                f"I am also unable to reason about it because {reason}, so I am leaving this "
                "marked unknown rather than guessing."
            )
        store.add_message(session_id, "assistant", body, channel=channel)
        return {
            "reply": body,
            "evidence": [h.to_dict() for h in hits],
            "recorded": recorded,
            "priorities": priorities,
            "stats": stats,
            "degraded": True,
            "degraded_reason": reason,
        }

    if not llm.llm_provider_available():
        return degraded_reply("no reasoning model is configured in .env")

    transcript = store.transcript(session_id, limit=12)
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in transcript[-10:])

    context = (
        f"CONVERSATION SO FAR:\n{convo or '(this is the first turn)'}\n\n"
        f"EMPLOYEE JUST SAID ({speaker}, via {channel}): {message}\n\n"
        f"PROGRESS: {stats['completion_pct']}% of {stats['total_questions']} questions answered; "
        f"{stats['by_status'].get(UNKNOWN, 0)} unknown; {stats['open_conflicts']} open conflicts.\n\n"
        f"MEMORY (already confirmed — never ask again):\n{_format_memory(memory)}\n\n"
        f"MOST IMPORTANT OPEN QUESTIONS:\n"
        + (
            "\n".join(
                f"- [{p['question_id']}] ({p['status']}, {p.get('criticality') or 'n/a'}) "
                f"{p['question']}"
                + (f"  <- pending follow-up: {p['followup']}" if p["followup"] else "")
                for p in priorities
            )
            or "- (none)"
        )
        + "\n\nOPEN CONFLICTS:\n"
        + (
            "\n".join(f"- [{c['id']}] {c['summary']}" for c in open_conflicts) or "- (none)"
        )
        + f"\n\nEVIDENCE RETRIEVED FOR THIS MESSAGE:\n{_format_evidence(hits)}"
    )

    try:
        reply, _ = llm.complete(
            system=CONVERSATION_SYSTEM,
            user=context,
            step="conversation_turn",
            session_id=session_id,
            metadata={
                "channel": channel,
                "speaker": speaker,
                "evidence_files": sorted({h.source_file for h in hits}),
                "completion_pct": stats["completion_pct"],
                "open_conflicts": stats["open_conflicts"],
            },
            expect_json=False,
            max_tokens=400,
        )
    except Exception as exc:
        # Venue wifi dies, a key expires, a provider rate-limits: the analyst
        # still answers with real citations instead of returning an error page.
        return degraded_reply(f"the reasoning model is unreachable ({type(exc).__name__})")
    reply = reply.strip()
    store.add_message(session_id, "assistant", reply, channel=channel)

    # Extract what the employee actually committed to, and persist it.
    try:
        candidates = "\n".join(
            f"- {p['question_id']}: {p['question']}" for p in priorities
        ) or "(none)"
        extraction = llm.complete_json(
            system=EXTRACTION_SYSTEM,
            user=(
                f"ANALYST ASKED: {transcript[-2]['content'] if len(transcript) >= 2 else '(nothing yet)'}\n"
                f"EMPLOYEE REPLIED: {message}\n\n"
                f"CANDIDATE QUESTIONS:\n{candidates}\n\n"
                f"OPEN CONFLICT IDS: {[c['id'] for c in open_conflicts]}"
            ),
            step="extract_commitments",
            session_id=session_id,
            metadata={"channel": channel, "speaker": speaker},
            max_tokens=700,
        )
    except Exception:
        extraction = {}

    for fact in extraction.get("facts", []) or []:
        statement = (fact.get("statement") or "").strip()
        if not statement:
            continue
        recorded["facts"].append(
            store.add_fact(fact.get("subject", "general"), statement, actor=speaker)
        )

    corrected = {c.get("question_id") for c in (extraction.get("corrections") or [])}
    for item in extraction.get("answers", []) or []:
        qid = str(item.get("question_id", "")).strip()
        text = (item.get("answer") or "").strip()
        if not qid or not text or store.get_answer(qid) is None:
            continue
        saved = store.record_answer(
            qid,
            status=USER_CONFIRMED,
            answer=text,
            rationale=f"Confirmed verbally by {speaker} on {channel}.",
            confidence=float(item.get("confidence") or 0.75),
            evidence=[{
                "citation": f"conversation:{session_id}",
                "source_file": "conversation",
                "locator": f"{speaker} via {channel}",
                "text": message[:600],
                "source_category": "human_attestation",
            }],
            actor=speaker,
            reason="correction by employee" if qid in corrected else "confirmed by employee",
        )
        recorded["answers"].append(
            {"question_id": qid, "status": saved["status"], "answer": saved["answer"],
             "was_correction": qid in corrected}
        )

    resolution = extraction.get("conflict_resolution") or {}
    if resolution.get("conflict_id") and resolution.get("resolution"):
        row = store.resolve_conflict(
            resolution["conflict_id"], resolution["resolution"], actor=speaker
        )
        if row:
            recorded["conflicts_resolved"].append(row)

    prism.emit(
        step="turn_outcome",
        session_id=session_id,
        input_text=message,
        output_text=reply,
        model=llm.model_name(),
        latency_ms=int((time.time() - started) * 1000),
        user_identifier=speaker,
        metadata={
            "channel": channel,
            "facts_recorded": len(recorded["facts"]),
            "answers_recorded": len(recorded["answers"]),
            "corrections": len([a for a in recorded["answers"] if a["was_correction"]]),
            "conflicts_resolved": len(recorded["conflicts_resolved"]),
            "needs_followup": bool(extraction.get("needs_followup")),
            "completion_pct": store.stats()["completion_pct"],
        },
    )

    return {
        "reply": reply,
        "evidence": [h.to_dict() for h in hits],
        "recorded": recorded,
        "needs_followup": bool(extraction.get("needs_followup")),
        "followup_question": extraction.get("followup_question", ""),
        "priorities": next_priority_questions(store, n=3),
        "stats": store.stats(),
        "degraded": False,
    }
