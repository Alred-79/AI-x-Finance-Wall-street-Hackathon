"""Streaming agent loop with a mocked LLM: tool call turn → final streamed answer, over SSE."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.app.llm as llm
from src.app.api import routes
from src.app.config import settings
from src.app.store import db as dbmod
from src.app.store.db import Store


class _Delta:
    def __init__(self, index, id_, name, args):
        self.index, self.id = index, id_
        self.function = type("F", (), {"name": name, "arguments": args})()


def fake_chat_stream(messages, **kw):
    has_tool_result = any(m.get("role") == "tool" for m in messages)
    acc = llm.StreamedMessage()
    if not has_tool_result:
        acc.add_tool_delta(_Delta(0, "call_1", "search_evidence", ""))
        acc.add_tool_delta(_Delta(0, None, None, json.dumps({"query": "MFA multi-factor"})))
        yield "message", acc
        return
    for tok in ["MFA ", "is **required** ", "per the Access Control Policy."]:
        acc.content += tok
        yield "delta", tok
    yield "message", acc


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "chat_stream", fake_chat_stream)
    s = Store(tmp_path / "p.db")
    monkeypatch.setattr(dbmod, "_store", s)
    object.__setattr__(settings, "openrouter_api_key", "test-key")
    from src.app.main import app
    with TestClient(app) as c:
        yield c
    object.__setattr__(settings, "openrouter_api_key", "")


def test_stream_events(client):
    with client.stream("POST", "/api/chat/stream", json={"session": "t1", "message": "Is MFA enabled?", "speaker": "Sam", "role": "CTO"}) as r:
        assert r.status_code == 200
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    types = [e["type"] for e in events]
    assert "tool" in types and "delta" in types and types[-1] == "done"
    tool = next(e for e in events if e["type"] == "tool")
    assert tool["tool"] == "search_evidence" and tool["args"]["query"] == "MFA multi-factor"
    done = events[-1]
    assert done["reply"] == "MFA is **required** per the Access Control Policy."
    assert done["events"][0]["tool"] == "search_evidence"
    hist = client.get("/api/chat/t1").json()
    assert [h["role"] for h in hist] == ["user", "assistant"]
    assert hist[1]["meta"]["events"][0]["tool"] == "search_evidence"
