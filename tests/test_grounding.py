"""Grounding: receipts on grounded turns, the honest no-knowledge fallback, and who_to_ask. LLM is mocked."""

from __future__ import annotations

import json

import pytest

import src.app.llm as llm
from src.app.agent import grounding
from src.app.agent.loop import TOOLS, Agent
from src.app.config import settings
from src.app.store.db import Store, now


class _Delta:
    def __init__(self, index, id_, name, args):
        self.index, self.id = index, id_
        self.function = type("F", (), {"name": name, "arguments": args})()


def _tool_turn(name: str, args: dict):
    acc = llm.StreamedMessage()
    acc.add_tool_delta(_Delta(0, "call_1", name, ""))
    acc.add_tool_delta(_Delta(0, None, None, json.dumps(args)))
    return acc


def _scripted(steps: list, reply: str):
    """steps: list of (tool, args) issued one per step; then the final reply streams token by token."""

    def fake_chat_stream(messages, **kw):
        n_tool_results = sum(1 for m in messages if m.get("role") == "tool")
        if n_tool_results < len(steps):
            yield "message", _tool_turn(*steps[n_tool_results])
            return
        acc = llm.StreamedMessage()
        for tok in reply.split(" "):
            acc.content += tok + " "
            yield "delta", tok + " "
        yield "message", acc

    return fake_chat_stream


def _seed(s: Store, name: str, heading: str, text: str, control: str, attribute: str) -> int:
    doc = s.insert("documents", {"path": f"policies/{name}.docx", "name": name, "folder": "2. Policies", "ext": ".docx",
                                 "doc_type": "policy", "authority": 2, "is_template": 0, "entity": "Solsphere AI Inc.", "effective_date": "2026-07-14",
                                 "text_len": len(text), "sha": name, "summary": "", "indexed_at": now()})
    ch = s.insert("chunks", {"doc_id": doc, "idx": 0, "heading": heading, "text": text, "sha": f"{name}-0"})
    return s.insert("claims", {"doc_id": doc, "chunk_id": ch, "control": control, "attribute": attribute, "value": "yes",
                               "statement": text, "modality": "must", "authority": 2, "observed_at": "", "excerpt": text})


@pytest.fixture
def store(tmp_path, monkeypatch):
    object.__setattr__(settings, "embedding_provider", "none")
    s = Store(tmp_path / "p.db")
    # a small, varied corpus (BM25 needs more than one document for positive IDF)
    _seed(s, "Access Control Policy", "5. Authentication", "Multi-factor authentication (MFA) is required for all corporate and cloud accounts.", "mfa", "mfa_required")
    _seed(s, "HR Security Policy", "3. Awareness", "All employees complete security awareness training at onboarding and annually.", "security_training", "annual_training")
    _seed(s, "HR Security Policy 2", "4. Screening", "Background verification is performed pre-hire by a third-party provider.", "background_checks", "pre_hire")
    return s


def _run(store, fake, text, monkeypatch):
    monkeypatch.setattr(llm, "chat_stream", fake)
    agent = Agent(store, "s1", speaker="Sahil", role="CTO")
    events = list(agent.run_stream(text))
    assert events[-1]["type"] == "done", events[-1]
    return agent, events


def test_grounded_turn_has_receipts(store, monkeypatch):
    fake = _scripted([("search_evidence", {"query": "MFA multi-factor"})],
                     "MFA is required for all corporate and cloud accounts [Access Control Policy §5, 14 Jul 2026].")
    agent, events = _run(store, fake, "Is MFA enabled?", monkeypatch)
    done = events[-1]
    g = done["grounding"]
    assert g["mode"] == "grounded"
    assert g["receipts"] and g["receipts"][0]["label"] == "[Access Control Policy §5, 14 Jul 2026]"
    assert g["receipts"][0]["authority"] == 2 and g["receipts"][0]["type"] == "claim"
    assert g["uncited"] == []
    assert "fallback" not in g
    # persisted with the message meta so history reloads render the same footer
    row = store.one("SELECT meta FROM messages WHERE role='assistant' ORDER BY id DESC LIMIT 1")
    assert json.loads(row["meta"])["grounding"]["mode"] == "grounded"


def test_uncited_facts_are_partial(store, monkeypatch):
    fake = _scripted([("search_evidence", {"query": "MFA"})],
                     "MFA is required for all corporate and cloud accounts [Access Control Policy §5, 14 Jul 2026]. "
                     "Hardware security keys are issued to every engineer on their first day of employment.")
    _, events = _run(store, fake, "Is MFA enabled?", monkeypatch)
    g = events[-1]["grounding"]
    assert g["mode"] == "partial"
    assert len(g["uncited"]) == 1 and g["uncited"][0].startswith("Hardware security keys")


def test_no_knowledge_fallback(store, monkeypatch):
    fake = _scripted([("search_evidence", {"query": "wireless network monitoring rogue access point"}), ("who_to_ask", {"controls": ["wireless_security"]})],
                     "The knowledge base has no information on wireless network monitoring, so I can't draw a conclusion from company documents. "
                     "No public research is available for this. Ask: CTO. Can you tell me whether we monitor our wireless networks?")
    agent, events = _run(store, fake, "Do we monitor our wireless networks for rogue access points?", monkeypatch)
    tools = [e for e in events if e["type"] == "tool"]
    assert [t["tool"] for t in tools] == ["search_evidence", "who_to_ask"] and all(t["ok"] for t in tools)
    assert any(t["function"]["name"] == "who_to_ask" for t in TOOLS)
    g = events[-1]["grounding"]
    assert g["mode"] == "no_knowledge" and g["receipts"] == []
    fb = g["fallback"]
    assert fb["owner_role"] == "CTO" and fb["person"] is None and fb["controls"] == ["wireless_security"]
    assert fb["topic"] == "wireless network monitoring"
    assert fb["public_sources"] == [] and isinstance(fb["web_research_available"], bool)


def test_no_knowledge_infers_controls_without_tool_call(store, monkeypatch):
    fake = _scripted([("search_evidence", {"query": "backup restore test"})],
                     "The knowledge base has no information on backup restore testing, so I can't draw a conclusion from company documents.")
    _, events = _run(store, fake, "Do we test backup restores?", monkeypatch)
    g = events[-1]["grounding"]
    assert g["mode"] == "no_knowledge"
    assert g["fallback"]["owner_role"] == "CTO"  # backup_recovery → CTO, inferred from the question


def test_conversational_turn(store, monkeypatch):
    _, events = _run(store, _scripted([], "Hello! What would you like to check first?"), "hi", monkeypatch)
    assert events[-1]["grounding"]["mode"] == "conversational"


def test_who_to_ask_role_and_person(store):
    r = grounding.who_to_ask(store, ["backup_recovery"])
    assert r["owner_role"] == "CTO" and r["person"] is None and r["ask"] == "CTO"
    assert grounding.who_to_ask(store, ["unknown_control"])["owner_role"] == "CEO"

    doc = store.insert("documents", {"path": "policies/infosec.docx", "name": "Information Security Policy", "folder": "2. Policies", "ext": ".docx",
                                     "doc_type": "policy", "authority": 2, "is_template": 0, "entity": "", "effective_date": "2026-07-14",
                                     "text_len": 10, "sha": "b", "summary": "", "indexed_at": now()})
    store.insert("claims", {"doc_id": doc, "chunk_id": None, "control": "governance_program", "attribute": "security_owner", "value": "CEO",
                            "statement": "The CEO, Sahil Pugalia, acts as CISO and owns the information security programme.", "modality": "is",
                            "authority": 2, "observed_at": "", "excerpt": "The CEO, Sahil Pugalia, acts as CISO"})
    store.insert("claims", {"doc_id": doc, "chunk_id": None, "control": "roles_responsibilities", "attribute": "privacy_owner", "value": "CBO/CPO",
                            "statement": "Privacy is owned by the CBO/CPO Priyanka Choudhury.", "modality": "is",
                            "authority": 2, "observed_at": "", "excerpt": ""})
    r = grounding.who_to_ask(store, ["governance_program"])
    assert r["owner_role"] == "CEO" and r["person"] == "Sahil Pugalia" and r["ask"] == "Sahil Pugalia (CEO)"
    assert grounding.who_to_ask(store, ["privacy_program"])["person"] == "Priyanka Choudhury"
    assert grounding.who_to_ask(store, ["backup_recovery"])["person"] is None  # CTO is unnamed


def test_receipt_label_formats():
    assert grounding.receipt_label({"type": "claim", "doc": "Access Control Policy", "section": "§5", "date": "2026-07-14", "authority": 2}) == "[Access Control Policy §5, 14 Jul 2026]"
    assert grounding.receipt_label({"type": "user", "doc": "Sahil (CTO)", "date": "2026-09-05T10:00:00+00:00", "authority": 5}) == "(confirmed by Sahil (CTO), 5 Sep 2026)"
    assert grounding.receipt_label({"type": "external", "doc": "Solsphere AI - Tracxn", "url": "https://www.tracxn.com/d/companies/solsphere", "authority": 0}) == "[public: tracxn.com]"
    assert grounding.receipt_label({"type": "template", "doc": "BCP Plan", "authority": 1}) == "[BCP Plan — template — not evidence]"


def test_derive_wording():
    from src.app.engine.derive import _unknown_comment, _with_receipts

    assert _unknown_comment("CTO") == "Not covered by company documents. Ask: CTO."
    assert _unknown_comment("CTO", "Template exists.") == "Not covered by company documents. Ask: CTO. Template exists."
    ev = [{"id": "C1", "type": "claim", "authority": 2, "doc": "Backup Policy", "date": "2026-07-14"},
          {"id": "U1", "type": "user", "authority": 5, "doc": "Sahil (CTO)", "date": "2026-09-05"},
          {"id": "C2", "type": "claim", "authority": 4, "doc": "Access Review", "date": "2026-09-04"}]
    out = _with_receipts("Yes — daily automated backups.", ev)
    assert out == "Yes — daily automated backups. (confirmed by Sahil (CTO), 5 Sep 2026) [Access Review, 4 Sep 2026]"
    assert _with_receipts("Yes [Backup Policy, 14 Jul 2026].", ev) == "Yes [Backup Policy, 14 Jul 2026]."
