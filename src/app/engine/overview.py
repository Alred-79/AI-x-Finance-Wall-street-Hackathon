"""Data overview for the visual Data view: tiers, coverage matrix, topics, conflict pairs."""

from __future__ import annotations

from ..catalog.loader import get_catalog
from ..store.db import Store, loads
from .conflicts import GROUPS
from .derive import question_states

TIERS = [(4, "record"), (3, "attestation"), (2, "policy"), (1, "template"), (5, "employee"), (0, "public")]


def overview(store: Store) -> dict:
    cat = get_catalog()
    counts = store.counts()
    docs = store.q("SELECT d.id, d.name, d.doc_type, d.authority, d.is_template, d.effective_date, d.entity, d.text_len, "
                   "(SELECT count(*) FROM claims c WHERE c.doc_id=d.id) AS n_claims FROM documents d ORDER BY d.authority DESC, n_claims DESC")
    tiers = []
    for a, label in TIERS[:4]:
        ds = [d for d in docs if d["authority"] == a]
        tiers.append({"authority": a, "label": label, "documents": len(ds), "claims": sum(d["n_claims"] for d in ds)})
    tiers.append({"authority": 5, "label": "employee", "documents": 0, "claims": counts["user_statements"]})
    tiers.append({"authority": 0, "label": "public", "documents": 0, "claims": counts["external_findings"]})

    # coverage matrix: control × tier
    per = {}
    for r in store.q("SELECT c.control, c.authority, d.is_template, count(*) AS n FROM claims c JOIN documents d ON d.id=c.doc_id GROUP BY c.control, c.authority, d.is_template"):
        tier = 1 if r["is_template"] else r["authority"]
        per.setdefault(r["control"], {})[tier] = per.get(r["control"], {}).get(tier, 0) + r["n"]
    for r in store.q("SELECT control, count(*) AS n FROM user_statements GROUP BY control"):
        per.setdefault(r["control"], {})[5] = r["n"]
    for r in store.q("SELECT control, count(*) AS n FROM external_findings GROUP BY control"):
        per.setdefault(r["control"], {})[0] = r["n"]
    open_conf = {}
    for k in store.q("SELECT control, resolution FROM conflicts WHERE status='open'"):
        for c in set((loads(k["resolution"], {}) or {}).get("controls", [])) | {k["control"]}:
            open_conf[c] = open_conf.get(c, 0) + 1
    states = question_states(store)
    by_control_status: dict[str, dict[str, int]] = {}
    for s in states:
        for c in s["controls"]:
            by_control_status.setdefault(c, {})[s["status"]] = by_control_status.get(c, {}).get(s["status"], 0) + 1
    group_of = {c: g for g, cs in GROUPS.items() for c in cs}
    coverage = []
    for cid, meta in cat.controls.items():
        cells = per.get(cid, {})
        coverage.append({
            "control": cid, "name": meta["name"], "group": group_of.get(cid, "other"), "owner_role": meta.get("owner_role"),
            "tiers": {label: cells.get(a, 0) for a, label in TIERS}, "total": sum(cells.values()),
            "open_conflicts": open_conf.get(cid, 0), "questions": [q.qid for q in cat.questions_for_control(cid)],
            "statuses": by_control_status.get(cid, {}),
        })
    coverage.sort(key=lambda r: (r["group"], -r["total"]))

    topics: dict[str, dict[str, int]] = {}
    for s in states:
        t = topics.setdefault(s["topic"], {"VERIFIED": 0, "CONFIRMED_BY_USER": 0, "PARTIAL": 0, "CONFLICT": 0, "UNKNOWN": 0, "total": 0})
        t[s["status"]] += 1
        t["total"] += 1

    conflicts = []
    for k in store.q("SELECT * FROM conflicts ORDER BY status DESC, id"):
        ids = [int(i[1:]) for i in (loads(k["claim_ids"], []) or []) if str(i).startswith("C") and str(i)[1:].isdigit()]
        cl = store.q(f"SELECT c.id, c.statement, c.authority, c.observed_at, d.name AS doc, d.doc_type, d.is_template FROM claims c JOIN documents d ON d.id=c.doc_id WHERE c.id IN ({','.join('?' for _ in ids) or 'NULL'})", ids) if ids else []
        meta = loads(k["resolution"], {}) or {}
        conflicts.append({"id": k["id"], "status": k["status"], "severity": meta.get("severity", "medium"), "controls": meta.get("controls", [k["control"]]),
                          "attribute": k["attribute"], "description": k["description"], "question_to_ask": k["question_to_ask"], "claims": cl,
                          "resolved_by": k["resolved_by"], "resolution_text": meta.get("text")})

    return {"counts": counts, "tiers": tiers, "documents": docs, "coverage": coverage, "topics": topics, "conflicts": conflicts,
            "dialect": store.dialect, "pgvector": store.has_pgvector, "last_run": store.kv_get("last_run"), "last_research": store.kv_get("last_research")}
