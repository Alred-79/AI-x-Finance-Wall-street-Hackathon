"""Outside-in research orchestrator: what will the buyer's analyst find about us on the public web?

Modes: entity_facts, breach_history, public_pages, attestations, fourth_party, live_probe, summary (all → run_all).
Results become external_findings; the live probe becomes an authority-4 record claim; a reputational summary is
stored in kv['reputational'] together with questions the employee should be asked.
"""

from __future__ import annotations

import json
import re

from ..catalog.loader import get_catalog
from ..config import settings
from ..llm import json_call
from ..observability import prism
from ..store.db import Store, now
from . import tavily_client as tv
from .probe import probe

DEFAULT_SUBPROCESSORS = ["Amazon Web Services", "Google Workspace", "GitHub"]
PAGE_HINTS = ("security", "trust", "privacy", "legal", "terms", "compliance", "soc", "gdpr", "responsible-disclosure", "security.txt")


def _brand_legal() -> tuple[str, str, str]:
    return settings.vendor_brand, settings.vendor_legal_name, settings.vendor_domain


def entity_facts(store: Store) -> list[dict]:
    brand, legal, domain = _brand_legal()
    res = tv.search(f"{legal} {brand} company founded headquarters founders", max_results=8)
    res += tv.search(f"\"{legal.split(' Inc')[0]}\" private limited OR subsidiary OR incorporated", max_results=6)
    ids = tv.record_findings(store, "entity", f"{legal} / {brand} entity facts", res, "company_profile")
    return res


def breach_history(store: Store) -> list[dict]:
    brand, legal, _ = _brand_legal()
    q = f"{brand} OR \"{legal}\" data breach OR security incident OR hacked OR leaked"
    res = tv.search(q, topic="news", time_range="year", max_results=8)
    res += tv.search(f"{brand} {legal} breach incident disclosure", max_results=6)
    relevant = [r for r in res if re.search(brand, r["title"] + r["snippet"], re.I) or re.search(legal.split(" ")[0], r["title"] + r["snippet"], re.I)]
    if relevant:
        tv.record_findings(store, "breach", q, relevant, "security_incident_history",
                           note="Public report mentioning the company alongside breach/incident terms — verify with the employee; may be a false positive.")
    else:
        tv.record_absence(store, "breach", q, "security_incident_history",
                          note="No public breach/incident reports found. This is NOT evidence of 'No' for Q48 — confirm with the employee.")
    return relevant


def public_pages(store: Store) -> dict:
    brand, legal, domain = _brand_legal()
    urls = tv.site_map(domain)
    picked = [u for u in urls if isinstance(u, str) and any(h in u.lower() for h in PAGE_HINTS)][:5]
    found = {"mapped": len(urls), "candidates": picked, "pages": []}
    if picked:
        for page in tv.extract(picked):
            if not page.get("content"):
                continue
            low = page["url"].lower()
            control = "privacy_policy" if "privacy" in low else "vulnerability_disclosure" if "security.txt" in low or "disclosure" in low else "public_security_policy"
            tv.record_findings(store, "public_page", f"map {domain}", [{"url": page["url"], "title": page["url"].split("/")[-1] or page["url"], "snippet": page["content"][:1500], "published_at": ""}], control,
                               note="Content published on the vendor's own website.")
            found["pages"].append({"url": page["url"], "chars": len(page["content"])})
    for control, words in (("public_security_policy", ("security", "trust")), ("privacy_policy", ("privacy",)), ("vulnerability_disclosure", ("security.txt", "disclosure", "vulnerability"))):
        if not any(any(w in u.lower() for w in words) for u in picked):
            tv.record_absence(store, "public_page", f"{domain} {'/'.join(words)} page", control,
                              note=f"No {' or '.join(words)} page discovered on {domain}. If none exists, the buyer will mark the related question as 'No'.")
    return found


def attestations(store: Store) -> list[dict]:
    brand, legal, domain = _brand_legal()
    res = tv.search(f"{brand} SOC 2 OR ISO 27001 OR HIPAA compliance trust center attestation site:{domain} OR {brand}", max_results=8)
    tv.record_findings(store, "attestation", f"{brand} attestations", res, "company_profile",
                       note="Public claim about certifications/attestations. Compare with the attestation documents actually held.")
    return res


def _subprocessors(store: Store) -> list[str]:
    names: set[str] = set()
    for c in store.q("SELECT value, statement FROM claims WHERE control IN ('vendor_list','data_hosting','third_party_risk','outsourced_security')"):
        for cand in ("AWS", "Amazon Web Services", "Google Workspace", "GitHub", "Vanta", "Drata", "Okta", "Slack", "Notion", "Jira", "Cloudflare", "Datadog"):
            if cand.lower() in (c["value"] + " " + c["statement"]).lower():
                names.add("Amazon Web Services" if cand == "AWS" else cand)
    return sorted(names) or DEFAULT_SUBPROCESSORS


def fourth_party(store: Store) -> dict:
    out = {}
    for name in _subprocessors(store)[:6]:
        q = f"{name} security incident OR breach OR vulnerability"
        res = tv.search(q, topic="news", time_range="month", max_results=4)
        tv.record_findings(store, "fourth_party", q, res, "supply_chain", note=f"Recent public security news about subprocessor {name}. Informational watchlist; does not change any answer.")
        out[name] = [r["title"] for r in res]
    return out


def live_probe(store: Store) -> dict:
    _, _, domain = _brand_legal()
    p = probe(domain)
    # Register as an observed record (authority 4) so Q34 can be verified by observation.
    doc = store.one("SELECT id FROM documents WHERE path=?", (f"probe://{domain}",))
    if doc:
        store.execute("DELETE FROM documents WHERE id=?", (doc["id"],))
    doc_id = store.insert("documents", {
        "path": f"probe://{domain}", "name": f"Live TLS/header probe of {domain}", "folder": "live", "ext": "",
        "doc_type": "record", "authority": 4, "is_template": 0, "entity": settings.vendor_brand, "effective_date": p["checked_at"][:10],
        "text_len": len(json.dumps(p)), "sha": "", "summary": "Direct observation of the public website's TLS and HTTP security headers.", "indexed_at": now(),
    })
    cid = store.insert("chunks", {"doc_id": doc_id, "idx": 0, "heading": "probe", "text": json.dumps(p, indent=1), "sha": ""})
    tls, hdr, st = p["tls"], p["headers"], p["security_txt"]
    claims = []
    if tls.get("ok"):
        claims.append(("tls_certificate", "certificate_present", "yes", f"{domain} serves a valid TLS certificate issued by {tls.get('issuer') or 'unknown'} (expires {tls.get('not_after')}), negotiated {tls.get('protocol')}."))
        claims.append(("encryption_in_transit", "public_tls_version", tls.get("protocol", ""), f"The public website negotiates {tls.get('protocol')} with cipher {tls.get('cipher')}."))
    else:
        claims.append(("tls_certificate", "certificate_present", "unknown", f"TLS probe of {domain} failed: {tls.get('error')}."))
    if hdr.get("ok"):
        claims.append(("network_architecture", "security_headers_missing", ", ".join(hdr["missing"]) or "none", f"HTTP security headers missing on {domain}: {', '.join(hdr['missing']) or 'none'}; present: {', '.join(hdr['present']) or 'none'}."))
    claims.append(("vulnerability_disclosure", "security_txt", "yes" if st.get("found") else "no", f"security.txt {'found at ' + st['url'] if st.get('found') else 'not published'} on {domain}."))
    for control, attr, val, stmt in claims:
        store.insert("claims", {"doc_id": doc_id, "chunk_id": cid, "control": control, "attribute": attr, "value": val, "statement": stmt,
                                "modality": "record_shows", "authority": 4, "observed_at": p["checked_at"][:10], "excerpt": stmt[:200]})
    return p


SUMMARY_SYSTEM = """You compile the 'Reputational Assessment' section of a buyer's vendor-risk workbook from public web findings,
and compare them with what the vendor's own documents say. Be strictly factual; every field must be traceable to a
finding id (X#) or an internal claim id (C#); write "Not found in public sources" when nothing supports a field.
Never claim a sanctions/regulatory screening was performed — search results are indicative only.

Return ONLY JSON:
{"fields": {"vendor_legal_name": "", "dba_brand_names": "", "corporate_website": "", "trust_portal_url": "", "headquarters": "",
  "countries_of_operation": "", "year_founded": "", "corporate_structure": "", "leadership": "", "funding": "",
  "bbb_rating": "", "publicly_reported_issues": "", "news_media_risk_indicators": "", "social_media_risk_indicators": "",
  "sanctions_ofac": "", "sos_standing": "", "legal_compliance_posture": "", "assurance_documents_public_claims": "",
  "regulatory_investigations": ""},
 "sources": {"field_name": ["X1", "C22"]},
 "discrepancies": [{"description": "...", "internal_ids": ["C.."], "external_ids": ["X.."], "question_to_ask": "..."}],
 "questions_for_employee": ["..."]}"""


def summary(store: Store) -> dict:
    ext = store.q("SELECT * FROM external_findings ORDER BY id")
    internal = store.q("SELECT c.id, c.statement, d.name AS doc FROM claims c JOIN documents d ON d.id=c.doc_id WHERE c.control IN ('company_profile','data_location','roles_responsibilities','governance_program') ORDER BY c.id")
    user = "EXTERNAL FINDINGS:\n" + "\n".join(f"X{x['id']} | {x['kind']} | {x['title']} | {x['url']} | {x['published_at']} | {x['snippet'][:400]} {x['note'] or ''}" for x in ext)
    user += "\n\nINTERNAL CLAIMS (company profile / leadership / location):\n" + "\n".join(f"C{c['id']} | {c['doc']} | {c['statement']}" for c in internal[:80])
    user += f"\n\nVENDOR: legal name per config '{settings.vendor_legal_name}', brand '{settings.vendor_brand}', domain {settings.vendor_domain}."
    with prism.step("outside_in_research"):
        data = json_call(SUMMARY_SYSTEM, user, model=settings.model_agent, max_tokens=3000)
    data["generated_at"] = now()
    store.kv_set("reputational", data)
    # discrepancies become open conflicts (external vs internal) so the interview picks them up
    for d in data.get("discrepancies", []):
        store.insert("conflicts", {
            "control": "company_profile", "attribute": "external_vs_internal", "claim_ids": json.dumps(d.get("internal_ids", []) + d.get("external_ids", [])),
            "description": str(d.get("description", ""))[:600], "question_to_ask": str(d.get("question_to_ask", ""))[:400], "status": "open",
            "resolution": json.dumps({"severity": "medium", "controls": ["company_profile"], "source": "outside_in"}), "created_at": now(),
        })
    return data


def run_all(store: Store, progress=None) -> dict:
    emit = progress or (lambda *_: None)
    out: dict = {}
    for name, fn in (("live_probe", live_probe), ("entity_facts", entity_facts), ("public_pages", public_pages),
                     ("attestations", attestations), ("breach_history", breach_history), ("fourth_party", fourth_party)):
        emit("research", {"mode": name})
        try:
            out[name] = fn(store)
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": str(e)}
            store.log("research_error", f"{name}: {e}")
    emit("research", {"mode": "summary"})
    try:
        out["summary"] = summary(store)
    except Exception as e:  # noqa: BLE001
        out["summary"] = {"error": str(e)}
    # re-derive questions touched by external evidence / probe
    from ..engine.derive import derive_all
    from ..engine.scorer import score

    cat = get_catalog()
    touched = {"company_profile", "public_security_policy", "privacy_policy", "vulnerability_disclosure", "tls_certificate",
               "security_incident_history", "data_location", "supply_chain", "encryption_in_transit", "network_architecture"}
    qids = sorted({q.qid for c in touched for q in cat.questions_for_control(c)}, key=float)
    derive_all(store, qids)
    score(store)
    store.kv_set("last_research", {"at": now(), "modes": list(out.keys())})
    return out


MODES = {"entity_facts": entity_facts, "breach_history": breach_history, "public_pages": public_pages,
         "attestations": attestations, "fourth_party": fourth_party, "live_probe": live_probe, "summary": summary}
