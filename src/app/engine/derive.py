"""Derive the questionnaire answer for each question from claims, user statements, conflicts, external findings.

Status and confidence are computed deterministically in code from the LLM's slot assessment, so the model
cannot 'decide' to be confident: no evidence → UNKNOWN; open conflict → CONFLICT (confidence ≤ 0.5);
template-only evidence contributes nothing.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..catalog.loader import Question, get_catalog
from ..config import settings
from ..llm import json_call
from ..observability import prism
from ..store.db import Store, loads, now
from .conflicts import open_conflicts_for

AUTH_CONF = {4: 0.92, 3: 0.82, 2: 0.72, 1: 0.0, 0: 0.0}
USER_CONF = 0.88
STATUS_ORDER = ["VERIFIED", "CONFIRMED_BY_USER", "PARTIAL", "CONFLICT", "UNKNOWN"]

SYSTEM = """You are a meticulous security analyst completing a vendor security questionnaire on behalf of {vendor}.
You get ONE question, its required slots, and ALL available evidence:
- CLAIMS from company documents, each with an id (C#), authority (4 record/observed > 3 audited attestation > 2 policy/contract > 1 template) and source
- EMPLOYEE STATEMENTS from interviews (U#), attributed and timestamped — authoritative for current state unless a newer record contradicts them
- OPEN CONFLICTS between sources (do not pick a side; describe both; answer_value must be "Unknown" unless an employee statement resolves it)
- EXTERNAL FINDINGS from the public web (X#) — these never establish an internal control; they may support company-profile facts (entity, locations, founders) and raise questions

Hard rules:
1. Never state anything the evidence does not support. Absence of evidence → response "Unknown — needs confirmation" and comments "Not covered by company documents. Ask: {owner_role}."
2. TEMPLATE claims (authority 1) are not evidence of practice. Mention them only to note a template exists.
3. Yes/No questions: answer_value ∈ {Yes, No, Partial, Unknown}. An honest "No" with justification beats an inflated "Yes". Never answer Yes based only on a template or an external finding.
4. Prefer the most authoritative and most recent evidence; when a record contradicts a policy, the record describes practice.
5. Write "response" as the buyer-facing text for the 'Vendor Response' cell: 1-3 factual sentences that name their sources inline as receipts, in exactly this fixed format: documents → [Access Control Policy §5, 14 Jul 2026] (document name + section/row when known + date); employee statements → (confirmed by Sahil (CTO), 5 Sep 2026); public web → [public: tracxn.com]. At most TWO receipts in the response; the rest belong in evidence_ids. Write "comments" for the 'Comments / Clarification' cell: nuances, admissions, dates, planned improvements, what is confirmed by whom.
6. slot_assessment must cover EVERY slot: {"slot": {"filled": true|false, "value": "...", "evidence_ids": ["C12","U3"]}}. A slot is filled only if evidence (not a template) supports a concrete value.
7. next_question: if any slot is unfilled or conflicted, ONE precise question for the employee (their role: {owner_role}) that fills the most important gap and does not re-ask anything already answered; otherwise "".
8. evidence_ids: every C#/U#/X# id you relied on.
9. "{vendor}", "{brand}", "{brand} AI" and "{brand_upper} Inc." are the SAME organisation (legal entity vs brand). Never mark an answer Unknown or Partial because sources use different names for the company; only a genuinely different fact (e.g. two different named CEOs, an audit period that cannot be right) counts.

Return ONLY JSON: {"response": "...", "comments": "...", "answer_value": "...", "slot_assessment": {...}, "evidence_ids": [...], "next_question": "...", "notes_for_analyst": "..."}"""


def _evidence_bundle(store: Store, q: Question) -> dict:
    ph = ",".join("?" for _ in q.controls)
    claims = store.q(
        f"SELECT c.id, c.control, c.attribute, c.value, c.statement, c.excerpt, c.authority, c.modality, c.observed_at, "
        f"d.name AS doc, d.doc_type, d.is_template, d.effective_date FROM claims c JOIN documents d ON d.id=c.doc_id "
        f"WHERE c.control IN ({ph}) ORDER BY c.authority DESC, c.id", q.controls)
    users = store.q(
        f"SELECT * FROM user_statements WHERE id NOT IN (SELECT supersedes FROM user_statements WHERE supersedes IS NOT NULL) "
        f"AND (control IN ({ph}) OR qids LIKE ?) ORDER BY created_at", [*q.controls, f'%"{q.qid}"%'])
    ext = store.q(f"SELECT * FROM external_findings WHERE control IN ({ph}) ORDER BY id", q.controls)
    conflicts = open_conflicts_for(store, q.controls)
    return {"claims": claims, "users": users, "external": ext, "conflicts": conflicts}


def _format_bundle(b: dict) -> str:
    parts = ["CLAIMS:"]
    for c in b["claims"]:
        date = c.get("observed_at") or c.get("effective_date") or "undated"
        tmpl = " TEMPLATE" if c.get("is_template") else ""
        parts.append(f"C{c['id']} | auth {c['authority']} {c['doc_type']}{tmpl} | {c['doc']} | {date} | [{c['attribute']}={c['value']}] {c['statement']} || \"{c['excerpt']}\"")
    if not b["claims"]:
        parts.append("(none)")
    parts.append("\nEMPLOYEE STATEMENTS:")
    for u in b["users"]:
        parts.append(f"U{u['id']} | {u['speaker']} ({u['role']}) at {u['created_at']} | [{u['control']}/{u['attribute']}={u['value']}] {u['statement']}")
    if not b["users"]:
        parts.append("(none)")
    parts.append("\nOPEN CONFLICTS:")
    for k in b["conflicts"]:
        parts.append(f"CONFLICT#{k['id']} [{k['control']}/{k['attribute']}] severity {k['severity']}: {k['description']} Claims: {', '.join(k['claim_ids'])}")
    if not b["conflicts"]:
        parts.append("(none)")
    parts.append("\nEXTERNAL FINDINGS:")
    for x in b["external"]:
        parts.append(f"X{x['id']} | {x['kind']} | {x['title']} | {x['url']} | {x.get('published_at') or ''} | {x['snippet'][:300]} {('NOTE: ' + x['note']) if x.get('note') else ''}")
    if not b["external"]:
        parts.append("(none)")
    return "\n".join(parts)


def _compute_status(q: Question, b: dict, slot_assessment: dict, evidence_ids: list[str], answer_value: str) -> tuple[str, float]:
    claim_by_id = {f"C{c['id']}": c for c in b["claims"]}
    used_claims = [claim_by_id[i] for i in evidence_ids if i in claim_by_id]
    used_users = [i for i in evidence_ids if i.startswith("U")]
    non_template = [c for c in used_claims if not c.get("is_template") and c["authority"] >= 2]
    slots = list(q.slots.keys()) or ["exists"]
    filled = sum(1 for s in slots if (slot_assessment.get(s) or {}).get("filled"))
    completeness = filled / len(slots) if slots else 1.0

    if b["conflicts"] and not used_users:
        status = "CONFLICT"
    elif not non_template and not used_users:
        status = "UNKNOWN"
    elif used_users:
        status = "CONFIRMED_BY_USER" if completeness >= 0.99 or answer_value in ("Yes", "No") else "PARTIAL"
    elif completeness >= 0.99 or (answer_value in ("Yes", "No") and completeness >= 0.5):
        status = "VERIFIED"
    else:
        status = "PARTIAL"

    base = 0.0
    if non_template:
        base = max(AUTH_CONF.get(c["authority"], 0.5) for c in non_template)
    if used_users:
        base = max(base, USER_CONF)
    distinct_docs = {c["doc"] for c in non_template}
    if len(distinct_docs) >= 2 or (used_users and non_template):
        base = min(0.98, base + 0.05)
    elif len(distinct_docs) == 1 and not used_users:
        base -= 0.08
    conf = base * max(0.45, completeness) if base else 0.0
    if status == "CONFLICT":
        conf = min(conf, 0.5) if conf else 0.3
    if status == "UNKNOWN":
        conf = 0.0
    if answer_value == "Unknown" and status not in ("CONFLICT", "UNKNOWN"):
        conf = min(conf, 0.45)
        status = "PARTIAL"
    return status, round(conf, 2)


def derive_question(store: Store, q: Question) -> dict:
    b = _evidence_bundle(store, q)
    if not (b["claims"] or b["users"] or b["external"]):
        row = {
            "qid": q.qid, "status": "UNKNOWN", "answer": "Unknown — needs confirmation", "comments": _unknown_comment(q.owner_role),
            "confidence": 0.0, "evidence": [], "open_slots": {s: "no evidence" for s in q.slots},
            "next_question": f"{q.text} (No documentation found — please answer directly.)", "updated_at": now(),
        }
        store.upsert("question_state", "qid", row)
        return row
    system = (SYSTEM.replace("{vendor}", settings.vendor_legal_name).replace("{owner_role}", q.owner_role)
              .replace("{brand_upper}", settings.vendor_brand.upper()).replace("{brand}", settings.vendor_brand))
    user = (
        f"QUESTION {q.qid} ({q.topic}; buyer criticality: {q.criticality or 'informational'}; answer type: {q.answer_type}"
        f"{'; options: ' + ', '.join(q.options) if q.options else ''}):\n{q.text}\n\n"
        f"SLOTS:\n" + "\n".join(f"- {k}: {v}" for k, v in q.slots.items()) + "\n\nEVIDENCE:\n" + _format_bundle(b)
    )
    with prism.step("derive", qid=q.qid, topic=q.topic, criticality=q.criticality or "informational"):
        data = json_call(system, user, model=settings.model_agent, max_tokens=2500)
    slot_assessment = data.get("slot_assessment") or {}
    evidence_ids = [str(i) for i in (data.get("evidence_ids") or [])]
    answer_value = str(data.get("answer_value") or "Unknown")
    status, conf = _compute_status(q, b, slot_assessment, evidence_ids, answer_value)
    open_slots = {s: (slot_assessment.get(s) or {}).get("value") or "unfilled" for s in q.slots if not (slot_assessment.get(s) or {}).get("filled")}
    evidence = _resolve_evidence(b, evidence_ids)
    response = str(data.get("response") or "").strip()
    comments = str(data.get("comments") or "").strip()
    # Citations the model produced that match nothing in the evidence bundle it was given.
    dropped = [i for i in evidence_ids if i not in {e["id"] for e in evidence}]
    reasons: list[str] = []
    if dropped:
        reasons.append(f"dropped {len(dropped)} citation(s) matching no supplied evidence: {', '.join(dropped[:6])}")
    if status == "UNKNOWN" or not evidence:
        if answer_value not in ("Unknown", ""):
            reasons.append(f"model answered {answer_value!r} with no usable evidence; forced to Unknown")
        elif not evidence:
            reasons.append("no evidence resolved; answer withheld")
        response = "Unknown — needs confirmation"
        conf = 0.0
        comments = _unknown_comment(q.owner_role, comments)
    elif status == "CONFLICT" and answer_value not in ("Unknown", ""):
        reasons.append(f"model answered {answer_value!r} while sources are in open conflict; capped at CONFLICT")
    elif status in ("VERIFIED", "CONFIRMED_BY_USER"):
        response = _with_receipts(response, evidence)
    if reasons:
        prism.trace_override(qid=q.qid, model_answer=answer_value, final_status=status,
                             confidence=conf, reasons=reasons, dropped_evidence=dropped)
    row = {
        "qid": q.qid, "status": status, "answer": response, "comments": comments,
        "confidence": conf, "evidence": evidence, "open_slots": open_slots,
        "next_question": (data.get("next_question") or "").strip() if status != "VERIFIED" else "",
        "updated_at": now(),
    }
    store.upsert("question_state", "qid", {**row, "evidence": json.dumps(evidence), "open_slots": json.dumps(open_slots)})
    store.kv_set(f"answer_value:{q.qid}", answer_value)
    return row


def _unknown_comment(owner_role: str, extra: str = "") -> str:
    """The fixed wording for an answer the documents do not cover; the model's nuance (if any) follows it."""
    base = f"Not covered by company documents. Ask: {owner_role}."
    extra = (extra or "").strip()
    return base if not extra or extra.lower().startswith("not covered by company documents") else f"{base} {extra}"


def _with_receipts(response: str, evidence: list[dict], limit: int = 2) -> str:
    """Guarantee the buyer-facing response names its sources in the fixed receipt format (at most `limit`)."""
    from ..agent.grounding import receipt_label

    if not response or re.search(r"\[[^\[\]\n]{3,120}\]|\(confirmed by [^)\n]{2,80}\)", response):
        return response
    labels: list[str] = []
    for e in sorted(evidence, key=lambda e: -(e.get("authority") or 0)):
        if e.get("type") in ("claim", "user") and (e.get("authority") or 0) >= 2:
            lab = receipt_label(e)
            if lab not in labels:
                labels.append(lab)
        if len(labels) >= limit:
            break
    return f"{response.rstrip()} {' '.join(labels)}".strip() if labels else response


def _resolve_evidence(b: dict, ids: list[str]) -> list[dict]:
    out = []
    cmap = {f"C{c['id']}": c for c in b["claims"]}
    umap = {f"U{u['id']}": u for u in b["users"]}
    xmap = {f"X{x['id']}": x for x in b["external"]}
    for i in ids:
        if i in cmap:
            c = cmap[i]
            out.append({"id": i, "type": "template" if c["is_template"] else "claim", "authority": c["authority"], "doc": c["doc"],
                        "doc_type": c["doc_type"], "statement": c["statement"], "excerpt": c["excerpt"], "date": c.get("observed_at") or c.get("effective_date") or ""})
        elif i in umap:
            u = umap[i]
            out.append({"id": i, "type": "user", "authority": 5, "doc": f"{u['speaker']} ({u['role']})", "doc_type": "interview",
                        "statement": u["statement"], "excerpt": "", "date": u["created_at"]})
        elif i in xmap:
            x = xmap[i]
            out.append({"id": i, "type": "external", "authority": 0, "doc": x["title"], "doc_type": x["kind"], "statement": x["snippet"][:300],
                        "excerpt": x["url"], "date": x.get("published_at") or ""})
    return out


def derive_all(store: Store, qids: list[str] | None = None, workers: int = 6, progress=None) -> dict:
    cat = get_catalog()
    qs = [cat.questions[q] for q in qids] if qids else cat.ordered()
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(derive_question, store, q): q.qid for q in qs}
        for fut in as_completed(futs):
            try:
                row = fut.result()
                counts[row["status"]] = counts.get(row["status"], 0) + 1
                if progress:
                    progress("derived", {"qid": futs[fut], "status": row["status"]})
            except Exception as e:  # noqa: BLE001
                store.log("derive_error", f"{futs[fut]}: {e}")
                if progress:
                    progress("error", {"qid": futs[fut], "error": str(e)})
    return counts


def question_states(store: Store) -> list[dict]:
    from .cache import memo

    return memo(store, "question_states", lambda: _question_states(store))


def _question_states(store: Store) -> list[dict]:
    cat = get_catalog()
    states = {r["qid"]: r for r in store.q("SELECT * FROM question_state")}
    values = store.kv_prefix("answer_value:")
    out = []
    for q in cat.ordered():
        s = states.get(q.qid) or {"status": "UNKNOWN", "answer": "", "comments": "", "confidence": 0.0, "evidence": "[]", "open_slots": "{}", "next_question": ""}
        out.append({
            **q.to_row(), "status": s["status"], "answer": s["answer"], "comments": s["comments"], "confidence": s["confidence"],
            "evidence": loads(s["evidence"], []), "open_slots": loads(s["open_slots"], {}), "next_question": s["next_question"],
            "answer_value": values.get(f"answer_value:{q.qid}", "Unknown"), "updated_at": s.get("updated_at"),
        })
    return out
