"""Conflict engine: LLM judge over groups of related claims, using the authority hierarchy."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..config import settings
from ..llm import json_call
from ..observability import prism
from ..store.db import Store, loads, now

# Related controls are judged together so cross-document contradictions surface.
GROUPS: dict[str, list[str]] = {
    "access": ["production_access", "access_review", "offboarding", "least_privilege", "identity_access_management", "rbac", "asset_inventory", "remote_access", "change_management"],
    "authentication": ["mfa", "password_policy", "authenticator_standards", "tls_certificate", "web_application", "sso_support", "cryptography_keys"],
    "resilience": ["backup_recovery", "bcdr_policy", "data_hosting", "data_location", "security_logging"],
    "vulnerability": ["vulnerability_scanning", "patch_remediation_sla", "penetration_testing", "pentest_remediation", "secure_development", "secure_coding", "vulnerability_disclosure"],
    "people": ["security_training", "role_based_training", "background_checks", "offboarding", "roles_responsibilities", "subcontractors"],
    "governance": ["governance_program", "security_policies", "public_security_policy", "oversight_escalation", "company_profile", "risk_assessment", "asset_prioritization", "physical_security", "ai_usage"],
    "incident": ["incident_response", "ir_testing", "breach_notification", "security_incident_history", "outsourced_security", "endpoint_protection", "wireless_security", "network_architecture"],
    "data": ["privacy_program", "sensitive_data_handling", "data_retention_disposal", "privacy_policy", "encryption_at_rest", "encryption_in_transit", "data_flow_diagrams", "third_party_risk", "supply_chain", "contract_security_clauses", "vendor_list"],
}

SYSTEM = """You audit the consistency of a company's security documentation for a vendor risk review.

You receive CLAIMS about related controls. Each has: id, source document, document type, authority
(4 record/observed > 3 audited attestation > 2 policy/contract > 1 template), date, and a one-sentence statement.

Find CONFLICTS — cases where sources assert incompatible facts about the same thing:
- who holds access / how many admins / which roles (policy vs access-review record)
- whether a control exists or is performed (e.g. "no automated scanning" vs "periodic vulnerability assessments")
- cadences, numbers, RTO/RPO, retention periods, SLAs
- password rotation / MFA scope
- entity or leadership names (e.g. a report naming a different CEO or company than the policies)
- audit periods or dates that cannot both be true
- practice deviating from policy: a record showing something the policy forbids or promises otherwise
- a TEMPLATE contradicting the real policy (severity low; say it is a template)
- direct cross-document inferences (e.g. a person's laptop was retired on date X "per offboarding checklist" yet the same person still holds admin access on a review dated after X)

Do NOT flag: wording differences, one source merely being more detailed, compatible scope differences, or a policy
admitting a gap that no other source contradicts (that is an admission, not a conflict).
Do NOT flag the company being called by different names: {aliases} all refer to the SAME organisation (brand vs legal
entity vs report short-name). Naming is only a conflict when it points at a genuinely different fact — a different named
individual in the same role (e.g. two different CEOs), a different incorporation date/jurisdiction, or a report whose
scope/period cannot belong to this company. Also: tools used BY a third-party tester (e.g. Burp Suite in a pentest
report) describe the tester's method, not the company's own scanning practice — do not read them as the company scanning.
Prefer ONE conflict per underlying disagreement; do not repeat the same root cause under several controls.

For each conflict return: attribute (snake_case), claim_ids (2 or more ids), description (max 2 sentences naming the
sources and dates), question_to_ask (ONE precise question to the employee that would resolve it), severity
(high|medium|low), controls (control ids touched, from the claims).
Return ONLY JSON: {"conflicts": [...]}"""


def _aliases() -> str:
    brand, legal = settings.vendor_brand, settings.vendor_legal_name
    names = [f'"{legal}"', f'"{brand}"', f'"{brand} AI"', f'"{brand.upper()} Inc."', f'"{legal.split(" ")[0]}"']
    return ", ".join(dict.fromkeys(names))


def _claims_for(store: Store, controls: list[str]) -> list[dict]:
    ph = ",".join("?" for _ in controls)
    return store.q(
        f"SELECT c.id, c.control, c.attribute, c.value, c.statement, c.authority, c.modality, c.observed_at, "
        f"d.name AS doc, d.doc_type, d.is_template, d.effective_date FROM claims c JOIN documents d ON d.id=c.doc_id "
        f"WHERE c.control IN ({ph}) ORDER BY c.authority DESC, c.id",
        controls,
    )


def _format(claims: list[dict]) -> str:
    lines = []
    for c in claims:
        date = c.get("observed_at") or c.get("effective_date") or "undated"
        tmpl = " TEMPLATE" if c.get("is_template") else ""
        lines.append(f"C{c['id']} | auth {c['authority']} {c['doc_type']}{tmpl} | {c['doc']} | {date} | [{c['control']}/{c['attribute']}] {c['statement']}")
    return "\n".join(lines)


def judge_group(store: Store, name: str, controls: list[str]) -> list[dict]:
    claims = _claims_for(store, controls)
    if len(claims) < 2:
        return []
    user = f"GROUP: {name}\n\nCLAIMS ({len(claims)}):\n{_format(claims)}"
    system = SYSTEM.replace("{aliases}", _aliases())
    with prism.step("conflict_judge", group=name, claims=len(claims)):
        data = json_call(system, user, model=settings.model_agent, max_tokens=4000)
    found = data.get("conflicts", []) if isinstance(data, dict) else []
    valid_ids = {f"C{c['id']}" for c in claims}
    out = []
    for f in found:
        ids = [i for i in f.get("claim_ids", []) if str(i) in valid_ids]
        if len(ids) < 2:
            continue
        ctrls = [c for c in f.get("controls", []) if c in controls] or [
            next(c["control"] for c in claims if f"C{c['id']}" == ids[0])
        ]
        out.append({
            "control": ctrls[0], "controls": ctrls, "attribute": str(f.get("attribute", ""))[:60],
            "claim_ids": ids, "description": str(f.get("description", ""))[:600],
            "question_to_ask": str(f.get("question_to_ask", ""))[:400], "severity": f.get("severity", "medium"),
        })
    return out


def detect_conflicts(store: Store, groups: dict[str, list[str]] | None = None, workers: int = 4) -> int:
    """Re-run detection. Resolved conflicts persist and suppress re-creation of the same (control, attribute)."""
    groups = groups or GROUPS
    resolved = {(r["control"], r["attribute"]) for r in store.q("SELECT control, attribute FROM conflicts WHERE status='resolved'")}
    # Drop only open conflicts belonging to the groups being re-judged
    ctrls = sorted({c for g in groups.values() for c in g})
    ph = ",".join("?" for _ in ctrls)
    store.execute(f"DELETE FROM conflicts WHERE status='open' AND control IN ({ph})", ctrls)
    n = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(judge_group, store, g, cs): g for g, cs in groups.items()}
        for fut in as_completed(futs):
            try:
                conflicts = fut.result()
            except Exception as e:  # noqa: BLE001
                store.log("conflict_error", f"{futs[fut]}: {e}")
                continue
            for c in conflicts:
                if (c["control"], c["attribute"]) in resolved:
                    continue
                store.insert("conflicts", {
                    "control": c["control"], "attribute": c["attribute"], "claim_ids": json.dumps(c["claim_ids"]),
                    "description": c["description"], "question_to_ask": c["question_to_ask"], "status": "open",
                    "resolution": json.dumps({"severity": c["severity"], "controls": c["controls"]}),
                    "created_at": now(),
                })
                n += 1
    store.log("conflicts_detected", {"count": n})
    return n


def open_conflicts_for(store: Store, controls: list[str]) -> list[dict]:
    rows = store.q("SELECT * FROM conflicts WHERE status='open'")
    out = []
    for r in rows:
        meta = loads(r.get("resolution"), {}) or {}
        touched = set(meta.get("controls", [])) | {r["control"]}
        if touched & set(controls):
            r["severity"] = meta.get("severity", "medium")
            r["controls"] = sorted(touched)
            r["claim_ids"] = loads(r["claim_ids"], [])
            out.append(r)
    return out


def groups_for_control(control: str) -> dict[str, list[str]]:
    return {g: cs for g, cs in GROUPS.items() if control in cs}
