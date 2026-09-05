"""LLM claim extraction: chunk → atomic, sourced claims tagged with a control id."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..catalog.loader import get_catalog
from ..config import settings
from ..llm import json_call

CACHE = settings.data_dir / "cache" / "claims"

MODALITIES = {
    "policy": "policy_states",
    "contract": "contract_requires",
    "soc2_report": "attestation_states",
    "pentest_report": "record_shows",
    "record": "record_shows",
    "chat": "record_shows",
    "template": "template_text",
    "diagram": "document_describes",
    "plan": "document_describes",
    "document": "document_describes",
}

SYSTEM = """You extract atomic security-control CLAIMS from company documents for a vendor security questionnaire.

A claim is one self-contained fact the text asserts about how the company operates, phrased so it can be checked
against other documents later. Extract BOTH positive controls ("MFA is enforced on AWS console") AND admissions
of gaps ("no restore test has been performed yet", "automated scanning is not in place", "VPN rollout in progress").
Admissions, exceptions, named people/roles/systems, dates, numbers, cadences, and SLAs are the most valuable.

Rules:
- Only what the text says. Never infer or generalise. Never invent.
- Tag each claim with exactly one control id from the list. Use "other" only if nothing fits.
- attribute: short snake_case name for the specific aspect (e.g. mfa_scope, backup_frequency, standing_prod_access, restore_tested).
- value: short normalised value (yes/no, a number, a cadence, a role name, a list) — never a full sentence.
- statement: ONE sentence that stands alone without the document (name the subject; e.g. "Standing production access is limited to the CTO.").
- excerpt: verbatim supporting text from the chunk, max 220 characters.
- observed_at: a date string ONLY if the claim itself is dated in the text (report date, review date, login date); else "".
- For records (tables of users, assets, findings): extract per-row facts that matter for security (e.g. each admin user, each retired asset, each finding with severity). Skip rows that carry no security meaning.
- If the document is a TEMPLATE (placeholders like <Company Name>, "instructions for use"), still extract, but the caller marks it as template.
- Skip boilerplate (purpose statements, policy acknowledgement clauses, generic legal text) unless it carries a concrete control.
- Max 25 claims per chunk. Prefer specificity over volume.

Return ONLY JSON: {"claims": [{"control": "...", "attribute": "...", "value": "...", "statement": "...", "excerpt": "...", "observed_at": ""}]}"""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:24]


def extract_claims(chunk_text: str, doc_meta: dict) -> list[dict]:
    """Return list of claim dicts (control, attribute, value, statement, excerpt, observed_at)."""
    cat = get_catalog()
    key = _sha(chunk_text + json.dumps(doc_meta, sort_keys=True) + "v1")
    CACHE.mkdir(parents=True, exist_ok=True)
    cpath: Path = CACHE / f"{key}.json"
    if cpath.exists():
        return json.loads(cpath.read_text())

    user = (
        f"DOCUMENT: {doc_meta.get('name')}\nTYPE: {doc_meta.get('doc_type')} | authority: {doc_meta.get('authority_label')}"
        f" | template: {doc_meta.get('is_template')} | entity: {doc_meta.get('entity') or 'unknown'}"
        f" | document date: {doc_meta.get('effective_date') or 'unknown'}\n"
        f"SECTION: {doc_meta.get('heading') or ''}\n\nCONTROL IDS:\n{cat.control_description_block()}\n- other\n\n"
        f"TEXT:\n\"\"\"\n{chunk_text}\n\"\"\""
    )
    data = json_call(SYSTEM, user, model=settings.model_fast, max_tokens=6000)
    claims = data.get("claims", []) if isinstance(data, dict) else data
    valid = set(cat.control_ids()) | {"other"}
    out = []
    for c in claims or []:
        if not isinstance(c, dict) or not c.get("statement"):
            continue
        ctrl = str(c.get("control", "other")).strip()
        out.append({
            "control": ctrl if ctrl in valid else "other",
            "attribute": str(c.get("attribute", "")).strip()[:80],
            "value": str(c.get("value", "")).strip()[:200],
            "statement": str(c.get("statement", "")).strip()[:500],
            "excerpt": str(c.get("excerpt", "")).strip()[:300],
            "observed_at": str(c.get("observed_at", "") or "").strip()[:40],
        })
    cpath.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


SUMMARY_SYSTEM = "Summarise this company document for a security assessor in 2 sentences: what it is, who issued it, what it covers, and any notable admission or oddity (e.g. it is an unfilled template, or names a different company/CEO). Plain text only."


def summarise(text: str, name: str) -> str:
    try:
        from ..llm import chat
        msg = chat([{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": f"FILE: {name}\n\n{text[:6000]}"}],
                   model=settings.model_fast, max_tokens=200)
        return (msg.content or "").strip()
    except Exception as e:  # noqa: BLE001
        return f"(summary unavailable: {e})"
