"""Markdown gap / fix-first report for leadership."""

from __future__ import annotations

from datetime import date

from ..catalog.loader import get_catalog
from ..config import settings
from ..engine.derive import question_states
from ..engine.scorer import score
from ..store.db import Store, loads


def report_data(store: Store) -> dict:
    """Structured report for the printable HTML page (styled by the frontend's single stylesheet)."""
    from ..engine.planner import open_items

    sc = store.kv_get("last_score") or score(store)
    conflicts = []
    for k in store.q("SELECT * FROM conflicts ORDER BY status DESC, id"):
        meta = loads(k["resolution"], {}) or {}
        conflicts.append({"id": k["id"], "status": k["status"], "severity": meta.get("severity", "medium"), "description": k["description"],
                          "question_to_ask": k["question_to_ask"], "resolved_by": k["resolved_by"], "resolution_text": meta.get("text")})
    return {
        "vendor": {"legal_name": settings.vendor_legal_name, "brand": settings.vendor_brand, "domain": settings.vendor_domain},
        "generated_at": date.today().isoformat(), "score": sc, "states": question_states(store), "conflicts": conflicts,
        "reputational": store.kv_get("reputational"), "open_items": open_items(store)[:20],
    }


def build_report(store: Store) -> str:
    sc = store.kv_get("last_score") or score(store)
    states = question_states(store)
    cat = get_catalog()
    conflicts = store.q("SELECT * FROM conflicts ORDER BY status DESC, id")
    rep = store.kv_get("reputational") or {}
    L: list[str] = []
    L.append(f"# Security review pre-flight — {settings.vendor_legal_name} ({settings.vendor_brand})")
    L.append(f"_Generated {date.today().isoformat()} by the AI Security Analyst. Every statement below is traceable to a document, a record, an employee, or a public source; nothing is inferred._\n")
    L.append("## Buyer's-eye summary")
    L.append(f"- Vendor criticality (buyer table): **{sc['vendor_criticality']}** for {sc['vendor_type']} / {sc['access']}")
    L.append(f"- Predicted inherent risk points: **{sc['inherent_points']:.0f} / {sc['max_inherent_points']:.0f}** → predicted rating **{sc['predicted_rating']}**")
    L.append(f"- Predicted escalations: **{len(sc['escalations'])}** ({sum(1 for e in sc['escalations'] if e['kind']=='question')} questions, {sum(1 for e in sc['escalations'] if e['kind']=='document')} documents)")
    c = sc["counts"]
    L.append(f"- Questionnaire status: {c['VERIFIED']} verified from documents · {c['CONFIRMED_BY_USER']} confirmed by employees · {c['PARTIAL']} partial · {c['CONFLICT']} in conflict · {c['UNKNOWN']} unknown\n")
    L.append("## Fix first (points removed per hour of effort)")
    for f in sc["fix_first"][:10]:
        L.append(f"- **{f['control']}** — {f['action']} _(~{f['hours']}h, {f['points']:.0f} pts, Q{', Q'.join(f['qids'])})_")
    L.append("\n## Predicted escalations")
    for e in sc["escalations"]:
        L.append(f"- {'Q' + e['qid'] + ' — ' if e.get('qid') else ''}{e['text']}: {e['reason']}")
    L.append("\n## Requested documents")
    for d in sc["documents"]:
        L.append(f"- {d['document']}: **{d['status'].replace('_', ' ')}** — {d['note']}")
    L.append("\n## Conflicts between sources")
    for k in conflicts:
        meta = loads(k["resolution"], {}) or {}
        L.append(f"- [{k['status'].upper()}] ({meta.get('severity', 'medium')}) {k['description']}"
                 + (f" **Resolution:** {meta.get('text')} — {k['resolved_by']}" if k["status"] == "resolved" else f" **Ask:** {k['question_to_ask']}"))
    if rep:
        L.append("\n## Outside-in (public web) view")
        for k_, v in (rep.get("fields") or {}).items():
            L.append(f"- {k_.replace('_', ' ')}: {v}")
        for d in rep.get("discrepancies", []):
            L.append(f"- ⚠ Discrepancy: {d.get('description')} → ask: {d.get('question_to_ask')}")
    L.append("\n## Open questions for the team")
    from ..engine.planner import open_items
    for it in open_items(store)[:15]:
        L.append(f"- Q{it['qid']} ({it['owner_role']}, priority {it['priority']}): {it['question']} — _{it['why']}_")
    L.append("\n## Answers by question")
    topic = None
    for s in states:
        if s["topic"] != topic:
            topic = s["topic"]
            L.append(f"\n### {topic}")
        L.append(f"- **Q{s['qid']}** {s['text']}\n  - Status: {s['status']} (confidence {s['confidence']}) · Answer: {s['answer']}\n  - {s['comments']}")
        for ev in s["evidence"][:3]:
            L.append(f"  - evidence: {ev['doc']} — \"{(ev.get('excerpt') or ev.get('statement') or '')[:160]}\"")
    return "\n".join(L)
