"""Query-driven dashboards: chart-spec validation, ready-made metrics for the agent, and CRUD over saved cards.

A *visual spec* is a small, renderer-agnostic description the agent proposes during a chat turn:

    {title, kind: bar|stacked_bar|stat|table, description, unit,
     data: {labels: [str], series: [{name: str, values: [number]}]},
     source_ids: [C#/U#/X# or tool names], live_source: null | status_by_topic | score | tiers | open_items}

Specs with a `live_source` can be refreshed from the store (`resolve_live`), so a saved card stays current.
"""

from __future__ import annotations

import math
import re
from typing import Any

from ..store.db import Store, loads, now

KINDS = ("bar", "stacked_bar", "stat", "table")
LIVE_SOURCES = ("status_by_topic", "score", "tiers", "open_items")
STATUS_ORDER = ["VERIFIED", "CONFIRMED_BY_USER", "PARTIAL", "CONFLICT", "UNKNOWN"]
STATUS_LABEL = {"VERIFIED": "Verified", "CONFIRMED_BY_USER": "Confirmed by employee", "PARTIAL": "Partial", "CONFLICT": "Conflict", "UNKNOWN": "Unknown"}
TIER_LABEL = {"record": "Records", "attestation": "Attestations", "policy": "Policies", "template": "Templates", "employee": "Employee statements", "public": "Public web"}

MAX_LABELS, MAX_SERIES = 30, 6
_SOURCE_ID = re.compile(r"^([CUX]\d+|[a-z][a-z0-9_]{1,40})$")


# ----------------------------------------------------------------------------- validation
def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def validate_spec(raw: Any) -> tuple[dict | None, str | None]:
    """Return (clean_spec, None) or (None, error). Strict on purpose: the error text is fed back to the model."""
    if not isinstance(raw, dict):
        return None, "spec must be an object"
    title = str(raw.get("title") or "").strip()
    if not 1 <= len(title) <= 80:
        return None, "title is required (1-80 characters)"
    kind = raw.get("kind")
    if kind not in KINDS:
        return None, f"kind must be one of {', '.join(KINDS)}"
    description = str(raw.get("description") or "").strip()
    if len(description) > 240:
        return None, "description must be one sentence (max 240 characters)"
    unit = str(raw.get("unit") or "").strip()
    if len(unit) > 24:
        return None, "unit must be short (max 24 characters)"
    live = raw.get("live_source") or None
    if live in ("none", "null", "static"):
        live = None
    if live is not None and live not in LIVE_SOURCES:
        return None, f"live_source must be null or one of {', '.join(LIVE_SOURCES)}"

    data = raw.get("data")
    if not isinstance(data, dict):
        return None, "data must be an object {labels: [...], series: [...]}"
    labels = data.get("labels")
    series = data.get("series")
    if not isinstance(labels, list) or not labels or not all(isinstance(x, (str, int, float)) and str(x).strip() for x in labels):
        return None, "data.labels must be a non-empty list of strings"
    if len(labels) > MAX_LABELS:
        return None, f"too many labels ({len(labels)}); keep at most {MAX_LABELS} — aggregate the tail into 'Other'"
    labels = [str(x).strip()[:60] for x in labels]
    if not isinstance(series, list) or not series:
        return None, "data.series must be a non-empty list of {name, values}"
    if len(series) > MAX_SERIES:
        return None, f"too many series ({len(series)}); keep at most {MAX_SERIES}"
    clean_series = []
    for i, s in enumerate(series):
        if not isinstance(s, dict):
            return None, f"series[{i}] must be an object {{name, values}}"
        name = str(s.get("name") or "").strip()
        if not name:
            return None, f"series[{i}].name is required"
        values = s.get("values")
        if not isinstance(values, list) or len(values) != len(labels):
            return None, f"series[{i}].values must have exactly {len(labels)} numbers (one per label)"
        nums = [_num(v) for v in values]
        if any(v is None for v in nums):
            return None, f"series[{i}].values must all be finite numbers"
        clean_series.append({"name": name[:40], "values": nums})
    if kind == "stat" and len(clean_series) != 1:
        return None, "stat takes exactly one series; the first value is the hero number, further label/value pairs are shown as context"
    if kind == "stacked_bar" and len(clean_series) < 2:
        return None, "stacked_bar needs at least two series; use kind 'bar' for a single series"
    if kind in ("bar", "stacked_bar") and len(labels) == 1 and len(clean_series) == 1:
        return None, "a single value is not a chart — use kind 'stat'"

    src = raw.get("source_ids")
    if src is None:
        src = []
    if not isinstance(src, list) or not all(isinstance(x, str) and _SOURCE_ID.match(x.strip()) for x in src):
        return None, "source_ids must be a list of evidence ids (C12, U3, X5) or tool names (get_score, get_metrics)"
    return {
        "title": title, "kind": kind, "description": description, "unit": unit,
        "data": {"labels": labels, "series": clean_series},
        "source_ids": [x.strip() for x in src][:20], "live_source": live,
    }, None


# ----------------------------------------------------------------------------- live metrics
def _spec(title: str, kind: str, description: str, unit: str, labels: list, series: list[dict], live: str, source: str) -> dict:
    return {"title": title, "kind": kind, "description": description, "unit": unit,
            "data": {"labels": labels, "series": series}, "source_ids": [source], "live_source": live}


def _status_by_topic(store: Store) -> dict:
    from .overview import overview
    topics = overview(store)["topics"]
    labels = list(topics.keys())
    series = [{"name": STATUS_LABEL[s], "values": [float(topics[t].get(s, 0)) for t in labels]} for s in STATUS_ORDER]
    total = sum(t["total"] for t in topics.values())
    verified = sum(t.get("VERIFIED", 0) + t.get("CONFIRMED_BY_USER", 0) for t in topics.values())
    spec = _spec("Questionnaire status by topic", "stacked_bar",
                 f"{verified} of {total} questions are verified or confirmed; the lighter segments are what still needs work.",
                 "questions", labels, series, "status_by_topic", "get_metrics")
    alt = _spec("Questions answered", "stat", "Verified or employee-confirmed answers out of the buyer's questionnaire.", "questions",
                ["Answered", "Total"], [{"name": "Questions", "values": [float(verified), float(total)]}], "status_by_topic", "get_metrics")
    return {"spec": spec, "alternatives": [alt], "summary": {"total": total, "answered": verified, "by_status": {s: sum(t.get(s, 0) for t in topics.values()) for s in STATUS_ORDER}}}


def _score(store: Store) -> dict:
    from .derive import question_states
    from .scorer import score
    sc = store.kv_get("last_score") or score(store)
    topic_of = {s["qid"]: s["topic"] for s in question_states(store)}
    by_topic: dict[str, float] = {}
    for r in sc.get("at_risk", []):
        t = topic_of.get(r["qid"], "Other")
        by_topic[t] = by_topic.get(t, 0.0) + float(r["inherent_pts"] or 0)
    ordered = sorted(by_topic.items(), key=lambda kv: -kv[1])
    n_esc = len(sc.get("escalations", []))
    spec = _spec("Predicted inherent risk points by topic", "bar",
                 f"Where the buyer's {sc.get('predicted_rating', 'n/a')} rating comes from: {int(sc.get('inherent_points', 0))} of {int(sc.get('max_inherent_points', 0))} possible points, concentrated in the top topics.",
                 "risk points", [t for t, _ in ordered] or ["No risk points"], [{"name": "Inherent points", "values": [v for _, v in ordered] or [0.0]}], "score", "get_score")
    hero = _spec("Buyer's-eye risk points", "stat", f"Predicted rating {sc.get('predicted_rating', 'n/a')} · {n_esc} predicted escalations.", "points",
                 ["Inherent points", "Maximum", "Escalations"],
                 [{"name": "Score", "values": [float(sc.get("inherent_points", 0)), float(sc.get("max_inherent_points", 0)), float(n_esc)]}], "score", "get_score")
    at_risk = sorted(sc.get("at_risk", []), key=lambda x: -x["inherent_pts"])[:8]
    top = _spec("Highest-risk open answers", "bar", "The questions costing the most inherent risk points right now.", "risk points",
                [f"Q{r['qid']} {r['text'][:42]}" for r in at_risk] or ["None"], [{"name": "Inherent points", "values": [float(r["inherent_pts"]) for r in at_risk] or [0.0]}], "score", "get_score")
    fixes = sc.get("fix_first", [])[:6]
    fix = _spec("Fix-first: points removed per action", "bar", "Quick wins ranked by risk points removed per hour of effort.", "risk points",
                [f["action"][:48] for f in fixes] or ["None"], [{"name": "Points removed", "values": [float(f["points"]) for f in fixes] or [0.0]}], None, "get_score")
    summary = {k: sc.get(k) for k in ("vendor_criticality", "predicted_rating", "inherent_points", "max_inherent_points", "residual_points", "risk_ratio")}
    summary["escalations"] = n_esc
    summary["escalation_kinds"] = {"question": sum(1 for e in sc.get("escalations", []) if e.get("kind") == "question"),
                                   "document": sum(1 for e in sc.get("escalations", []) if e.get("kind") == "document")}
    return {"spec": spec, "alternatives": [hero, top, fix], "summary": summary}


def _tiers(store: Store) -> dict:
    from .overview import overview
    tiers = overview(store)["tiers"]
    labels = [TIER_LABEL.get(t["label"], t["label"]) for t in tiers]
    spec = _spec("Evidence by source tier", "bar", "Records and attestations outrank policies; templates count for nothing in a contradiction.", "claims",
                 labels, [{"name": "Claims", "values": [float(t["claims"]) for t in tiers]}], "tiers", "get_metrics")
    return {"spec": spec, "alternatives": [], "summary": {t["label"]: {"documents": t["documents"], "claims": t["claims"]} for t in tiers}}


def _open_items(store: Store) -> dict:
    from .planner import open_items
    items = open_items(store)
    top = items[:8]
    spec = _spec("Top open items by priority", "bar", "What to ask the team next, ranked by buyer criticality, risk points and conflict weight.", "priority",
                 [f"Q{i['qid']} {i['text'][:42]}" for i in top] or ["Nothing open"], [{"name": "Priority", "values": [float(i["priority"]) for i in top] or [0.0]}], "open_items", "get_metrics")
    by_status = {s: sum(1 for i in items if i["status"] == s) for s in ("CONFLICT", "UNKNOWN", "PARTIAL")}
    alt = _spec("Open items", "stat", "Questions the documents cannot answer yet, by state.", "questions",
                ["Open", "Conflict", "Unknown", "Partial"], [{"name": "Open items", "values": [float(len(items)), *[float(by_status[s]) for s in ("CONFLICT", "UNKNOWN", "PARTIAL")]]}], "open_items", "get_metrics")
    return {"spec": spec, "alternatives": [alt], "summary": {"open": len(items), "by_status": by_status, "top": [{"qid": i["qid"], "priority": i["priority"], "status": i["status"]} for i in top]}}


METRICS = {"status_by_topic": _status_by_topic, "score": _score, "tiers": _tiers, "open_items": _open_items}


def metrics(store: Store, name: str) -> dict:
    """Ready-made chart specs for a live source: {"name", "spec", "alternatives", "summary"}."""
    if name not in METRICS:
        raise KeyError(f"unknown metric '{name}'. Use one of: {', '.join(METRICS)}")
    return {"name": name, **METRICS[name](store)}


def resolve_live(spec: dict, store: Store) -> dict:
    """Refresh `data` of a spec that has a live_source; keeps the saved title/description. Non-live specs are returned as-is."""
    live = spec.get("live_source")
    if live not in METRICS:
        return spec
    fresh = METRICS[live](store)
    candidates = [fresh["spec"], *fresh["alternatives"]]
    match = next((c for c in candidates if c["kind"] == spec.get("kind") and c["title"] == spec.get("title")), None) \
        or next((c for c in candidates if c["kind"] == spec.get("kind")), None) or fresh["spec"]
    return {**spec, "data": match["data"], "refreshed_at": now()}


# ----------------------------------------------------------------------------- CRUD
def _row(r: dict) -> dict:
    return {"id": r["id"], "title": r["title"], "source": r["source"], "position": r["position"], "created_at": r["created_at"], "spec": loads(r["spec"], {})}


def list_items(store: Store) -> list[dict]:
    return [_row(r) for r in store.q("SELECT * FROM dashboard_items ORDER BY position, id")]


def get_item(store: Store, item_id: int) -> dict | None:
    r = store.one("SELECT * FROM dashboard_items WHERE id=?", (int(item_id),))
    return _row(r) if r else None


def add_item(store: Store, spec: dict, source: str = "chat", title: str | None = None) -> dict:
    clean, err = validate_spec(spec)
    if err:
        raise ValueError(err)
    if title:
        clean["title"] = str(title).strip()[:80]
    pos = (store.one("SELECT max(position) AS m FROM dashboard_items")["m"] or 0) + 1
    import json
    iid = store.insert("dashboard_items", {"title": clean["title"], "spec": json.dumps(clean), "source": (source or "chat")[:40], "position": pos, "created_at": now()})
    store.log("dashboard_add", {"id": iid, "title": clean["title"], "kind": clean["kind"]})
    return get_item(store, iid)  # type: ignore[return-value]


def delete_item(store: Store, item_id: int) -> bool:
    if not get_item(store, item_id):
        return False
    store.execute("DELETE FROM dashboard_items WHERE id=?", (int(item_id),))
    return True


def reorder(store: Store, ids: list[int]) -> list[dict]:
    for pos, iid in enumerate(ids, start=1):
        store.execute("UPDATE dashboard_items SET position=? WHERE id=?", (pos, int(iid)))
    return list_items(store)
