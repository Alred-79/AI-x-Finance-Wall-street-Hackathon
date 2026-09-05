"""Interview planner: which open item to ask about next, for whom, and why."""

from __future__ import annotations

from ..store.db import Store, loads
from .derive import question_states

CRIT_W = {"critical": 3.0, "high": 2.2, "moderate": 1.5, "low": 1.0}
STATUS_W = {"CONFLICT": 1.6, "UNKNOWN": 1.25, "PARTIAL": 1.0}


def _crit_weight(crit: str) -> float:
    c = (crit or "").lower()
    return max([w for k, w in CRIT_W.items() if k in c], default=1.0)


def open_items(store: Store, role: str | None = None) -> list[dict]:
    items = []
    conflicts = store.q("SELECT * FROM conflicts WHERE status='open'")
    for s in question_states(store):
        if s["status"] not in STATUS_W:
            continue
        pts = s["inherent_pts"] or (2.0 if s["informational"] else 3.0)
        prio = pts * _crit_weight(s["criticality"]) * STATUS_W[s["status"]] * (1.3 if s["rule_if_no"] and "escalat" in s["rule_if_no"].lower() else 1.0)
        related = [c for c in conflicts if set((loads(c["resolution"], {}) or {}).get("controls", [c["control"]])) & set(s["controls"])]
        why = []
        if s["criticality"]:
            why.append(f"buyer criticality {s['criticality']}")
        if s["inherent_pts"]:
            why.append(f"{int(s['inherent_pts'])} inherent risk points if unanswered/No")
        if s["status"] == "CONFLICT" and related:
            why.append(f"conflict: {related[0]['description'][:160]}")
        elif s["open_slots"]:
            why.append("missing: " + ", ".join(list(s["open_slots"].keys())[:4]))
        question = (related[0]["question_to_ask"] if related and s["status"] == "CONFLICT" else s["next_question"]) or s["text"]
        items.append({
            "qid": s["qid"], "topic": s["topic"], "status": s["status"], "priority": round(prio, 1),
            "owner_role": s["owner_role"], "question": question, "why": "; ".join(why), "text": s["text"],
            "conflict_id": related[0]["id"] if related else None,
        })
    items.sort(key=lambda x: -x["priority"])
    if role:
        items = [i for i in items if i["owner_role"] == role] + [i for i in items if i["owner_role"] != role]
    return items


def next_item(store: Store, role: str | None = None, exclude_qids: set[str] | None = None) -> dict | None:
    for it in open_items(store, role):
        if not exclude_qids or it["qid"] not in exclude_qids:
            return it
    return None
