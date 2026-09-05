"""Profile store with two dialects behind one API.

- SQLite (default, zero-config):    DATABASE_URL unset  → data/profile.db
- Postgres / Neon (+ pgvector):     DATABASE_URL=postgres://...  (sslmode=require for Neon)

All callers write SQLite-flavoured SQL with `?` placeholders; the Postgres path rewrites placeholders and the
schema. Embeddings live in `embeddings` — a real `vector` column when the pgvector extension is available,
otherwise JSON text ranked in Python.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config import settings

EMBED_DIM = settings.embedding_dim

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY, path TEXT UNIQUE, name TEXT, folder TEXT, ext TEXT,
  doc_type TEXT, authority INTEGER, is_template INTEGER, entity TEXT, effective_date TEXT,
  text_len INTEGER, sha TEXT, summary TEXT, indexed_at TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES documents(id) ON DELETE CASCADE, idx INTEGER, heading TEXT, text TEXT, sha TEXT
);
CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES documents(id) ON DELETE CASCADE, chunk_id INTEGER, control TEXT, attribute TEXT,
  value TEXT, statement TEXT, modality TEXT, authority INTEGER, observed_at TEXT, excerpt TEXT
);
CREATE INDEX IF NOT EXISTS idx_claims_control ON claims(control);
CREATE TABLE IF NOT EXISTS questions (
  qid TEXT PRIMARY KEY, topic TEXT, text TEXT, controls TEXT, criticality TEXT,
  inherent_pts REAL, residual_pts REAL, informational INTEGER, rule_if_no TEXT,
  control_id TEXT, control_objective TEXT, owner_role TEXT, slots TEXT, answer_type TEXT
);
CREATE TABLE IF NOT EXISTS question_state (
  qid TEXT PRIMARY KEY, status TEXT, answer TEXT, comments TEXT, confidence REAL,
  evidence TEXT, open_slots TEXT, next_question TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS user_statements (
  id INTEGER PRIMARY KEY, control TEXT, attribute TEXT, value TEXT, statement TEXT,
  speaker TEXT, role TEXT, qids TEXT, supersedes INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS conflicts (
  id INTEGER PRIMARY KEY, control TEXT, attribute TEXT, claim_ids TEXT, description TEXT,
  question_to_ask TEXT, status TEXT, resolution TEXT, resolved_by TEXT, created_at TEXT, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS external_findings (
  id INTEGER PRIMARY KEY, kind TEXT, query TEXT, url TEXT, title TEXT, snippet TEXT,
  published_at TEXT, control TEXT, note TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, session TEXT, role TEXT, content TEXT, meta TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY, event TEXT, detail TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS dashboard_items (
  id INTEGER PRIMARY KEY, title TEXT, spec TEXT, source TEXT, position INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS embeddings (
  item_type TEXT, item_id INTEGER, model TEXT, vec __VEC__, PRIMARY KEY (item_type, item_id)
);
"""

ID_TABLES = {"documents", "chunks", "claims", "user_statements", "conflicts", "external_findings", "messages", "audit_log", "dashboard_items"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | None = None, url: str | None = None):
        self.url = url if url is not None else (settings.database_url if path is None else "")
        self.dialect = "postgres" if self.url else "sqlite"
        self._lock = threading.RLock()
        self.has_pgvector = False
        if self.dialect == "postgres":
            self._connect_pg()
        else:
            self.path = Path(path or settings.db_path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA.replace("__VEC__", "TEXT"))

    # ------------------------------------------------------------------ postgres
    def _connect_pg(self) -> None:
        import psycopg
        from psycopg.rows import dict_row

        self._conn = psycopg.connect(self.url, row_factory=dict_row, autocommit=False)
        try:
            with self._conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            self._conn.commit()
            self.has_pgvector = True
        except Exception:  # noqa: BLE001 - extension unavailable → JSON fallback
            self._conn.rollback()
            self.has_pgvector = False
        schema = SCHEMA.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY").replace("__VEC__", f"vector({EMBED_DIM})" if self.has_pgvector else "TEXT")
        with self._conn.cursor() as cur:
            # Migration: an embeddings table created before pgvector was available has a TEXT column.
            # Embeddings are derived data, so rebuild the table with a real vector column.
            cur.execute("SELECT data_type, udt_name FROM information_schema.columns WHERE table_name='embeddings' AND column_name='vec'")
            row = cur.fetchone()
            if row and self.has_pgvector and row["udt_name"] != "vector":
                cur.execute("DROP TABLE embeddings")
            for stmt in [s.strip() for s in schema.split(";") if s.strip()]:
                cur.execute(stmt)
        self._conn.commit()
        if self.has_pgvector:
            from pgvector.psycopg import register_vector

            register_vector(self._conn)

    def _pg(self, sql: str) -> str:
        return sql.replace("?", "%s")

    def _reconnect_if_needed(self) -> None:
        if self.dialect == "postgres" and getattr(self._conn, "closed", False):
            self._connect_pg()

    # ------------------------------------------------------------------ generic
    @contextmanager
    def tx(self):
        with self._lock:
            self._reconnect_if_needed()
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _exec(self, sql: str, params: Iterable[Any] = ()):
        params = tuple(params)
        if self.dialect == "postgres":
            cur = self._conn.cursor()
            cur.execute(self._pg(sql), params)
            return cur
        return self._conn.execute(sql, params)

    def q(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            self._reconnect_if_needed()
            try:
                cur = self._exec(sql, params)
                rows = cur.fetchall()
                if self.dialect == "postgres":
                    self._conn.commit()
                return [dict(r) for r in rows]
            except Exception:
                if self.dialect == "postgres":
                    self._conn.rollback()
                raise

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        rows = self.q(sql, params)
        return rows[0] if rows else None

    @staticmethod
    def _vals(row: dict[str, Any]) -> list:
        return [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()]

    def insert(self, table: str, row: dict[str, Any]) -> int:
        cols = ", ".join(row.keys())
        ph = ", ".join("?" for _ in row)
        with self.tx() as c:
            if self.dialect == "postgres":
                sql = f"INSERT INTO {table} ({cols}) VALUES ({ph})" + (" RETURNING id" if table in ID_TABLES else "")
                cur = self._exec(sql, self._vals(row))
                return int(cur.fetchone()["id"]) if table in ID_TABLES else 0
            cur = c.execute(f"INSERT INTO {table} ({cols}) VALUES ({ph})", self._vals(row))
            return int(cur.lastrowid)

    def upsert(self, table: str, key: str, row: dict[str, Any]) -> None:
        cols = ", ".join(row.keys())
        ph = ", ".join("?" for _ in row)
        upd = ", ".join(f"{k}=excluded.{k}" for k in row if k != key) or f"{key}=excluded.{key}"
        with self.tx():
            self._exec(f"INSERT INTO {table} ({cols}) VALUES ({ph}) ON CONFLICT({key}) DO UPDATE SET {upd}", self._vals(row))

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.tx():
            self._exec(sql, params)

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        if not rows:
            return
        with self.tx() as c:
            if self.dialect == "postgres":
                with self._conn.cursor() as cur:
                    cur.executemany(self._pg(sql), rows)
            else:
                c.executemany(sql, rows)

    def log(self, event: str, detail: Any = "") -> None:
        self.insert("audit_log", {"event": event, "detail": detail if isinstance(detail, str) else json.dumps(detail), "created_at": now()})

    def kv_get(self, k: str, default: Any = None) -> Any:
        r = self.one("SELECT v FROM kv WHERE k=?", (k,))
        return json.loads(r["v"]) if r else default

    def kv_set(self, k: str, v: Any) -> None:
        self.upsert("kv", "k", {"k": k, "v": json.dumps(v)})

    # ------------------------------------------------------------------ embeddings
    def put_embeddings(self, item_type: str, rows: list[tuple[int, list[float]]], model: str) -> None:
        if not rows:
            return
        if self.dialect == "postgres" and self.has_pgvector:
            import numpy as np

            data = [(item_type, iid, model, np.asarray(vec, dtype="float32")) for iid, vec in rows]
        else:
            data = [(item_type, iid, model, json.dumps([round(float(x), 6) for x in vec])) for iid, vec in rows]
        self.executemany(
            "INSERT INTO embeddings (item_type, item_id, model, vec) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(item_type, item_id) DO UPDATE SET vec=excluded.vec, model=excluded.model", data)

    def embedded_ids(self, item_type: str) -> set[int]:
        return {r["item_id"] for r in self.q("SELECT item_id FROM embeddings WHERE item_type=?", (item_type,))}

    def all_embeddings(self, item_type: str) -> list[tuple[int, list[float]]]:
        out = []
        for r in self.q("SELECT item_id, vec FROM embeddings WHERE item_type=?", (item_type,)):
            v = r["vec"]
            out.append((r["item_id"], list(v) if not isinstance(v, str) else json.loads(v)))
        return out

    def nearest(self, item_type: str, vec: list[float], k: int) -> list[tuple[int, float]] | None:
        """Server-side ANN when pgvector is present; None tells the caller to rank in Python."""
        if not (self.dialect == "postgres" and self.has_pgvector):
            return None
        import numpy as np

        rows = self.q("SELECT item_id, 1 - (vec <=> ?) AS sim FROM embeddings WHERE item_type=? ORDER BY vec <=> ? LIMIT ?",
                      (np.asarray(vec, dtype="float32"), item_type, np.asarray(vec, dtype="float32"), k))
        return [(r["item_id"], float(r["sim"])) for r in rows]

    # ------------------------------------------------------------------ maintenance
    def counts(self) -> dict[str, int]:
        out = {}
        for t in ("documents", "chunks", "claims", "user_statements", "conflicts", "external_findings", "embeddings", "messages"):
            out[t] = int(self.one(f"SELECT count(*) AS n FROM {t}")["n"])
        return out

    def reset_derived(self) -> None:
        """Clear everything derived from documents (keeps user statements & messages)."""
        with self.tx():
            for t in ("embeddings", "claims", "chunks", "documents", "conflicts", "question_state"):
                self._exec(f"DELETE FROM {t}")

    def wipe(self) -> None:
        with self.tx():
            for t in ("embeddings", "claims", "chunks", "documents", "conflicts", "question_state", "user_statements",
                      "external_findings", "messages", "audit_log", "kv"):
                self._exec(f"DELETE FROM {t}")


_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def loads(v: Any, default: Any = None) -> Any:
    if v is None or v == "":
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (TypeError, json.JSONDecodeError):
        return default
