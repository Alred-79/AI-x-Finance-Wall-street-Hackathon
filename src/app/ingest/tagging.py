"""Authority tagging, template detection, date/entity extraction, chunking.

Authority levels (higher wins in a conflict):
  4 record       observed records: access reviews, inventories, pentest findings, chat logs, live probes
  3 attestation  audited reports (SOC 2)
  2 policy       policies, plans, contracts (what *should* happen)
  1 template     unfilled templates / illustrative material (not evidence)
  0 catalog      the questionnaire itself (never a source of answers)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parsers import ParsedDoc

AUTHORITY_LABEL = {4: "record", 3: "attestation", 2: "policy", 1: "template", 0: "catalog"}

_TEMPLATE_MARKERS = [
    r"<\s*company name\s*>",
    r"<\s*policy owner\s*>",
    r"instructions for use",
    r"this template has been pre-filled",
    r"policy template instructions",
    r"illustrative templates",
    r"replace any highlighted text",
]
_DATE_PATTERNS = [
    r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b",
    r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4})\b",
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
    r"\b(\d{4}-\d{2}-\d{2})\b",
]


@dataclass
class DocTags:
    doc_type: str
    authority: int
    is_template: bool
    entity: str
    effective_date: str
    skip_claims: bool = False


def _has_template_markers(text: str) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in _TEMPLATE_MARKERS)


def _first_date(text: str) -> str:
    # Prefer an explicit effective/report/review/completion date anywhere in the document
    for label in (r"effective date", r"date of review", r"date of completion", r"date of report", r"report date"):
        m = re.search(label + r"[:\s|]*([^\n|]{4,40})", text, re.I)
        if m:
            for p in _DATE_PATTERNS:
                d = re.search(p, m.group(1))
                if d:
                    return d.group(1)
    head = text[:4000]
    for p in _DATE_PATTERNS:
        d = re.search(p, head)
        if d:
            return d.group(1)
    return ""


def _entity(text: str) -> str:
    head = text[:3000]
    found = []
    for name in ("Solsphere AI Inc", "Solsphere", "Regodit AI", "REGODIT Inc", "Regodit"):
        if name.lower() in head.lower():
            found.append(name)
    return found[0] if found else ""


def tag(doc: ParsedDoc) -> DocTags:
    name = doc.name.lower()
    folder = doc.folder.lower()
    text = doc.text or ""
    is_template = _has_template_markers(text)
    entity = _entity(text)
    date = _first_date(text)

    # questionnaire → catalog only
    if "questionnaire" in name or folder.startswith("1."):
        return DocTags("questionnaire", 0, False, entity, date, skip_claims=True)
    if is_template:
        return DocTags("template", 1, True, entity, date)
    if doc.ext in {".png", ".jpg", ".jpeg", ".webp"}:
        return DocTags("diagram", 2, False, entity, date)
    if "soc" in name and "report" in name:
        return DocTags("soc2_report", 3, False, entity, date)
    if any(k in name for k in ("vapt", "pentest", "penetration", "pen test")):
        return DocTags("pentest_report", 4, False, entity, date)
    if any(k in name for k in ("access_review", "access review", "inventory", "register", "log", "records")):
        return DocTags("record", 4, False, entity, date)
    if any(k in name for k in ("slack", "chat", "messages", "teams", "thread")) or doc.ext == ".json":
        return DocTags("chat", 4, False, entity, date)
    if "policy" in name or folder.startswith("2."):
        return DocTags("policy", 2, False, entity, date)
    if any(k in name for k in ("agreement", "contract", "msa", "dpa", "w-9", "w9")):
        return DocTags("contract", 2, False, entity, date)
    if doc.ext in {".png", ".jpg", ".jpeg", ".webp"}:
        return DocTags("diagram", 2, False, entity, date)
    if "plan" in name or "sdlc" in name or "lifecycle" in name:
        return DocTags("plan", 2, False, entity, date)
    return DocTags("document", 2, False, entity, date)


# ------------------------------------------------------------------ chunking

_HEADING = re.compile(r"^(##\s+.+|\d{1,2}\.\s+[A-Z][^\n]{2,80}|[A-Z][A-Za-z &/-]{3,60}:?)$")


def chunk_text(text: str, target: int = 5000, hard_max: int = 7000) -> list[tuple[str, str]]:
    """Split on headings, then pack sections up to ~target chars. Returns (heading, text)."""
    lines = text.split("\n")
    sections: list[tuple[str, list[str]]] = [("", [])]
    for ln in lines:
        s = ln.strip()
        if s and _HEADING.match(s) and len(s) < 90:
            sections.append((s.lstrip("# ").strip(), []))
        else:
            sections[-1][1].append(ln)
    chunks: list[tuple[str, str]] = []
    cur_head: str = ""
    cur: list[str] = []
    cur_len = 0
    for head, body in sections:
        body_txt = "\n".join(body).strip()
        if not body_txt and not head:
            continue
        piece = (f"## {head}\n" if head else "") + body_txt
        if cur_len + len(piece) > target and cur:
            chunks.append((cur_head, "\n\n".join(cur)))
            cur, cur_len, cur_head = [], 0, head
        if not cur:
            cur_head = head or cur_head
        # hard split very long sections
        while len(piece) > hard_max:
            cut = piece.rfind("\n", 0, hard_max)
            cut = cut if cut > target // 2 else hard_max
            chunks.append((head, piece[:cut]))
            piece = piece[cut:]
        cur.append(piece)
        cur_len += len(piece)
    if cur:
        chunks.append((cur_head, "\n\n".join(cur)))
    return [(h, c) for h, c in chunks if c.strip()]
