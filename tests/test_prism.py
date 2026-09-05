"""PRISM observability: tagging, the guardrail-override trace, trajectories, and safe no-op.

The point of these tests is not that telemetry is wired up. It is that the *specific* event the
product's central claim rests on — the engine overruling the model when the evidence does not
support it — is detected and recorded, including when the model invents a citation.
"""

from __future__ import annotations

import pytest

from src.app.catalog.loader import get_catalog, seed_questions
from src.app.config import settings
from src.app.engine import derive as derive_mod
from src.app.observability import prism
from src.app.store.db import Store, now


@pytest.fixture(autouse=True)
def _reset_prism(monkeypatch):
    """Every test starts with clean counters and PRISM switched off unless it says otherwise."""
    with prism._lock:
        for k in prism._counters:
            prism._counters[k] = 0
        prism._recent.clear()
        prism._trajectories.clear()
    monkeypatch.setattr(prism, "_client", None)
    object.__setattr__(settings, "prism_api_key", "")
    object.__setattr__(settings, "prism_project_id", "")
    yield


class FakeClient:
    """Stands in for PRISMtrace so tests assert on payloads instead of hitting the network."""

    def __init__(self):
        self.traces: list[dict] = []
        self.trajectories: list[dict] = []

    def trace_llm(self, **kw):
        self.traces.append(kw)

    def submit_trajectory(self, **kw):
        self.trajectories.append(kw)
        return {"id": "traj_1"}

    def flush(self, timeout=2.0):
        pass


@pytest.fixture
def prism_on(monkeypatch):
    fake = FakeClient()
    object.__setattr__(settings, "prism_api_key", "test-key")
    object.__setattr__(settings, "prism_project_id", "test-project")
    monkeypatch.setattr(prism, "_client", fake)
    return fake


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "p.db")
    seed_questions(s)
    return s


def _add_claim(s: Store, control: str, statement: str, authority: int = 2, is_template: int = 0) -> int:
    doc_id = s.insert("documents", {"path": f"/x/{control}.docx", "name": "Access Control Policy", "folder": "2. Company policies",
                                    "ext": ".docx", "doc_type": "policy", "authority": authority, "is_template": is_template,
                                    "entity": "Solsphere AI Inc.", "effective_date": "2026-07-14", "text_len": 100,
                                    "sha": control, "summary": "", "indexed_at": now()})
    return s.insert("claims", {"doc_id": doc_id, "chunk_id": None, "control": control, "attribute": "exists", "value": "yes",
                               "statement": statement, "modality": "asserted", "authority": authority,
                               "observed_at": "2026-07-14", "excerpt": statement})


# --------------------------------------------------------------------------- no-op safety


def test_unconfigured_prism_never_raises_and_records_skip():
    prism.trace_llm(model="m", messages=[{"role": "user", "content": "hi"}], output="ok", latency_ms=5)
    h = prism.health()
    assert h["configured"] is False
    assert h["counters"]["skipped"] == 1 and h["counters"]["traces"] == 0


def test_step_tags_are_attached_to_traces(prism_on):
    with prism.step("derive", qid="12", topic="Data Security"):
        prism.trace_llm(model="m", messages=[{"role": "user", "content": "hi"}], output="ok", latency_ms=5)
    meta = prism_on.traces[0]["metadata"]
    assert meta["phase"] == "derive" and meta["qid"] == "12" and meta["topic"] == "Data Security"


def test_step_tags_do_not_leak_out_of_the_block(prism_on):
    with prism.step("derive", qid="12"):
        pass
    prism.trace_llm(model="m", messages=[], output="ok", latency_ms=1)
    assert "qid" not in prism_on.traces[0]["metadata"]


def test_image_payloads_are_not_traced(prism_on):
    messages = [{"role": "user", "content": [{"type": "text", "text": "describe"},
                                             {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
    prism.trace_llm(model="m", messages=messages, output="a diagram", latency_ms=5)
    sent = prism_on.traces[0]["input_messages"][0]["content"]
    assert "describe" in sent and "base64" not in sent


# --------------------------------------------------------------------------- the guardrail trace


def _fake_model(response: str, answer_value: str, evidence_ids: list[str]):
    def call(system, user, **kw):
        return {"response": response, "comments": "", "answer_value": answer_value,
                "slot_assessment": {}, "evidence_ids": evidence_ids, "next_question": "", "notes_for_analyst": ""}
    return call


def test_fabricated_citation_is_dropped_and_traced_as_an_override(store, prism_on, monkeypatch):
    """The Delve case, in a unit test: the model says Yes and cites evidence that does not exist."""
    _add_claim(store, "encryption_at_rest", "Data at rest is encrypted with AES-256.")
    monkeypatch.setattr(derive_mod, "json_call", _fake_model("Yes, AES-256.", "Yes", ["C9999"]))

    q = get_catalog().questions["20"]  # data-at-rest encryption
    row = derive_mod.derive_question(store, q)

    assert row["status"] == "UNKNOWN", "an answer citing nothing real cannot be verified"
    assert row["answer"] == "Unknown — needs confirmation"
    assert row["confidence"] == 0.0
    assert prism.health()["counters"]["overrides"] == 1
    override = next(r for r in prism.health()["recent"] if r["kind"] == "overrides")
    assert override["model_answer"] == "Yes"
    assert override["final_status"] == "UNKNOWN"
    assert "C9999" in override["dropped_evidence_ids"]
    assert any("C9999" in r for r in override["reasons"])


def test_real_citation_is_kept_and_no_override_is_recorded(store, prism_on, monkeypatch):
    cid = _add_claim(store, "encryption_at_rest", "Data at rest is encrypted with AES-256.")
    monkeypatch.setattr(derive_mod, "json_call", _fake_model("Yes, AES-256.", "Yes", [f"C{cid}"]))

    row = derive_mod.derive_question(store, get_catalog().questions["20"])

    assert row["status"] in ("VERIFIED", "PARTIAL")
    assert row["evidence"] and row["evidence"][0]["id"] == f"C{cid}"
    assert prism.health()["counters"]["overrides"] == 0, "a properly cited answer is not an override"


def test_template_only_evidence_is_an_override(store, prism_on, monkeypatch):
    """An unfilled template is not proof that a control exists."""
    cid = _add_claim(store, "encryption_at_rest", "Data at rest is encrypted with [ALGORITHM].", authority=1, is_template=1)
    monkeypatch.setattr(derive_mod, "json_call", _fake_model("Yes.", "Yes", [f"C{cid}"]))

    row = derive_mod.derive_question(store, get_catalog().questions["20"])

    assert row["status"] == "UNKNOWN"
    assert prism.health()["counters"]["overrides"] == 1


def test_override_trace_reaches_prism_with_override_flag(store, prism_on, monkeypatch):
    _add_claim(store, "encryption_at_rest", "Data at rest is encrypted with AES-256.")
    monkeypatch.setattr(derive_mod, "json_call", _fake_model("Yes.", "Yes", ["C4242"]))
    derive_mod.derive_question(store, get_catalog().questions["20"])

    guard = [t for t in prism_on.traces if t["metadata"].get("phase") == "guardrail"]
    assert len(guard) == 1
    assert guard[0]["metadata"]["override"] is True
    assert guard[0]["model"] == "guardrail:engine.derive"


# --------------------------------------------------------------------------- trajectories


def test_trajectory_maps_tools_to_steps_and_grounding_to_status(prism_on):
    prism.submit_trajectory(
        session="s1", user_text="Do we have MFA?", reply="Yes [Access Control Policy §4, 14 Jul 2026]",
        events=[{"tool": "search_evidence", "args": {"query": "mfa"}, "ok": True},
                {"tool": "get_question", "args": {"qid": "60"}, "ok": True}],
        grounding={"mode": "grounded", "receipts": [{"id": "C1"}], "uncited": []}, duration_ms=1200)

    t = prism_on.trajectories[0]
    assert t["conversation_id"] == "s1"
    assert [s["tool_name"] for s in t["steps"] if s["step_type"] == "tool_call"] == ["search_evidence", "get_question"]
    assert t["steps"][-1]["step_type"] == "final_answer"
    assert t["final_status"] == "success"


def test_ungrounded_turn_is_reported_as_a_failed_trajectory(prism_on):
    prism.submit_trajectory(session="s2", user_text="Do we do background checks?", reply="Yes, annually.",
                            events=[], grounding={"mode": "no_knowledge", "receipts": [], "uncited": ["Yes, annually."]})
    assert prism_on.trajectories[0]["final_status"] == "failure"


def test_failed_tool_call_is_marked_error_in_the_trajectory(prism_on):
    prism.submit_trajectory(session="s3", user_text="x", reply="y",
                            events=[{"tool": "web_research", "args": {}, "ok": False}],
                            grounding={"mode": "grounded", "receipts": [], "uncited": []})
    assert prism_on.trajectories[0]["steps"][0]["status"] == "error"


def test_client_failure_does_not_break_the_caller(monkeypatch):
    object.__setattr__(settings, "prism_api_key", "k")
    object.__setattr__(settings, "prism_project_id", "p")

    class Boom:
        def trace_llm(self, **kw):
            raise RuntimeError("prism is down")

    monkeypatch.setattr(prism, "_client", Boom())
    prism.trace_llm(model="m", messages=[], output="o", latency_ms=1)  # must not raise
    assert prism.health()["counters"]["failed"] == 1
