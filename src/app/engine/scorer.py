"""Buyer's-eye scorer: apply the customer's own workbook logic to our derived answers.

- vendor criticality from the Vendor Criticality Table
- inherent / residual risk points from InherentRiskScore / ResidualRiskScore
- predicted escalations from the per-question assessor rules + missing requested documents
- exception drafts (LLM) in the Approved Exceptions format
- fix-first list ranked by points removed per hour
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

from ..catalog.loader import get_catalog
from ..config import settings
from ..llm import json_call
from ..observability import prism
from ..store.db import Store
from .derive import question_states

# requested document → (controls that evidence it, name keywords that count as the document itself)
REQUESTED_DOC_MAP = {
    "Third-Party Risk Management Policy": (["third_party_risk"], ["vendor_risk", "third-party", "third_party", "tprm"]),
    "Data Retention Schedule": (["data_retention_disposal"], ["retention", "data_classification"]),
    "Secure Disposal Procedures": (["data_retention_disposal", "asset_inventory"], ["disposal", "asset_management"]),
    "BC/DR Policy AND/OR Plan": (["bcdr_policy", "backup_recovery"], ["business_continuity", "bcp", "disaster"]),
    "Authorized Personnel Access List": (["authorized_personnel", "access_review"], ["access_review"]),
    "Network Architecture Diagram": (["network_architecture"], ["network", "diagram"]),
    "EndPoint Protections Description/Document": (["endpoint_protection"], ["asset_management", "endpoint"]),
    "COI with Cyber Liability Insurance": (["company_profile"], ["insurance", "coi", "certificate of insurance"]),
}


def _fixes() -> dict:
    p = settings.catalog_dir / "fixes.yaml"
    return (yaml.safe_load(p.read_text()) or {}).get("fixes", {}) if p.exists() else {}


def vendor_criticality(vendor_type: str, access: str) -> str:
    for row in get_catalog().criticality_table:
        if row["vendor_type"].lower() == vendor_type.lower() and row["access"].lower() == access.lower():
            return row["criticality"]
    return "Not Defined"


def document_availability(store: Store) -> list[dict]:
    docs = store.q("SELECT name, doc_type, is_template FROM documents")
    per_control = {r["control"]: r["n"] for r in store.q("SELECT c.control, count(*) AS n FROM claims c JOIN documents d ON d.id=c.doc_id WHERE d.is_template=0 GROUP BY c.control")}
    out = []
    for req, (controls, keys) in REQUESTED_DOC_MAP.items():
        direct = [d for d in docs if any(k in d["name"].lower().replace(" ", "_") or k in d["name"].lower() for k in keys)]
        real = [d for d in direct if not d["is_template"]]
        templates = [d for d in direct if d["is_template"]]
        n_claims = sum(per_control.get(c, 0) for c in controls)
        if real:
            status, note = "available", ", ".join(d["name"] for d in real[:3])
        elif templates:
            status, note = "template_only", "Only an unfilled template found: " + ", ".join(d["name"] for d in templates)
        elif n_claims:
            status, note = "partial", f"Covered inside other documents ({n_claims} related claims) but no standalone document"
        else:
            status, note = "missing", "No document found in company data"
        out.append({"document": req, "status": status, "note": note})
    return out


def score(store: Store, vendor_type: str = "Technology", access: str = "Network&Data") -> dict:
    from .cache import memo

    return memo(store, f"score:{vendor_type}:{access}", lambda: _score(store, vendor_type, access))


def _score(store: Store, vendor_type: str, access: str) -> dict:
    states = question_states(store)
    crit = vendor_criticality(vendor_type, access)
    at_risk, escalations, total_inh, total_res, max_inh = [], [], 0.0, 0.0, 0.0
    for s in states:
        if s["informational"] or not s["inherent_pts"]:
            continue
        max_inh += s["inherent_pts"]
        av = s["answer_value"]
        risky = av in ("No", "Unknown") or s["status"] in ("UNKNOWN", "CONFLICT")
        if av == "Partial":
            risky = True
        if risky:
            total_inh += s["inherent_pts"]
            total_res += s["residual_pts"]
            at_risk.append({"qid": s["qid"], "text": s["text"], "answer_value": av, "status": s["status"], "inherent_pts": s["inherent_pts"],
                            "residual_pts": s["residual_pts"], "criticality": s["criticality"], "controls": s["controls"]})
            if s["rule_if_no"] and "escalat" in s["rule_if_no"].lower():
                escalations.append({"qid": s["qid"], "text": s["text"], "reason": f"Answer is {av} ({s['status']}); buyer rule: escalate", "rule": s["rule_if_no"][:400], "kind": "question"})
    docs = document_availability(store)
    for d in docs:
        if d["status"] in ("missing", "template_only"):
            escalations.append({"qid": None, "text": d["document"], "reason": f"Requested document {d['status'].replace('_', ' ')}: {d['note']}", "rule": "Justification required in Vendor Profile column E if documentation cannot be provided", "kind": "document"})
    ratio = total_inh / max_inh if max_inh else 0
    rating = "Low" if ratio < 0.15 else "Moderate" if ratio < 0.35 else "High" if ratio < 0.6 else "Critical"
    fixes = _fixes()
    fix_list = []
    seen = set()
    for r in at_risk:
        for c in r["controls"]:
            if c in fixes and c not in seen:
                seen.add(c)
                f = fixes[c]
                pts = sum(x["inherent_pts"] for x in at_risk if c in x["controls"])
                fix_list.append({"control": c, "action": f["action"], "hours": f["hours"], "points": pts, "qids": [x["qid"] for x in at_risk if c in x["controls"]],
                                 "points_per_hour": round(pts / max(f["hours"], 0.25), 1)})
    for d in docs:
        if d["document"] == "COI with Cyber Liability Insurance" and d["status"] == "missing" and "company_profile" not in seen:
            f = fixes.get("company_profile")
            if f:
                fix_list.append({"control": "company_profile", "action": f["action"], "hours": f["hours"], "points": 0, "qids": [], "points_per_hour": 0})
    fix_list.sort(key=lambda x: (-x["points_per_hour"], -x["points"]))
    result = {
        "vendor_type": vendor_type, "access": access, "vendor_criticality": crit,
        "inherent_points": total_inh, "residual_points": total_res, "max_inherent_points": max_inh,
        "risk_ratio": round(ratio, 3), "predicted_rating": rating,
        "at_risk": sorted(at_risk, key=lambda x: -x["inherent_pts"]), "escalations": escalations,
        "documents": docs, "fix_first": fix_list,
        "counts": {k: sum(1 for s in states if s["status"] == k) for k in ("VERIFIED", "CONFIRMED_BY_USER", "PARTIAL", "CONFLICT", "UNKNOWN")},
    }
    store.kv_set("last_score", result, bump=False)
    return result


EXC_SYSTEM = """You draft vendor-side exception requests for a buyer's third-party risk review. Given a questionnaire
question the vendor must answer "No"/"Partial"/"Unknown" to, the buyer's assessor rule, the vendor's derived
answer and comments (all evidence-based), write the entry for the buyer's 'Approved Exceptions' register:
- justification: why the control is not (fully) in place, factual, no spin, 2-3 sentences, only using facts given
- mitigating_controls: compensating controls that ARE evidenced in the given material (or "None evidenced")
- remediation_plan: concrete next step; if a timeline is not evidenced write "Timeline to be confirmed by <role>"
- evidence_to_attach: which documents/records support the above
Never invent controls, dates, or tools not present in the input. Return ONLY JSON with those four keys."""


def draft_exceptions(store: Store, max_items: int = 8) -> list[dict]:
    sc = store.kv_get("last_score") or score(store)
    states = {s["qid"]: s for s in question_states(store)}
    todo = [e for e in sc["escalations"] if e["kind"] == "question"][:max_items]

    def one(e):
        s = states[e["qid"]]
        user = (f"QUESTION {s['qid']}: {s['text']}\nBUYER RULE: {s['rule_if_no']}\nDERIVED ANSWER: {s['answer']}\nCOMMENTS: {s['comments']}\n"
                f"OWNER ROLE: {s['owner_role']}\nEVIDENCE USED:\n" + "\n".join(f"- [{ev['doc']}] {ev['statement']}" for ev in s["evidence"]))
        with prism.step("exception_draft", qid=s["qid"]):
            d = json_call(EXC_SYSTEM, user, model=settings.model_agent, max_tokens=900)
        return {"qid": s["qid"], "text": s["text"], **{k: d.get(k, "") for k in ("justification", "mitigating_controls", "remediation_plan", "evidence_to_attach")}}

    out = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for fut in as_completed([ex.submit(one, e) for e in todo]):
            try:
                out.append(fut.result())
            except Exception as ex_:  # noqa: BLE001
                store.log("exception_draft_error", str(ex_))
    out.sort(key=lambda x: float(x["qid"]))
    store.kv_set("exceptions", out)
    return out
