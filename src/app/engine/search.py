"""Hybrid evidence retrieval: dense vectors (fastembed → pgvector / in-memory cosine) blended with BM25.

Falls back to BM25 alone when embeddings are disabled or not yet built, so search never breaks.
"""

from __future__ import annotations

import math
import re
import threading

from rank_bm25 import BM25Okapi

from ..store.db import Store

_STOP = set("the a an and or of to in on for is are be with by as at from that this it its our we your you do does have has will shall may can not any all".split())
_TOK = re.compile(r"[a-z0-9]+")
DENSE_WEIGHT = 0.6


def tokenize(s: str) -> list[str]:
    return [t for t in _TOK.findall((s or "").lower()) if t not in _STOP and len(t) > 1]


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class EvidenceIndex:
    def __init__(self, store: Store):
        self.store = store
        self._lock = threading.Lock()
        self._built_for: int = -1
        self._docs: list[dict] = []
        self._bm25: BM25Okapi | None = None
        self._vecs: dict[str, list[float]] = {}  # "C12" / "K4" → vector (in-memory path)

    def _version(self) -> int:
        r = self.store.one("SELECT (SELECT count(*) FROM claims) + (SELECT count(*) FROM chunks) + (SELECT count(*) FROM user_statements) + (SELECT count(*) FROM external_findings) + (SELECT count(*) FROM embeddings) AS n")
        return int(r["n"]) if r else 0

    def _build(self) -> None:
        docs: list[dict] = []
        for c in self.store.q(
            "SELECT c.id, c.control, c.attribute, c.value, c.statement, c.excerpt, c.authority, c.modality, c.observed_at, "
            "d.name AS doc, d.doc_type, d.is_template FROM claims c JOIN documents d ON d.id=c.doc_id"
        ):
            docs.append({"type": "claim", "id": f"C{c['id']}", "text": f"{c['statement']} {c['excerpt']} {c['attribute']} {c['value']}", **c})
        for ch in self.store.q("SELECT ch.id, ch.heading, ch.text, d.name AS doc, d.doc_type, d.authority, d.is_template FROM chunks ch JOIN documents d ON d.id=ch.doc_id WHERE d.doc_type != 'questionnaire'"):
            docs.append({"type": "chunk", "id": f"K{ch['id']}", "text": f"{ch['heading']} {ch['text']}", **ch})
        for u in self.store.q("SELECT * FROM user_statements"):
            docs.append({"type": "user", "id": f"U{u['id']}", "text": f"{u['statement']} {u['attribute']} {u['value']}", **u})
        for x in self.store.q("SELECT * FROM external_findings"):
            docs.append({"type": "external", "id": f"X{x['id']}", "text": f"{x['title']} {x['snippet']} {x['note']}", **x})
        self._docs = docs
        self._bm25 = BM25Okapi([tokenize(d["text"]) or ["_"] for d in docs]) if docs else None
        # in-memory vectors (skipped when pgvector answers server-side)
        self._vecs = {}
        if not (self.store.dialect == "postgres" and self.store.has_pgvector):
            for iid, v in self.store.all_embeddings("claim"):
                self._vecs[f"C{iid}"] = v
            for iid, v in self.store.all_embeddings("chunk"):
                self._vecs[f"K{iid}"] = v

    def ensure(self) -> None:
        with self._lock:
            v = self._version()
            if v != self._built_for:
                self._build()
                self._built_for = v

    def _dense_scores(self, query: str) -> dict[str, float]:
        from . import embeddings as emb

        if not emb.available():
            return {}
        try:
            qv = emb.embed_query(query)
        except Exception:  # noqa: BLE001 - model not downloaded yet, etc.
            return {}
        out: dict[str, float] = {}
        server = self.store.nearest("claim", qv, 40)
        if server is not None:
            out.update({f"C{i}": s for i, s in server})
            out.update({f"K{i}": s for i, s in (self.store.nearest("chunk", qv, 20) or [])})
            return out
        for key, v in self._vecs.items():
            out[key] = _cos(qv, v)
        return out

    def search(self, query: str, k: int = 10, control: str | None = None, types: tuple[str, ...] = ("claim", "chunk", "user", "external")) -> list[dict]:
        self.ensure()
        if not self._bm25:
            return []
        bm = self._bm25.get_scores(tokenize(query))
        bmax = max(bm) if len(bm) and max(bm) > 0 else 1.0
        dense = self._dense_scores(query)
        used_dense = bool(dense)
        scored = []
        for i, d in enumerate(self._docs):
            lex = bm[i] / bmax
            den = dense.get(d["id"], 0.0)
            den = max(0.0, (den - 0.3) / 0.7) if used_dense else 0.0  # cosine → 0..1 with a floor
            s = (DENSE_WEIGHT * den + (1 - DENSE_WEIGHT) * lex) if used_dense else lex
            if d["type"] in ("user", "external") and not used_dense:
                s = lex
            scored.append((s, i))
        scored.sort(reverse=True)
        out = []
        for s, i in scored:
            d = self._docs[i]
            if s <= 0 and not control:
                break
            if d["type"] not in types:
                continue
            if control and d.get("control") not in (control, None) and d["type"] in ("claim", "user"):
                continue
            item = {k_: v for k_, v in d.items() if k_ != "text"}
            item["score"] = round(float(s), 3)
            if d["type"] == "chunk":
                item["text"] = d["text"][:1200]
            out.append(item)
            if len(out) >= k:
                break
        return out


_index: EvidenceIndex | None = None


def index_for(store: Store) -> EvidenceIndex:
    global _index
    if _index is None or _index.store is not store:
        _index = EvidenceIndex(store)
    return _index
