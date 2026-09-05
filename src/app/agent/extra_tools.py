"""Feature tools registered into the analyst agent. EXTRA_TOOLS: OpenAI tool specs; EXTRA_HANDLERS: name → fn(agent, **args).

Dashboards: `get_metrics` hands the model ready-made numbers for the live sources; `propose_visual` attaches a validated
chart spec to the turn (agent.visuals → the streamed "done" event → rendered under the reply with "Add to dashboard").
"""

from __future__ import annotations

from ..engine import dashboards
from ..store.db import now

_VISUAL_DESCRIPTION = (
    "Attach a small chart to your reply. Use it ONLY when the answer genuinely contains numbers the employee would want to see at a glance: "
    "a score breakdown (risk points by topic or question), questionnaire status by topic, escalation counts, claims per evidence tier, "
    "the top open items, a before/after of points, or a short timeline of counts. NEVER for a single yes/no answer, a one-line fact, or "
    "to decorate prose. One visual per turn is normal; two at most. Prefer get_metrics first — it returns a ready spec you can pass "
    "straight through (edit title/description if you like). Kinds: 'bar' (horizontal bars, 1-3 series), 'stacked_bar' (ordered parts of a "
    "whole per label, 2-5 series, first series = the best state), 'stat' (one hero number; extra label/value pairs become context), "
    "'table' (rows = labels, columns = series). Every series must have exactly one value per label. Set live_source when the data came "
    "from get_metrics so the dashboard can refresh it later; leave it null for numbers you computed from evidence. Cite what the numbers "
    "came from in source_ids (evidence ids like C12/U3/X5, or tool names like get_score). If the tool returns {error}, fix the spec and retry once."
)

EXTRA_TOOLS: list[dict] = [
    {"type": "function", "function": {
        "name": "get_metrics",
        "description": ("Ready-made, up-to-date numbers for a chart, straight from the store. Returns {spec, alternatives, summary}: `spec` is a "
                        "complete propose_visual payload; `alternatives` are other valid specs for the same source (e.g. a stat tile); `summary` "
                        "has the raw figures for your prose. Names: 'status_by_topic' (66 questions by status per topic), 'score' (buyer's-eye "
                        "inherent points by topic, hero points/rating/escalations, highest-risk questions, fix-first), 'tiers' (claims per "
                        "evidence tier), 'open_items' (top open questions by priority). Call this, then propose_visual with the spec."),
        "parameters": {"type": "object", "properties": {"name": {"type": "string", "enum": list(dashboards.LIVE_SOURCES)}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "propose_visual",
        "description": _VISUAL_DESCRIPTION,
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "short chart title, max 80 chars"},
            "kind": {"type": "string", "enum": list(dashboards.KINDS)},
            "description": {"type": "string", "description": "one sentence: what the reader should see in this chart"},
            "unit": {"type": "string", "description": "unit of the values, e.g. 'questions', 'risk points', 'claims'; may be empty"},
            "data": {"type": "object", "properties": {
                "labels": {"type": "array", "items": {"type": "string"}},
                "series": {"type": "array", "items": {"type": "object", "properties": {
                    "name": {"type": "string"}, "values": {"type": "array", "items": {"type": "number"}}}, "required": ["name", "values"]}}},
                "required": ["labels", "series"]},
            "source_ids": {"type": "array", "items": {"type": "string"}, "description": "evidence ids (C12, U3, X5) or tool names (get_score, get_metrics) the numbers came from"},
            "live_source": {"type": "string", "enum": list(dashboards.LIVE_SOURCES), "description": "set when data came from get_metrics so the dashboard can refresh it; omit for static numbers"},
        }, "required": ["title", "kind", "description", "data"]}}},
]


def _get_metrics(agent, name: str = "", **_ignored):
    try:
        return dashboards.metrics(agent.store, str(name))
    except KeyError as e:
        return {"error": str(e).strip("'")}


def _propose_visual(agent, **raw):
    if len(agent.visuals) >= 3:
        return {"error": "at most three visuals per turn; the reply already has three"}
    spec, err = dashboards.validate_spec(raw)
    if err:
        return {"error": err}
    vid = f"v{len(agent.visuals) + 1}"
    agent.visuals.append({"id": vid, "created_at": now(), **spec})
    return {"ok": True, "visual_id": vid, "note": "The chart renders under your reply with an 'Add to dashboard' button; refer to it briefly in prose, don't repeat every number."}


EXTRA_HANDLERS: dict = {"get_metrics": _get_metrics, "propose_visual": _propose_visual}
