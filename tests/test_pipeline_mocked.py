"""End-to-end plumbing test with a mocked LLM: index → conflicts → derive → score → planner → user fact."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.app.catalog.loader import get_catalog
from src.app.config import settings
from src.app.engine import conflicts as conflicts_mod
from src.app.engine import derive as derive_mod
from src.app.engine.pipeline import full_run, record_user_fact, resolve_conflict
from src.app.engine.planner import open_items
from src.app.engine.search import EvidenceIndex
from src.app.extract import claims as claims_mod
from src.app.store.db import Store

KEYWORDS = {
    "mfa": ["multi-factor", "mfa"], "backup_recovery": ["backup", "restore", "rto", "rpo"],
    "production_access": ["production access", "admin"], "access_review": ["access review", "revoke"],
    "vulnerability_scanning": ["scanning", "scan"], "penetration_testing": ["penetration", "vapt"],
    "password_policy": ["password", "rotation"], "encryption_at_rest": ["aes", "at rest"],
    "encryption_in_transit": ["tls"], "security_training": ["training"], "background_checks": ["background"],
    "offboarding": ["offboard", "retired"], "incident_response": ["incident", "sev-"],
}


def fake_extract(system, user, **kw):
    text = user.split("TEXT:", 1)[-1]
    out = []
    for sent in re.split(r"(?<=[.\n])\s+", text)[:400]:
        low = sent.lower()
        for ctrl, kws in KEYWORDS.items():
            if any(k in low for k in kws) and 30 < len(sent) < 400:
                out.append({"control": ctrl, "attribute": kws[0].replace(" ", "_"), "value": "see statement",
                            "statement": sent.strip()[:300], "excerpt": sent.strip()[:200], "observed_at": ""})
                break
        if len(out) >= 12:
            break
    return {"claims": out}


def fake_conflicts(system, user, **kw):
    ids = re.findall(r"^(C\d+)", user, re.M)
    if "GROUP: access" in user and len(ids) >= 2:
        return {"conflicts": [{"attribute": "standing_prod_access", "claim_ids": ids[:2],
                               "description": "Policy limits standing production access to the CTO but the access review lists several admins.",
                               "question_to_ask": "Who currently holds standing AWS production admin access?", "severity": "high",
                               "controls": ["production_access", "access_review"]}]}
    return {"conflicts": []}


def fake_derive(system, user, **kw):
    ids = re.findall(r"^(C\d+|U\d+)", user, re.M)
    slots = re.findall(r"^- (\w+):", user.split("SLOTS:", 1)[-1].split("EVIDENCE:", 1)[0], re.M)
    users = [i for i in ids if i.startswith("U")]
    filled = bool(ids)
    return {
        "response": "Yes — supported by policy." if filled else "Unknown — needs confirmation",
        "comments": "Confirmed by employee." if users else "From documents.",
        "answer_value": "Yes" if filled else "Unknown",
        "slot_assessment": {s: {"filled": filled, "value": "x", "evidence_ids": ids[:1]} for s in slots},
        "evidence_ids": ids[:3], "next_question": "" if filled else "Please confirm.", "notes_for_analyst": "",
    }


import os

STORES = ["sqlite"] + (["postgres"] if os.getenv("TEST_DATABASE_URL") else [])


@pytest.fixture(params=STORES)
def store(request, tmp_path, monkeypatch):
    monkeypatch.setattr(claims_mod, "json_call", fake_extract)
    monkeypatch.setattr(conflicts_mod, "json_call", fake_conflicts)
    monkeypatch.setattr(derive_mod, "json_call", fake_derive)
    monkeypatch.setattr(claims_mod, "summarise", lambda text, name: "summary")
    monkeypatch.setattr(claims_mod, "CACHE", tmp_path / "cache")
    import src.app.ingest.indexer as idx
    monkeypatch.setattr(idx, "summarise", lambda text, name: "summary")
    monkeypatch.setattr(idx, "_vision_text", lambda doc: "")
    object.__setattr__(settings, "embedding_provider", "none")  # dense retrieval is covered by test_embeddings_smoke
    if request.param == "postgres":
        s = Store(url=os.environ["TEST_DATABASE_URL"])
        s.wipe()
        yield s
        s.wipe()
        return
    yield Store(tmp_path / "p.db")


def test_full_pipeline(store):
    res = full_run(store, Path(settings.datasets_dir))
    assert res["index"]["files"] == 26
    assert res["index"]["claims"] > 20
    assert res["conflicts"] >= 1
    states = derive_mod.question_states(store)
    assert len(states) == 66
    by = {s["qid"]: s for s in states}
    # questions on access controls are in conflict; those with no claims are unknown
    assert by["56"]["status"] == "CONFLICT" and by["56"]["confidence"] <= 0.5
    assert any(s["status"] == "UNKNOWN" for s in states)
    assert all(s["answer"] == "Unknown — needs confirmation" for s in states if s["status"] == "UNKNOWN")
    sc = res["score"]
    assert sc["vendor_criticality"] == "SC1: Mission Critical"
    assert sc["inherent_points"] > 0 and sc["predicted_rating"] in ("Low", "Moderate", "High", "Critical")
    assert any(e["kind"] == "document" and "Cyber Liability" in e["text"] for e in sc["escalations"])
    assert sc["fix_first"], "fix-first list should not be empty"

    items = open_items(store)
    assert items and items[0]["priority"] >= items[-1]["priority"]
    conf = items[0].get("conflict_id") or next(i["conflict_id"] for i in items if i["conflict_id"])

    # search works over claims + chunks
    idx = EvidenceIndex(store)
    hits = idx.search("production access admin", k=5)
    assert hits and hits[0]["type"] in ("claim", "chunk")

    # user fact supersedes and re-derives
    r1 = record_user_fact(store, control="production_access", attribute="standing_prod_access", value="CTO + K. O'Brien",
                          speaker="Sam", role="CTO", statement="Standing production access is held by the CTO and the Security Lead.")
    r2 = record_user_fact(store, control="production_access", attribute="standing_prod_access", value="CTO only",
                          speaker="Sam", role="CTO", statement="Correction: only the CTO holds standing production access as of today.")
    assert r2["supersedes"] == r1["id"]
    live = store.q("SELECT id FROM user_statements WHERE id NOT IN (SELECT supersedes FROM user_statements WHERE supersedes IS NOT NULL)")
    assert [r["id"] for r in live] == [r2["id"]]

    # resolving the conflict flips Q56 out of CONFLICT
    resolve_conflict(store, conf, "Contractor access revoked on Sept 5; CTO is sole standing admin.", "Sam (CTO)")
    by = {s["qid"]: s for s in derive_mod.question_states(store)}
    assert by["56"]["status"] in ("CONFIRMED_BY_USER", "VERIFIED", "PARTIAL")
    assert by["56"]["confidence"] > 0.5
