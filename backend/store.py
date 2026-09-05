"""Persistent security profile.

SQLite so the profile survives restarts: the analyst genuinely remembers what it
learned, never re-asks a settled question, and keeps a full revision history so
a user correction is an *update* with an audit trail rather than an overwrite.

Tables
  answers        one row per questionnaire question (current state)
  answer_history append-only log of every change, with who/why
  facts          free-standing facts learned from a human, reusable across questions
  conflicts      detected contradictions and their resolution state
  messages       conversation transcript (text + voice turns)
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from .config import PROFILE_DB

# Answer status vocabulary — mirrors the track's required distinctions.
VERIFIED = "verified"          # proven from company information
USER_CONFIRMED = "user_confirmed"  # a human told us, recorded
CONFLICT = "conflict"          # sources disagree; must be resolved
UNKNOWN = "unknown"            # no information; needs confirmation
STATUSES = (VERIFIED, USER_CONFIRMED, CONFLICT, UNKNOWN)

SCHEMA = """
CREATE TABLE IF NOT EXISTS answers (
    question_id   TEXT PRIMARY KEY,
    topic         TEXT NOT NULL,
    question      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'unknown',
    answer        TEXT NOT NULL DEFAULT '',
    rationale     TEXT NOT NULL DEFAULT '',
    confidence    REAL NOT NULL DEFAULT 0.0,
    evidence      TEXT NOT NULL DEFAULT '[]',
    followup      TEXT NOT NULL DEFAULT '',
    control_id    TEXT NOT NULL DEFAULT '',
    criticality   TEXT NOT NULL DEFAULT '',
    asked_count   INTEGER NOT NULL DEFAULT 0,
    updated_at    REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS answer_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL,
    status      TEXT NOT NULL,
    answer      TEXT NOT NULL,
    confidence  REAL NOT NULL,
    actor       TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id         TEXT PRIMARY KEY,
    subject    TEXT NOT NULL,
    statement  TEXT NOT NULL,
    actor      TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'user',
    at         REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS conflicts (
    id           TEXT PRIMARY KEY,
    question_id  TEXT NOT NULL DEFAULT '',
    topic        TEXT NOT NULL DEFAULT '',
    summary      TEXT NOT NULL,
    side_a       TEXT NOT NULL,
    side_b       TEXT NOT NULL,
    severity     TEXT NOT NULL DEFAULT 'medium',
    status       TEXT NOT NULL DEFAULT 'open',
    resolution   TEXT NOT NULL DEFAULT '',
    detected_by  TEXT NOT NULL DEFAULT 'rule',
    at           REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    session   TEXT NOT NULL,
    role      TEXT NOT NULL,
    content   TEXT NOT NULL,
    channel   TEXT NOT NULL DEFAULT 'text',
    meta      TEXT NOT NULL DEFAULT '{}',
    at        REAL NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    PROFILE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(PROFILE_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


class ProfileStore:
    """The analyst's memory. All writes are logged."""

    def __init__(self) -> None:
        self.conn = connect()
        self._lock = __import__("threading").Lock()

    # ---------------- questionnaire seeding ----------------

    def seed_questions(self, questions: list[dict]) -> int:
        added = 0
        with self._lock, self.conn:
            for q in questions:
                cur = self.conn.execute(
                    "SELECT 1 FROM answers WHERE question_id = ?", (q["id"],)
                )
                if cur.fetchone():
                    continue
                self.conn.execute(
                    """INSERT INTO answers
                       (question_id, topic, question, status, control_id, criticality, updated_at)
                       VALUES (?, ?, ?, 'unknown', ?, ?, ?)""",
                    (
                        q["id"],
                        q["topic"],
                        q["question"],
                        q.get("control_id", ""),
                        q.get("criticality", ""),
                        time.time(),
                    ),
                )
                added += 1
        return added

    # ---------------- answers ----------------

    def get_answer(self, question_id: str) -> dict | None:
        cur = self.conn.execute(
            "SELECT * FROM answers WHERE question_id = ?", (question_id,)
        )
        row = cur.fetchone()
        return self._row_to_answer(row) if row else None

    def all_answers(self) -> list[dict]:
        cur = self.conn.execute("SELECT * FROM answers")
        rows = [self._row_to_answer(r) for r in cur.fetchall()]
        rows.sort(key=lambda r: float(r["question_id"]))
        return rows

    @staticmethod
    def _row_to_answer(row: sqlite3.Row) -> dict:
        data = dict(row)
        try:
            data["evidence"] = json.loads(data.get("evidence") or "[]")
        except json.JSONDecodeError:
            data["evidence"] = []
        return data

    def record_answer(
        self,
        question_id: str,
        *,
        status: str,
        answer: str,
        rationale: str = "",
        confidence: float = 0.0,
        evidence: list[dict] | None = None,
        followup: str = "",
        actor: str = "analyst",
        reason: str = "",
    ) -> dict:
        if status not in STATUSES:
            raise ValueError(f"invalid status {status!r}; expected one of {STATUSES}")
        now = time.time()
        with self._lock, self.conn:
            self.conn.execute(
                """UPDATE answers
                   SET status = ?, answer = ?, rationale = ?, confidence = ?,
                       evidence = ?, followup = ?, updated_at = ?
                   WHERE question_id = ?""",
                (
                    status,
                    answer,
                    rationale,
                    float(max(0.0, min(1.0, confidence))),
                    json.dumps(evidence or []),
                    followup,
                    now,
                    question_id,
                ),
            )
            self.conn.execute(
                """INSERT INTO answer_history
                   (question_id, status, answer, confidence, actor, reason, at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (question_id, status, answer, float(confidence), actor, reason, now),
            )
        return self.get_answer(question_id)  # type: ignore[return-value]

    def mark_asked(self, question_id: str) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE answers SET asked_count = asked_count + 1 WHERE question_id = ?",
                (question_id,),
            )

    def history(self, question_id: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM answer_history WHERE question_id = ? ORDER BY at ASC",
            (question_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    # ---------------- facts learned from humans ----------------

    def add_fact(self, subject: str, statement: str, actor: str, source: str = "user") -> dict:
        fact = {
            "id": uuid.uuid4().hex[:12],
            "subject": subject,
            "statement": statement,
            "actor": actor,
            "source": source,
            "at": time.time(),
        }
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO facts (id, subject, statement, actor, source, at) VALUES (?,?,?,?,?,?)",
                tuple(fact.values()),
            )
        return fact

    def facts(self) -> list[dict]:
        cur = self.conn.execute("SELECT * FROM facts ORDER BY at DESC")
        return [dict(r) for r in cur.fetchall()]

    def search_facts(self, query: str, limit: int = 5) -> list[dict]:
        terms = [t for t in query.lower().split() if len(t) > 3]
        out: list[tuple[int, dict]] = []
        for fact in self.facts():
            blob = f"{fact['subject']} {fact['statement']}".lower()
            score = sum(1 for t in terms if t in blob)
            if score:
                out.append((score, fact))
        out.sort(key=lambda p: p[0], reverse=True)
        return [f for _, f in out[:limit]]

    # ---------------- conflicts ----------------

    def add_conflict(
        self,
        *,
        summary: str,
        side_a: str,
        side_b: str,
        question_id: str = "",
        topic: str = "",
        severity: str = "medium",
        detected_by: str = "rule",
    ) -> dict:
        # De-duplicate on summary so re-running detection is idempotent.
        cur = self.conn.execute("SELECT * FROM conflicts WHERE summary = ?", (summary,))
        existing = cur.fetchone()
        if existing:
            return dict(existing)
        conflict = {
            "id": uuid.uuid4().hex[:12],
            "question_id": question_id,
            "topic": topic,
            "summary": summary,
            "side_a": side_a,
            "side_b": side_b,
            "severity": severity,
            "status": "open",
            "resolution": "",
            "detected_by": detected_by,
            "at": time.time(),
        }
        with self._lock, self.conn:
            self.conn.execute(
                """INSERT INTO conflicts
                   (id, question_id, topic, summary, side_a, side_b, severity,
                    status, resolution, detected_by, at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(conflict.values()),
            )
        return conflict

    def conflicts(self, status: str | None = None) -> list[dict]:
        if status:
            cur = self.conn.execute(
                "SELECT * FROM conflicts WHERE status = ? ORDER BY at DESC", (status,)
            )
        else:
            cur = self.conn.execute("SELECT * FROM conflicts ORDER BY at DESC")
        return [dict(r) for r in cur.fetchall()]

    def resolve_conflict(self, conflict_id: str, resolution: str, actor: str) -> dict | None:
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE conflicts SET status = 'resolved', resolution = ? WHERE id = ?",
                (f"{resolution} (resolved by {actor})", conflict_id),
            )
        cur = self.conn.execute("SELECT * FROM conflicts WHERE id = ?", (conflict_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    # ---------------- transcript ----------------

    def add_message(
        self, session: str, role: str, content: str, channel: str = "text", meta: dict | None = None
    ) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO messages (session, role, content, channel, meta, at) VALUES (?,?,?,?,?,?)",
                (session, role, content, channel, json.dumps(meta or {}), time.time()),
            )

    def transcript(self, session: str, limit: int = 40) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM messages WHERE session = ? ORDER BY at DESC LIMIT ?",
            (session, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
        rows.reverse()
        return rows

    # ---------------- reporting ----------------

    def stats(self) -> dict[str, Any]:
        answers = self.all_answers()
        by_status: dict[str, int] = {s: 0 for s in STATUSES}
        for a in answers:
            by_status[a["status"]] = by_status.get(a["status"], 0) + 1
        total = len(answers) or 1
        answered = by_status[VERIFIED] + by_status[USER_CONFIRMED]
        return {
            "total_questions": len(answers),
            "by_status": by_status,
            "completion_pct": round(100 * answered / total, 1),
            "open_conflicts": len(self.conflicts("open")),
            "facts_learned": len(self.facts()),
            "avg_confidence": round(
                sum(a["confidence"] for a in answers) / total, 3
            ),
        }

    def reset(self) -> None:
        with self._lock, self.conn:
            for table in ("answers", "answer_history", "facts", "conflicts", "messages"):
                self.conn.execute(f"DELETE FROM {table}")


_store: ProfileStore | None = None


def get_store() -> ProfileStore:
    global _store
    if _store is None:
        _store = ProfileStore()
    return _store
