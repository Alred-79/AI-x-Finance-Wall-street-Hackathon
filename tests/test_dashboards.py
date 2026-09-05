"""Query-driven dashboards: propose_visual validation, get_metrics on seeded state, and the /api/dashboard endpoints."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.app.agent.extra_tools import EXTRA_HANDLERS, EXTRA_TOOLS
from src.app.agent.loop import Agent
from src.app.catalog.loader import get_catalog, seed_questions
from src.app.config import settings
from src.app.engine import dashboards
from src.app.store import db as dbmod
from src.app.store.db import Store

GOOD = {
    "title": "Questionnaire status by topic", "kind": "stacked_bar", "description": "Most topics are verified; access control still has conflicts.",
    "unit": "questions", "data": {"labels": ["Access", "Backups"], "series": [{"name": "Verified", "values": [3, 2]}, {"name": "Conflict", "values": [1, 0]}]},
    "source_ids": ["C12", "U3", "get_score"], "live_source": "status_by_topic",
}


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "p.db")
    seed_questions(s)
    return s


def _seed_states(s: Store) -> dict[str, int]:
    """Give every question a status so the metrics have something to count."""
    cat = get_catalog()
    cycle = ["VERIFIED", "VERIFIED", "UNKNOWN", "PARTIAL", "CONFLICT"]
    counts: dict[str, int] = {}
    for i, q in enumerate(cat.ordered()):
        st = cycle[i % len(cycle)]
        counts[st] = counts.get(st, 0) + 1
        s.upsert("question_state", "qid", {"qid": q.qid, "status": st, "answer": "x" if st == "VERIFIED" else "Unknown — needs confirmation", "comments": "",
                                             "confidence": 0.9 if st == "VERIFIED" else 0.0, "evidence": "[]", "open_slots": "{}", "next_question": "", "updated_at": "2026-09-05T00:00:00"})
        s.kv_set(f"answer_value:{q.qid}", "Yes" if st == "VERIFIED" else "Unknown")
    return counts


# ------------------------------------------------------------------------------------------------ tool contract
def test_tools_registered():
    names = {t["function"]["name"] for t in EXTRA_TOOLS}
    assert names == {"get_metrics", "propose_visual"} == set(EXTRA_HANDLERS)
    props = next(t for t in EXTRA_TOOLS if t["function"]["name"] == "propose_visual")["function"]["parameters"]["properties"]
    assert set(props) >= {"title", "kind", "description", "unit", "data", "source_ids", "live_source"}
    assert set(props["kind"]["enum"]) == set(dashboards.KINDS)


def test_propose_visual_good(store):
    agent = Agent(store, "s1", "Sam", "CTO")
    res = EXTRA_HANDLERS["propose_visual"](agent, **GOOD)
    assert res["ok"] and res["visual_id"] == "v1"
    assert len(agent.visuals) == 1
    v = agent.visuals[0]
    assert v["id"] == "v1" and v["created_at"] and v["kind"] == "stacked_bar"
    assert v["data"]["series"][0]["values"] == [3.0, 2.0] and v["live_source"] == "status_by_topic"
    assert v["source_ids"] == ["C12", "U3", "get_score"]
    # the done event carries the visuals verbatim
    out = agent._finish("Here is the breakdown.")
    assert out["visuals"] == agent.visuals
    saved = store.one("SELECT meta FROM messages WHERE role='assistant'")
    assert json.loads(saved["meta"])["visuals"][0]["title"] == GOOD["title"]


@pytest.mark.parametrize("patch,needle", [
    ({"kind": "pie"}, "kind must be one of"),
    ({"title": ""}, "title is required"),
    ({"data": {"labels": ["a", "b"], "series": [{"name": "s", "values": [1]}]}}, "exactly 2 numbers"),
    ({"data": {"labels": ["a", "b"], "series": [{"name": "s", "values": [1, "x"]}]}}, "finite numbers"),
    ({"data": {"labels": [], "series": []}}, "labels must be a non-empty list"),
    ({"kind": "stacked_bar", "data": {"labels": ["a", "b"], "series": [{"name": "s", "values": [1, 2]}]}}, "at least two series"),
    ({"kind": "bar", "data": {"labels": ["a"], "series": [{"name": "s", "values": [1]}]}}, "use kind 'stat'"),
    ({"kind": "stat", "data": {"labels": ["a"], "series": [{"name": "s", "values": [1]}, {"name": "t", "values": [2]}]}}, "exactly one series"),
    ({"live_source": "weather"}, "live_source must be"),
    ({"source_ids": ["not an id!"]}, "source_ids must be"),
    ({"data": "nope"}, "data must be an object"),
])
def test_propose_visual_rejects(store, patch, needle):
    agent = Agent(store, "s2")
    res = EXTRA_HANDLERS["propose_visual"](agent, **{**GOOD, **patch})
    assert "error" in res and needle in res["error"], res
    assert agent.visuals == []


def test_propose_visual_stat_and_static(store):
    agent = Agent(store, "s3")
    res = EXTRA_HANDLERS["propose_visual"](agent, title="Buyer's-eye points", kind="stat", description="Predicted points.", unit="points",
                                           data={"labels": ["Inherent", "Max"], "series": [{"name": "Score", "values": [42, 300]}]}, source_ids=["get_score"])
    assert res["ok"] and agent.visuals[0]["live_source"] is None and agent.visuals[0]["unit"] == "points"


# ------------------------------------------------------------------------------------------------ metrics
def test_get_metrics_status_by_topic(store):
    counts = _seed_states(store)
    agent = Agent(store, "m1")
    res = EXTRA_HANDLERS["get_metrics"](agent, name="status_by_topic")
    spec = res["spec"]
    assert spec["kind"] == "stacked_bar" and spec["live_source"] == "status_by_topic"
    names = [s["name"] for s in spec["data"]["series"]]
    assert names == ["Verified", "Confirmed by employee", "Partial", "Conflict", "Unknown"]
    assert all(len(s["values"]) == len(spec["data"]["labels"]) for s in spec["data"]["series"])
    assert sum(sum(s["values"]) for s in spec["data"]["series"]) == 66
    assert sum(spec["data"]["series"][0]["values"]) == counts["VERIFIED"]
    assert res["summary"]["total"] == 66 and res["summary"]["by_status"]["CONFLICT"] == counts["CONFLICT"]
    # the ready-made spec is accepted verbatim by propose_visual
    assert EXTRA_HANDLERS["propose_visual"](agent, **spec)["ok"]
    for alt in res["alternatives"]:
        assert dashboards.validate_spec(alt)[1] is None


def test_get_metrics_score_open_items_tiers(store):
    _seed_states(store)
    agent = Agent(store, "m2")
    sc = EXTRA_HANDLERS["get_metrics"](agent, name="score")
    assert sc["spec"]["kind"] == "bar" and sc["spec"]["unit"] == "risk points"
    assert sc["summary"]["predicted_rating"] in ("Low", "Moderate", "High", "Critical")
    assert sc["summary"]["inherent_points"] > 0 and sc["summary"]["escalations"] >= 1
    kinds = {a["kind"] for a in sc["alternatives"]}
    assert "stat" in kinds
    for a in [sc["spec"], *sc["alternatives"]]:
        assert dashboards.validate_spec(a)[1] is None, a["title"]

    oi = EXTRA_HANDLERS["get_metrics"](agent, name="open_items")
    assert oi["spec"]["kind"] == "bar" and oi["summary"]["open"] > 0
    assert len(oi["spec"]["data"]["labels"]) == min(8, oi["summary"]["open"])
    assert oi["spec"]["data"]["series"][0]["values"] == sorted(oi["spec"]["data"]["series"][0]["values"], reverse=True)

    tiers = EXTRA_HANDLERS["get_metrics"](agent, name="tiers")
    assert tiers["spec"]["data"]["labels"][0] == "Records" and len(tiers["spec"]["data"]["labels"]) == 6

    assert "error" in EXTRA_HANDLERS["get_metrics"](agent, name="weather")


def test_resolve_live_refreshes_data(store):
    _seed_states(store)
    stale = {**GOOD, "data": {"labels": ["Old"], "series": [{"name": "Verified", "values": [1]}, {"name": "Unknown", "values": [1]}]}}
    fresh = dashboards.resolve_live(stale, store)
    assert fresh["title"] == GOOD["title"] and fresh["refreshed_at"]
    assert sum(sum(s["values"]) for s in fresh["data"]["series"]) == 66
    static = {**GOOD, "live_source": None}
    assert dashboards.resolve_live(static, store) == static


# ------------------------------------------------------------------------------------------------ API
@pytest.fixture
def client(tmp_path, monkeypatch):
    s = Store(tmp_path / "api.db")
    monkeypatch.setattr(dbmod, "_store", s)
    object.__setattr__(settings, "auto_index", False)
    from src.app.main import app
    with TestClient(app) as c:
        yield c, s


def test_dashboard_api_roundtrip(client):
    c, s = client
    assert c.get("/api/dashboard").json()["items"] == []

    r = c.post("/api/dashboard/items", json={"spec": GOOD, "source": "chat"})
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["id"] >= 1 and item["title"] == GOOD["title"] and item["spec"]["kind"] == "stacked_bar" and item["source"] == "chat"

    r2 = c.post("/api/dashboard/items", json={"spec": {**GOOD, "live_source": None, "kind": "table"}, "title": "Renamed"})
    assert r2.status_code == 200 and r2.json()["title"] == "Renamed"

    items = c.get("/api/dashboard").json()["items"]
    assert [i["id"] for i in items] == [item["id"], r2.json()["id"]]

    bad = c.post("/api/dashboard/items", json={"spec": {**GOOD, "kind": "pie"}})
    assert bad.status_code == 400 and "kind must be" in bad.json()["detail"]

    # live refresh recomputes data from the store (all 66 questions, none derived yet → all UNKNOWN)
    live = c.get(f"/api/dashboard/items/{item['id']}/live").json()
    assert live["spec"]["title"] == GOOD["title"] and live["spec"]["refreshed_at"]
    assert sum(sum(x["values"]) for x in live["spec"]["data"]["series"]) == 66
    # a static item comes back unchanged
    static = c.get(f"/api/dashboard/items/{r2.json()['id']}/live").json()
    assert static["spec"]["data"] == GOOD["data"] and "refreshed_at" not in static["spec"]

    ro = c.post("/api/dashboard/reorder", json={"ids": [r2.json()["id"], item["id"]]})
    assert [i["id"] for i in ro.json()["items"]] == [r2.json()["id"], item["id"]]

    assert c.delete(f"/api/dashboard/items/{item['id']}").json()["ok"]
    assert c.delete(f"/api/dashboard/items/{item['id']}").status_code == 404
    assert c.get(f"/api/dashboard/items/{item['id']}/live").status_code == 404
    assert [i["id"] for i in c.get("/api/dashboard").json()["items"]] == [r2.json()["id"]]

    m = c.get("/api/dashboard/metrics/tiers").json()
    assert m["name"] == "tiers" and m["spec"]["kind"] == "bar"
    assert c.get("/api/dashboard/metrics/nope").status_code == 404
