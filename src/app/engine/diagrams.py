"""Live diagram data for each workflow: what it does, in what order, what it produced, and how each step deduces its result.

Nodes are rendered by the frontend as a flow (left → right, with a loop-back for guided chat workflows).
Every `value` comes from the store, never from the model.
"""

from __future__ import annotations

from ..store.db import Store, loads
from .derive import question_states

HOW = {
    "documents": "Every file in datasets/ (and uploads) is parsed — docx paragraphs and tables, xlsx rows, pdf text, images via a vision pass. Each document is tagged with an authority tier from its folder and name (record > attestation > policy > template) and flagged as a template when it still carries placeholders.",
    "chunks": "Documents are split on headings into ~5,000-character sections so every extracted claim can point back to a specific passage.",
    "claims": "An extraction model reads each section and writes atomic, checkable statements (control, attribute, value, verbatim excerpt, date). Results are cached by section hash, so re-runs are free.",
    "vectors": "Each claim and section is embedded locally (fastembed, 384-d) and stored in pgvector. Retrieval blends vector similarity (0.6) with BM25 (0.4).",
    "conflicts": "Claims are grouped into 8 related control areas and judged for contradictions using the authority hierarchy: a record beats an attestation, which beats a policy; templates count for nothing. Brand-vs-legal-entity naming is excluded by rule.",
    "answers": "For each of the 66 questions the model fills the question's slots from the evidence; status and confidence are then computed in code — no evidence → Unknown, an open conflict caps confidence at 0.5, template-only evidence scores zero.",
    "score": "The buyer's own workbook tables are applied to the answers: vendor criticality from the access matrix, inherent/residual points per question, escalation rules per assessor instruction.",
    "open_items": "Questions that are Unknown, Partial or in Conflict, ranked by inherent risk points × buyer criticality × status weight.",
    "ask": "The analyst searches first, then asks one precise question that fills the most valuable empty slot, explaining why it matters.",
    "statements": "Each answer is recorded under the speaker's name and timestamp; a later statement on the same attribute supersedes the earlier one instead of overwriting it.",
    "rederive": "Only the questions touched by the new statement are re-derived and re-scored, so the board and the buyer's rating move immediately.",
    "open_conflicts": "Contradictions the judge found that no employee statement has resolved yet.",
    "sides": "Both claims are shown with their source, tier and date, plus the single question that would settle them.",
    "resolved": "A resolution is stored with who said it and when; the conflict stays in the record as resolved, never deleted.",
    "probe": "A direct TLS handshake and HTTP header check of the corporate domain, plus a look for security.txt. Stored as an observed record (tier 4).",
    "entity": "Public registries and company profiles: legal entity, jurisdiction, founders, subsidiaries.",
    "public_page": "The corporate site is mapped for security, trust, privacy and disclosure pages; found pages are extracted.",
    "attestation": "Public claims of SOC 2 / ISO certifications, compared with the attestation documents actually held.",
    "breach": "News search for breaches or incidents naming the company. No hit is recorded as 'no public report found', never as 'No'.",
    "fourth_party": "Recent security news about each subprocessor named in the documents (AWS, Google Workspace, GitHub…).",
    "reputational": "A model compiles the buyer's Reputational Assessment fields from the findings and flags every place the public record disagrees with the documents; discrepancies become open conflicts.",
    "criticality": "Vendor type × access level looked up in the buyer's Vendor Criticality Table.",
    "points": "Sum of the buyer's inherent-risk points over every scored question whose answer is No, Partial or Unknown.",
    "escalations": "Questions whose buyer rule says 'escalate' when the answer is No, plus requested documents that are missing or template-only.",
    "exceptions": "For each predicted escalation, a draft entry for the buyer's Approved Exceptions register — justification, mitigating controls and remediation plan — written only from evidenced facts.",
    "fixes": "Gaps ranked by inherent points removed per hour of effort, from a small catalogue of known remediations.",
    "guard": "The exporter refuses to write any response without provenance and substitutes 'Unknown — needs confirmation'.",
    "workbook": "The customer's own .xlsx is filled: responses, comments, evidence, Vendor Profile checkboxes, Reputational Assessment, plus Analyst Summary and Exception Requests sheets.",
    "report": "A printable HTML report (and Markdown) built from the same data.",
}


def _node(id_, label, value=None, unit="", ok=True):
    return {"id": id_, "label": label, "value": value, "unit": unit, "how": HOW.get(id_, ""), "done": value not in (None, 0, "", "—") and ok}


def diagrams(store: Store) -> dict[str, dict]:
    c = store.counts()
    states = question_states(store)
    st = {}
    for q in states:
        st[q["status"]] = st.get(q["status"], 0) + 1
    kv = store.kv_prefix("last_") | store.kv_prefix("reputational") | store.kv_prefix("exceptions") | store.kv_prefix("workflow:export")
    sc = kv.get("last_score") or {}
    conflicts = store.q("SELECT status FROM conflicts")
    n_open = sum(1 for k in conflicts if k["status"] == "open")
    n_res = sum(1 for k in conflicts if k["status"] == "resolved")
    ext = {}
    for r in store.q("SELECT kind, count(*) AS n FROM external_findings GROUP BY kind"):
        ext[r["kind"]] = r["n"]
    rep = kv.get("reputational") or {}
    exc = kv.get("exceptions") or []
    last_export = kv.get("workflow:export:last") or {}
    open_items = st.get("UNKNOWN", 0) + st.get("PARTIAL", 0) + st.get("CONFLICT", 0)
    with_evidence = sum(1 for q in states if q["evidence"])
    status_text = " · ".join(f"{k.replace('_BY_USER', '').lower()} {v}" for k, v in sorted(st.items(), key=lambda kv: -kv[1])) if st else None
    rating = f"{sc.get('predicted_rating')} · {int(sc.get('inherent_points', 0))}/{int(sc.get('max_inherent_points', 0))} pts" if sc else None

    return {
        "ingest": {"kind": "linear", "nodes": [
            _node("documents", "Documents", c["documents"], "files"), _node("chunks", "Sections", c["chunks"]),
            _node("claims", "Claims", c["claims"]), _node("vectors", "Vectors", c["embeddings"]),
            _node("conflicts", "Contradictions", n_open + n_res, f"{n_open} open" if n_open + n_res else ""),
            _node("answers", "Answers", len(states) if st else 0, status_text or ""), _node("score", "Buyer rating", sc.get("predicted_rating"), rating or "")],
            "outcome": f"{c['claims']} claims from {c['documents']} documents → {n_open + n_res} contradictions → {len(states)} answers → {sc.get('predicted_rating', '—')}" if c["claims"] else "Not run yet"},
        "interview": {"kind": "loop", "nodes": [
            _node("open_items", "Open items", open_items, "questions"), _node("ask", "Ask one question", None),
            _node("statements", "Statements recorded", c["user_statements"]), _node("rederive", "Re-derived", st.get("CONFIRMED_BY_USER", 0), "confirmed by employees")],
            "outcome": f"{open_items} open · {c['user_statements']} statements recorded · {st.get('CONFIRMED_BY_USER', 0)} questions confirmed by employees"},
        "conflicts": {"kind": "loop", "nodes": [
            _node("open_conflicts", "Open contradictions", n_open), _node("sides", "Show both sides", None),
            _node("resolved", "Resolved", n_res), _node("rederive", "Re-derived", st.get("CONFLICT", 0), "still in conflict")],
            "outcome": f"{n_open} open · {n_res} resolved · {st.get('CONFLICT', 0)} questions still blocked"},
        "research": {"kind": "fan", "nodes": [
            _node("probe", "Live probe", ext.get("probe") or (1 if store.one("SELECT id FROM documents WHERE path LIKE ?", ("probe://%",)) else 0)),
            _node("entity", "Entity facts", ext.get("entity", 0)), _node("public_page", "Own web pages", ext.get("public_page", 0)),
            _node("attestation", "Attestation claims", ext.get("attestation", 0)), _node("breach", "Breach news", ext.get("breach", 0)),
            _node("fourth_party", "Subprocessors", ext.get("fourth_party", 0)),
            _node("reputational", "Reputational view", len(rep.get("discrepancies", [])) if rep else None, "discrepancies" if rep else "")],
            "outcome": f"{c['external_findings']} public findings · {len(rep.get('discrepancies', []))} discrepancies with our documents" if rep else "Not run yet"},
        "buyer_review": {"kind": "linear", "nodes": [
            _node("answers", "Answers", len(states) if st else 0), _node("criticality", "Criticality", sc.get("vendor_criticality")),
            _node("points", "Inherent points", int(sc.get("inherent_points", 0)) if sc else None, f"of {int(sc.get('max_inherent_points', 0))}" if sc else ""),
            _node("escalations", "Escalations", len(sc.get("escalations", [])) if sc else None), _node("exceptions", "Exception drafts", len(exc)),
            _node("fixes", "Fix-first", len(sc.get("fix_first", [])) if sc else None)],
            "outcome": f"{sc.get('predicted_rating', '—')} · {len(sc.get('escalations', []))} escalations · {len(exc)} exception drafts" if sc else "Not run yet"},
        "export": {"kind": "linear", "nodes": [
            _node("guard", "Provenance guard", with_evidence, f"of {len(states)} with receipts"), _node("workbook", "Workbook", last_export.get("workbook")),
            _node("report", "Report", "ready" if last_export else None)],
            "outcome": f"Last export: {last_export.get('workbook')}" if last_export else "Not exported yet"},
    }
