"""The analyst agent: a tool-using chat loop over the profile store.

The agent cannot write questionnaire answers. It can only search, read state, record attributed employee facts,
resolve conflicts, and trigger web research. Answers are derived from evidence by the engine.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..catalog.loader import get_catalog
from ..config import settings
from ..engine.derive import question_states
from ..engine.pipeline import record_user_fact, resolve_conflict
from ..engine.planner import open_items
from ..engine.search import index_for
from ..llm import chat
from ..observability import prism
from ..store.db import Store, loads, now

MAX_STEPS = 8

# Optional extra tools (e.g. dashboards) live in agent/extra_tools.py: EXTRA_TOOLS (OpenAI tool specs) and
# EXTRA_HANDLERS {name: fn(agent, **args)}. Keeps feature modules out of this file.
try:
    from .extra_tools import EXTRA_HANDLERS, EXTRA_TOOLS
except ImportError:  # pragma: no cover
    EXTRA_TOOLS, EXTRA_HANDLERS = [], {}

TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "search_evidence", "description": "Full-text search over company documents (claims + passages), employee statements and external findings. ALWAYS search before asking the employee anything.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "control": {"type": "string", "description": "optional control id to restrict claims"}, "k": {"type": "integer", "default": 8}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_question", "description": "Get the current derived state of a questionnaire question: status, answer, confidence, evidence, open slots, related conflicts.",
        "parameters": {"type": "object", "properties": {"qid": {"type": "string"}}, "required": ["qid"]}}},
    {"type": "function", "function": {"name": "find_questions", "description": "Find questionnaire questions by keyword (e.g. 'MFA', 'backup', 'background check'). Returns qid, text, status.",
        "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}}},
    {"type": "function", "function": {"name": "list_open_items", "description": "Prioritised list of unanswered / conflicted questions with the suggested next question for the employee and why it matters.",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "default": 8}}}}},
    {"type": "function", "function": {"name": "list_conflicts", "description": "List open conflicts between sources.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "record_user_fact", "description": "Record a fact the employee just stated (attributed to them). Use one call per atomic fact. Supersedes an earlier statement on the same control+attribute. Triggers re-derivation of affected questions.",
        "parameters": {"type": "object", "properties": {"control": {"type": "string", "description": "control id"}, "attribute": {"type": "string", "description": "snake_case slot/attribute name"}, "value": {"type": "string", "description": "short normalised value"}, "statement": {"type": "string", "description": "one self-contained sentence"}, "qids": {"type": "array", "items": {"type": "string"}, "description": "question ids this answers (optional)"}}, "required": ["control", "attribute", "value", "statement"]}}},
    {"type": "function", "function": {"name": "resolve_conflict", "description": "Mark a conflict resolved with the employee's explanation (after recording the underlying fact with record_user_fact).",
        "parameters": {"type": "object", "properties": {"conflict_id": {"type": "integer"}, "resolution": {"type": "string"}}, "required": ["conflict_id", "resolution"]}}},
    {"type": "function", "function": {"name": "web_research", "description": "Run outside-in research on the public web via Tavily. Modes: live_probe (TLS/headers/security.txt of our domain), entity_facts, public_pages, attestations, breach_history, fourth_party, summary, all.",
        "parameters": {"type": "object", "properties": {"mode": {"type": "string"}}, "required": ["mode"]}}},
    {"type": "function", "function": {"name": "get_score", "description": "Buyer's-eye view: vendor criticality, predicted inherent/residual risk points, predicted escalations, missing documents, fix-first list.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "who_to_ask", "description": "When the company documents hold nothing on a topic: map the relevant control ids to the owner role (from the catalog) and, if the documents name a person for that role, the name. Call this before telling the employee who can answer.",
        "parameters": {"type": "object", "properties": {"controls": {"type": "array", "items": {"type": "string"}, "description": "control ids the question is about"}}, "required": ["controls"]}}},
]

SYSTEM = """You are the AI Security Analyst for {vendor} (brand: {brand}). You are talking to {speaker}, whose role is {role}.
Your job: complete the buyer's 66-question vendor security questionnaire truthfully, with evidence, by (1) searching the
company's own documents first, (2) asking the employee only what documents cannot answer, (3) detecting and resolving
contradictions, and (4) remembering everything said.

Rules you never break:
- SEARCH BEFORE ASKING. Call search_evidence / get_question before asking the employee anything.
- NEVER MAKE UP AN ANSWER. If evidence is missing, say so and ask. If sources conflict, present both sides and ask one precise clarifying question.
- RECEIPTS. Every confident factual statement carries an inline receipt, in exactly one of these fixed formats (take names, sections and dates from the tool results; never invent them):
    document ........ [Access Control Policy §5, 14 Jul 2026]   (document name + section/row when known + document date)
    employee ........ (confirmed by Sahil (CTO), 5 Sep 2026)      (speaker (role), date of the statement)
    public web ...... [public: tracxn.com]                        (always labelled as public information, never as company fact)
    template ........ [BCP Plan — template — not evidence]        (an unfilled template is never the basis for a fact)
  A sentence without a receipt is a question or your own suggestion, never a fact. Templates (unfilled documents) are not evidence; say so if relevant.
- KNOWLEDGE GAP. When the documents hold nothing relevant (search_evidence returned nothing useful and get_question shows UNKNOWN / no evidence), do not improvise. Your reply must: (a) say plainly "The knowledge base has no information on <topic>, so I can't draw a conclusion from company documents."; (b) {web_hint}; (c) call who_to_ask with the relevant control ids and name who can answer as "Ask: <person> (<role>)" or the role alone; then ask the employee whether they can answer it now.
- Ask ONE question at a time. Prefer the highest-priority open item unless the employee steers elsewhere. Explain in one clause why it matters (buyer criticality / risk points / conflict).
- Don't accept vague answers when a slot needs detail: "Yes" to backups → ask frequency, automation, encryption, restore test — one at a time.
- When the employee states a fact, IMMEDIATELY record it with record_user_fact (one call per atomic fact; control ids from the catalog; short attribute names). If it resolves a listed conflict, also call resolve_conflict. Then confirm back what you recorded in one line.
- If the employee corrects something earlier, record the new fact (it supersedes) and acknowledge the correction.
- Distinguish clearly: verified from documents / confirmed by employee / unknown.
- Keep replies compact: 2-6 sentences plus at most one question. Use plain language; the employee may not be a security specialist.
- When asked "how are we doing" or about the buyer's view, call get_score and summarise: predicted rating, escalations, top fixes.

Control ids available: {controls}

Current snapshot: {snapshot}"""


def _snapshot(store: Store) -> str:
    states = question_states(store)
    counts: dict[str, int] = {}
    for s in states:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    items = open_items(store)[:5]
    top = "; ".join(f"Q{i['qid']} [{i['status']}] {i['question'][:90]}" for i in items)
    sc = store.kv_get("last_score") or {}
    return (f"status counts {counts}; predicted buyer rating {sc.get('predicted_rating', 'n/a')} "
            f"({sc.get('inherent_points', 0)}/{sc.get('max_inherent_points', 0)} inherent pts, {len(sc.get('escalations', []))} predicted escalations); "
            f"top open items: {top or 'none'}")


class Agent:
    def __init__(self, store: Store, session: str, speaker: str = "Employee", role: str = "CTO"):
        self.store, self.session, self.speaker, self.role = store, session, speaker, role
        self.updated_qids: set[str] = set()
        self.evidence: list[dict] = []
        self.events: list[dict] = []
        self.visuals: list[dict] = []   # chart specs proposed during the turn (see extra_tools)
        self.extras: dict = {}          # any other structured payload a feature wants in the done event
        self.asked: dict | None = None  # last who_to_ask result this turn (see grounding)
        self.user_text: str = ""
        self._started: float = 0.0

    # ---- tool implementations
    def t_search_evidence(self, query: str, control: str | None = None, k: int = 8):
        hits = index_for(self.store).search(query, k=k, control=control or None)
        for h in hits:
            if h["type"] in ("claim", "user", "external"):
                # the index spreads the row over its own id, so a claim comes back as 1 rather than "C1": re-prefix
                hid = str(h["id"])
                if hid.isdigit():
                    hid = {"claim": "C", "user": "U", "external": "X"}[h["type"]] + hid
                self.evidence.append({"id": hid, "type": "template" if h.get("is_template") else h["type"], "doc": h.get("doc") or h.get("speaker") or h.get("title"),
                                      "date": h.get("observed_at") or h.get("created_at") or h.get("published_at") or "", "control": h.get("control"),
                                      "statement": h.get("statement") or h.get("snippet", ""), "authority": h.get("authority"), "excerpt": h.get("excerpt") or h.get("url", "")})
        return [{k_: v for k_, v in h.items() if k_ not in ("text",)} | ({"text": h["text"][:600]} if "text" in h else {}) for h in hits]

    def t_get_question(self, qid: str):
        qid = str(qid).replace("Q", "").split(".")[0]
        s = next((x for x in question_states(self.store) if x["qid"] == qid), None)
        if not s:
            return {"error": f"unknown qid {qid}"}
        from ..engine.conflicts import open_conflicts_for
        s["conflicts"] = [{"id": c["id"], "description": c["description"], "question_to_ask": c["question_to_ask"], "severity": c["severity"]} for c in open_conflicts_for(self.store, s["controls"])]
        for ev in s["evidence"]:
            self.evidence.append(ev)
        return s

    def t_find_questions(self, keyword: str):
        kw = keyword.lower()
        return [{"qid": s["qid"], "text": s["text"], "status": s["status"], "controls": s["controls"]} for s in question_states(self.store)
                if kw in s["text"].lower() or any(kw in c for c in s["controls"]) or kw in s["topic"].lower()][:12]

    def t_list_open_items(self, limit: int = 8):
        return open_items(self.store, self.role)[:limit]

    def t_list_conflicts(self):
        rows = self.store.q("SELECT id, control, attribute, description, question_to_ask, resolution FROM conflicts WHERE status='open'")
        for r in rows:
            r["severity"] = (loads(r.pop("resolution"), {}) or {}).get("severity", "medium")
        return rows

    def t_record_user_fact(self, control: str, attribute: str, value: str, statement: str, qids: list[str] | None = None):
        cat = get_catalog()
        if control not in cat.controls:
            return {"error": f"unknown control '{control}'. Use one of: {', '.join(cat.control_ids())}"}
        r = record_user_fact(self.store, control=control, attribute=attribute, value=value, statement=statement,
                             speaker=self.speaker, role=self.role, qids=[str(q) for q in (qids or [])] or None)
        self.updated_qids.update(r["affected_qids"])
        return r

    def t_resolve_conflict(self, conflict_id: int, resolution: str):
        r = resolve_conflict(self.store, int(conflict_id), resolution, f"{self.speaker} ({self.role})")
        self.updated_qids.update(r["affected_qids"])
        return r

    def t_web_research(self, mode: str):
        from ..research import outside_in as oi
        if mode == "all":
            res = oi.run_all(self.store)
        elif mode in oi.MODES:
            res = oi.MODES[mode](self.store)
        else:
            return {"error": f"unknown mode {mode}"}
        self.updated_qids.update(s["qid"] for s in question_states(self.store) if s["updated_at"] and s["updated_at"] >= now()[:16])
        return json.loads(json.dumps(res, default=str))[:20] if isinstance(res, list) else json.loads(json.dumps(res, default=str))

    def t_get_score(self):
        from ..engine.scorer import score
        sc = score(self.store)
        return {k: sc[k] for k in ("vendor_criticality", "inherent_points", "max_inherent_points", "residual_points", "predicted_rating", "counts")} | {
            "escalations": sc["escalations"][:10], "fix_first": sc["fix_first"][:6], "documents": sc["documents"]}

    def t_who_to_ask(self, controls: list[str] | None = None):
        from .grounding import who_to_ask
        self.asked = who_to_ask(self.store, [str(c) for c in (controls or [])])
        return self.asked

    # ---- loop
    def _history(self, limit: int = 30) -> list[dict]:
        rows = self.store.q("SELECT role, content FROM messages WHERE session=? ORDER BY id DESC LIMIT ?", (self.session, limit))
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    TOOL_LABEL = {
        "search_evidence": "Searching company documents", "get_question": "Reading question state", "find_questions": "Finding related questions",
        "list_open_items": "Prioritising open items", "list_conflicts": "Checking conflicts", "record_user_fact": "Recording your statement",
        "resolve_conflict": "Resolving conflict", "web_research": "Researching the public web", "get_score": "Computing buyer's-eye score",
        "who_to_ask": "Working out who owns this", "get_metrics": "Gathering the numbers", "propose_visual": "Drawing a chart",
        "who_to_ask": "Finding who to ask",
    }

    def _exec_tool(self, name: str, raw_args: str) -> tuple[dict, Any]:
        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError:
            args = {}
        fn = getattr(self, f"t_{name}", None)
        try:
            if fn is None and name in EXTRA_HANDLERS:
                result = EXTRA_HANDLERS[name](self, **args)
            else:
                result = fn(**args) if fn else {"error": f"unknown tool {name}"}
        except Exception as e:  # noqa: BLE001
            result = {"error": str(e)}
        ok = not (isinstance(result, dict) and result.get("error"))
        self.events.append({"tool": name, "args": args, "ok": ok})
        return {"tool": name, "args": args, "ok": ok}, result

    def _finish(self, reply: str) -> dict:
        reply = reply.strip() or "I couldn't produce a reply. Please try again."
        seen, ev = set(), []
        for e in self.evidence:
            if e.get("id") and e["id"] not in seen:
                seen.add(e["id"])
                ev.append(e)
        # Receipts + grounding mode ride the done event with the other extras (see grounding.py).
        try:
            from .grounding import build_grounding
            self.extras["grounding"] = build_grounding(self, reply, self.user_text)
        except Exception as e:  # noqa: BLE001 - grounding must never break a reply
            self.store.log("grounding_error", str(e))
            self.extras.setdefault("grounding", {"mode": "conversational", "receipts": [], "uncited": []})
        out = {"reply": reply, "evidence": ev[:12], "events": self.events, "updated_qids": sorted(self.updated_qids, key=float),
               "visuals": self.visuals, **self.extras}
        self.store.insert("messages", {"session": self.session, "role": "assistant", "content": reply,
                                       "meta": json.dumps({k: v for k, v in out.items() if k != "reply"}), "created_at": now()})
        # The whole turn as an ordered trajectory, so PRISM can evaluate whether the analyst searched
        # before it asked and whether the reply it landed on was actually grounded.
        prism.submit_trajectory(session=self.session, user_text=self.user_text, reply=reply, events=self.events,
                                grounding=self.extras.get("grounding"),
                                duration_ms=int((time.time() - self._started) * 1000) if self._started else 0)
        return out

    def run_stream(self, user_text: str):
        """Generator of events: status / tool / delta / done / error. Tokens of the final reply stream as they arrive."""
        from ..llm import chat_stream

        self.user_text = user_text
        self._started = time.time()
        self.store.insert("messages", {"session": self.session, "role": "user", "content": user_text, "meta": "", "created_at": now()})
        cat = get_catalog()
        web_hint = ("if it helps, call web_research and report what the public web says with [public: domain] receipts, labelled explicitly as public information, not company fact"
                    if settings.tavily_api_key else
                    "if public findings (X#) already exist, report them with [public: domain] receipts, labelled explicitly as public information, not company fact; otherwise say that no public research is available")
        system = (SYSTEM.replace("{vendor}", settings.vendor_legal_name).replace("{brand}", settings.vendor_brand)
                  .replace("{speaker}", self.speaker).replace("{role}", self.role).replace("{web_hint}", web_hint)
                  .replace("{controls}", ", ".join(cat.control_ids())).replace("{snapshot}", _snapshot(self.store)))
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *self._history()]
        reply = ""
        try:
            for step in range(MAX_STEPS):
                yield {"type": "status", "text": "Thinking…" if step == 0 else "Composing answer…"}
                streamed = ""
                acc = None
                for kind, payload in chat_stream(messages, model=settings.model_agent, tools=TOOLS + EXTRA_TOOLS, max_tokens=1500, temperature=0.3):
                    if kind == "delta":
                        streamed += payload
                        yield {"type": "delta", "text": payload}
                    else:
                        acc = payload
                if acc is None or not acc.tool_calls:
                    reply = streamed
                    break
                # The model asked for tools: any text it streamed alongside is interim; tell the UI to reset it.
                if streamed:
                    yield {"type": "reset"}
                messages.append({"role": "assistant", "content": acc.content or "", "tool_calls": [
                    {"id": tc["id"] or f"call_{i}", "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}} for i, tc in enumerate(acc.tool_calls)]})
                for i, tc in enumerate(acc.tool_calls):
                    yield {"type": "status", "text": self.TOOL_LABEL.get(tc["name"], tc["name"]) + "…"}
                    ev, result = self._exec_tool(tc["name"], tc["arguments"])
                    yield {"type": "tool", **ev}
                    messages.append({"role": "tool", "tool_call_id": tc["id"] or f"call_{i}", "content": json.dumps(result, default=str)[:12000]})
            else:
                reply = reply or "I've used all my research steps for this turn. Here is what I have so far — ask me to continue if needed."
                yield {"type": "delta", "text": reply}
            out = self._finish(reply)
            yield {"type": "done", **{k: v for k, v in out.items() if k != "reply"}, "reply": out["reply"]}
        except Exception as e:  # noqa: BLE001
            self.store.log("agent_error", str(e))
            yield {"type": "error", "text": str(e)}

    def run(self, user_text: str) -> dict:
        """Non-streaming wrapper (drains the stream)."""
        final: dict = {}
        for ev in self.run_stream(user_text):
            if ev["type"] == "done":
                final = ev
            elif ev["type"] == "error":
                raise RuntimeError(ev["text"])
        return {"reply": final.get("reply", ""), "evidence": final.get("evidence", []), "events": final.get("events", []), "updated_qids": final.get("updated_qids", [])}
