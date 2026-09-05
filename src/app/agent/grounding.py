"""Grounding: "we have the receipts", and an honest knowledge-gap fallback.

Receipt label formats (fixed; the SYSTEM prompt asks the model for the same strings):
  document            [Access Control Policy §5, 14 Jul 2026]
  employee statement  (confirmed by Sahil (CTO), 5 Sep 2026)
  public web          [public: tracxn.com]
  template            [BCP Plan — template — not evidence]

After each turn `build_grounding` turns the evidence the agent touched into ranked receipts and classifies the
reply: grounded / partial / no_knowledge / conversational. In the no_knowledge case it also names who to ask.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from ..catalog.loader import get_catalog
from ..store.db import Store

if TYPE_CHECKING:  # pragma: no cover
    from .loop import Agent

FALLBACK_PHRASE = "The knowledge base has no information on {topic}, so I can't draw a conclusion from company documents."

ROLE_ALIASES = {
    "CEO": ["CEO", "Chief Executive Officer"],
    "CTO": ["CTO", "Chief Technology Officer", "Chief Technical Officer"],
    "CBO": ["CBO", "Chief Business Officer", "CPO", "Chief Product Officer", "Chief Privacy Officer"],
    "CPO": ["CPO", "Chief Product Officer", "Chief Privacy Officer", "CBO"],
    "CISO": ["CISO", "Chief Information Security Officer"],
}
PERSON_CONTROLS = ("roles_responsibilities", "company_profile", "governance_program")
_NAME = r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}"
_NAME_STOP = {"Chief", "Executive", "Officer", "Technology", "Technical", "Business", "Product", "Privacy", "Information", "Security",
              "The", "Acting", "Inc", "Ai", "AI", "Solsphere", "Regodit", "Policy", "Company", "Board", "Founder", "Team", "Owner"}

# Tools whose output is system state (scores, open items), not a company-document fact: nothing to receipt.
SYSTEM_TOOLS = {"get_score", "list_open_items", "list_conflicts", "find_questions", "who_to_ask"}
RECORD_TOOLS = {"record_user_fact", "resolve_conflict"}

_RECEIPT = re.compile(r"\[[^\[\]\n]{3,120}\]|\(confirmed by [^)\n]{2,80}\)", re.I)
_LEAD_WORDS = set("hey hi hello please can could would will you tell me about do does did is are was were have has had we our the company "
                  "there it what which when where who how why often many much any a an in at of for use perform run currently actually "
                  "your my us i".split())
_TRAIL_WORDS = set("please today currently right now then".split())


# ---------------------------------------------------------------- receipts

def fmt_date(raw: str | None) -> str:
    """'2026-07-14' → '14 Jul 2026'; ISO timestamps too; anything else is passed through (first 10 chars)."""
    if not raw:
        return ""
    s = str(raw).strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return f"{d.day} {d.strftime('%b %Y')}"
    except ValueError:
        return s[:10]


def _section(heading: str | None) -> str:
    if not heading:
        return ""
    h = heading.strip()
    m = re.match(r"^\s*(?:section|sec\.?|§|row|clause|article)?\s*(\d+(?:\.\d+)*)\b", h, re.I)
    if m:
        return f"§{m.group(1)}"
    return h[:40] if len(h) <= 40 else h[:37].rstrip() + "…"


def receipt_label(e: dict) -> str:
    """The fixed inline label for one evidence item (claim / template / user / external)."""
    typ = e.get("type") or "claim"
    auth = e.get("authority")
    doc = (e.get("doc") or e.get("title") or e.get("speaker") or "").strip()
    date = fmt_date(e.get("date") or e.get("observed_at") or e.get("effective_date") or e.get("created_at") or e.get("published_at"))
    if typ == "user" or auth == 5:
        return f"(confirmed by {doc}{', ' + date if date else ''})"
    if typ == "external" or auth == 0:
        url = e.get("url") or e.get("excerpt") or ""
        host = urlparse(url).netloc.replace("www.", "") if "://" in str(url) else ""
        return f"[public: {host or doc or 'web'}]"
    if typ == "template" or auth == 1 or e.get("is_template"):
        return f"[{doc or 'document'} — template — not evidence]"
    sec = e.get("section") or ""
    return f"[{doc or 'document'}{' ' + sec if sec else ''}{', ' + date if date else ''}]"


def _hydrate(store: Store, ids: list[str]) -> dict[str, dict]:
    """Look every touched evidence id up in the store so receipts carry doc, section, date and authority."""
    out: dict[str, dict] = {}
    cids = [i[1:] for i in ids if i.startswith("C") and i[1:].isdigit()]
    uids = [i[1:] for i in ids if i.startswith("U") and i[1:].isdigit()]
    xids = [i[1:] for i in ids if i.startswith("X") and i[1:].isdigit()]
    if cids:
        ph = ",".join("?" for _ in cids)
        for c in store.q(f"SELECT c.id, c.authority, c.statement, c.excerpt, c.observed_at, c.control, d.name AS doc, d.doc_type, d.is_template, "
                         f"d.effective_date, ch.heading FROM claims c JOIN documents d ON d.id=c.doc_id LEFT JOIN chunks ch ON ch.id=c.chunk_id "
                         f"WHERE c.id IN ({ph})", cids):
            tmpl = bool(c.get("is_template")) or c.get("authority") == 1
            out[f"C{c['id']}"] = {"id": f"C{c['id']}", "type": "template" if tmpl else "claim", "authority": 1 if tmpl else c["authority"],
                                  "doc": c["doc"], "doc_type": c.get("doc_type"), "control": c.get("control"), "section": _section(c.get("heading")),
                                  "date": c.get("observed_at") or c.get("effective_date") or "", "statement": c.get("statement") or "",
                                  "excerpt": c.get("excerpt") or ""}
    if uids:
        ph = ",".join("?" for _ in uids)
        for u in store.q(f"SELECT id, speaker, role, statement, created_at, control FROM user_statements WHERE id IN ({ph})", uids):
            out[f"U{u['id']}"] = {"id": f"U{u['id']}", "type": "user", "authority": 5, "doc": f"{u['speaker']} ({u['role']})", "doc_type": "interview",
                                  "control": u.get("control"), "section": "", "date": u["created_at"], "statement": u["statement"], "excerpt": ""}
    if xids:
        ph = ",".join("?" for _ in xids)
        for x in store.q(f"SELECT id, kind, url, title, snippet, published_at, control FROM external_findings WHERE id IN ({ph})", xids):
            out[f"X{x['id']}"] = {"id": f"X{x['id']}", "type": "external", "authority": 0, "doc": x["title"], "doc_type": x["kind"], "control": x.get("control"),
                                  "section": "", "date": x.get("published_at") or "", "statement": (x.get("snippet") or "")[:300], "excerpt": x["url"], "url": x["url"]}
    return out


def build_receipts(store: Store, evidence: list[dict]) -> list[dict]:
    """Dedupe the evidence touched this turn, hydrate from the store, label, rank by authority desc."""
    seen: list[str] = []
    for e in evidence:
        i = str(e.get("id") or "")
        if i.isdigit():  # bare row id: prefix by type
            i = {"claim": "C", "template": "C", "user": "U", "external": "X"}.get(e.get("type") or "claim", "C") + i
        if i and i not in seen:
            seen.append(i)
    if not seen:
        return []
    rows = _hydrate(store, seen)
    out = []
    for i in seen:
        r = rows.get(i)
        if r is None:  # not in the store any more: fall back to what the tool returned
            src = next(e for e in evidence if str(e.get("id")) == i)
            r = {"id": i, "type": src.get("type") or "claim", "authority": src.get("authority"), "doc": src.get("doc") or "", "section": "",
                 "date": src.get("date") or "", "statement": src.get("statement") or "", "excerpt": src.get("excerpt") or ""}
        r["label"] = receipt_label(r)
        out.append(r)
    out.sort(key=lambda r: (-(r.get("authority") if r.get("authority") is not None else 2), int(re.sub(r"\D", "", r["id"]) or 0)))
    return out


# ---------------------------------------------------------------- who to ask

def _find_person(store: Store, role: str) -> str | None:
    aliases = ROLE_ALIASES.get(role.upper(), [role])
    alt = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    role_re = rf"(?:{alt})(?:\s*/\s*[A-Z]{{2,5}})?"
    pats = [
        re.compile(rf"\b{role_re}\b[:,]?\s*(?:is|—|–|-)?\s*({_NAME})"),          # "CEO Sahil Pugalia", "CEO: X", "CEO, X", "CEO is X"
        re.compile(rf"({_NAME})\s*[\(,–—-]\s*(?:acting\s+|and\s+)?{role_re}\b"),   # "Sahil Pugalia (CEO", "Sahil Pugalia, CEO"
    ]
    ph = ",".join("?" for _ in PERSON_CONTROLS)
    texts: list[str] = []
    for c in store.q(f"SELECT statement, excerpt, value FROM claims WHERE control IN ({ph}) ORDER BY authority DESC, id", list(PERSON_CONTROLS)):
        texts += [c.get("statement") or "", c.get("excerpt") or "", c.get("value") or ""]
    for u in store.q(f"SELECT statement FROM user_statements WHERE control IN ({ph}) ORDER BY id DESC", list(PERSON_CONTROLS)):
        texts.append(u.get("statement") or "")
    for t in texts:
        if not t or not any(a.lower() in t.lower() for a in aliases):
            continue
        for p in pats:
            for m in p.finditer(t):
                name = re.sub(r"\s+", " ", m.group(1)).strip()
                words = name.split()
                if 2 <= len(words) <= 3 and not any(w in _NAME_STOP for w in words):
                    return name
    return None


def who_to_ask(store: Store, controls: list[str] | None) -> dict:
    """Map controls → owner role from the catalog, and the named person for that role when the documents name one."""
    cat = get_catalog()
    ids = [c for c in (controls or []) if c in cat.controls]
    roles: list[str] = []
    for c in ids:
        r = cat.controls[c].get("owner_role", "CEO")
        if r not in roles:
            roles.append(r)
    role = roles[0] if roles else "CEO"
    person = _find_person(store, role)
    return {
        "controls": ids, "owner_role": role, "roles": roles or [role], "person": person,
        "ask": f"{person} ({role})" if person else role,
        "note": "Control owner from the catalog" + ("; named in the company documents." if person else "; the documents do not name this person — ask by role."),
    }


# ---------------------------------------------------------------- classification

def _sentences(reply: str) -> list[str]:
    text = re.sub(r"`[^`]*`", "", reply)
    out: list[str] = []
    for block in re.split(r"\n+", text):
        block = re.sub(r"^\s*(?:[-*•]|\d+[.)]|#+)\s*", "", block).strip()
        if not block:
            continue
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(\[\"“])", block):
            s = s.strip()
            if s:
                out.append(s)
    return out


def _is_factual(s: str) -> bool:
    plain = re.sub(r"[*_>]", "", s).strip()
    if len(plain) < 40 or plain.endswith("?") or plain.endswith(":"):
        return False
    low = plain.lower()
    if re.match(r"^(i|i'm|i've|i'll|let me|let's|we can|we could|shall i|want me|would you|could you|can you|please|next|do you|should i|if you|once you|tell me|to confirm|note:|unknown)\b", low):
        return False
    if "knowledge base has no information" in low or "can't draw a conclusion" in low or "cannot draw a conclusion" in low:
        return False
    if low.startswith("ask:") or low.startswith("ask "):
        return False
    return True


def uncited_sentences(reply: str) -> list[str]:
    return [s for s in _sentences(reply) if _is_factual(s) and not _RECEIPT.search(s)]


def topic_from(user_text: str, reply: str = "") -> str:
    m = re.search(r"no information (?:on|about) (.+?)(?:,| so |\.|$)", reply or "", re.I)
    if m and 2 < len(m.group(1)) < 80:
        return m.group(1).strip().strip("*_\"'")
    words = re.findall(r"[A-Za-z0-9][\w'/-]*", (user_text or "").lower())
    while words and words[0] in _LEAD_WORDS:
        words.pop(0)
    while words and words[-1] in _TRAIL_WORDS:
        words.pop()
    topic = " ".join(words[:8]).strip()
    if not topic:
        topic = (user_text or "").strip().rstrip("?").strip()[:60]
    return topic[:60] or "this topic"


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 2 and t not in _LEAD_WORDS}


def infer_controls(agent: "Agent", user_text: str) -> list[str]:
    """Controls the turn was about: from tool args first, else keyword overlap with the catalog."""
    cat = get_catalog()
    found: list[str] = []

    def add(c):
        if c and c in cat.controls and c not in found:
            found.append(c)

    for ev in agent.events:
        a = ev.get("args") or {}
        if ev["tool"] in ("who_to_ask",):
            for c in a.get("controls") or []:
                add(c)
        elif ev["tool"] in ("search_evidence", "record_user_fact"):
            add(a.get("control"))
        elif ev["tool"] == "get_question":
            q = cat.questions.get(str(a.get("qid", "")).replace("Q", "").split(".")[0])
            for c in (q.controls if q else []):
                add(c)
    for e in agent.evidence:
        add(e.get("control"))
    if found:
        return found
    qt = _tokens(user_text)
    if not qt:
        return []
    scored: list[tuple[int, str]] = []
    for cid, c in cat.controls.items():
        ct = _tokens(c.get("name", "")) | set(cid.split("_"))
        n = len(qt & ct)
        if n:
            scored.append((n, cid))
    for q in cat.questions.values():
        n = len(qt & _tokens(q.text))
        if n >= 2:
            for c in q.controls:
                scored.append((n - 1, c))
    scored.sort(reverse=True)
    for _, cid in scored:
        add(cid)
        if len(found) >= 2:
            break
    return found


def build_grounding(agent: "Agent", reply: str, user_text: str = "") -> dict:
    """grounding = {mode, receipts, uncited[, fallback]} for the done event."""
    from ..config import settings

    receipts = build_receipts(agent.store, agent.evidence)
    internal = [r for r in receipts if r["type"] in ("claim", "user")]
    public = [r for r in receipts if r["type"] == "external"]
    recorded = any(ev["tool"] in RECORD_TOOLS and ev.get("ok") for ev in agent.events)
    system_only = any(ev["tool"] in SYSTEM_TOOLS and ev.get("ok") for ev in agent.events) and not internal
    uncited = uncited_sentences(reply)
    factual = any(_is_factual(s) for s in _sentences(reply))
    cited = bool(_RECEIPT.search(reply))
    says_gap = "knowledge base has no information" in reply.lower()

    if recorded:
        mode = "grounded" if not uncited else "partial"
    elif internal and not says_gap:
        mode = "grounded" if cited and not uncited else ("partial" if uncited else "grounded")
    elif says_gap or (factual and not internal and not system_only):
        mode = "no_knowledge"
    else:
        mode = "conversational"

    g: dict = {"mode": mode, "receipts": receipts[:12], "uncited": [s[:160] for s in uncited[:6]]}
    if mode == "no_knowledge":
        asked = getattr(agent, "asked", None) or who_to_ask(agent.store, infer_controls(agent, user_text))
        g["fallback"] = {
            "topic": topic_from(user_text, reply), "owner_role": asked["owner_role"], "person": asked.get("person"), "ask": asked.get("ask"),
            "controls": asked.get("controls", []),
            "public_sources": [{"id": r["id"], "title": r.get("doc") or "", "url": r.get("url") or r.get("excerpt") or "", "snippet": (r.get("statement") or "")[:200], "label": r["label"]} for r in public],
            "web_research_available": bool(settings.tavily_api_key),
        }
    return g
