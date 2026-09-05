"""Local embeddings (fastembed, CPU, no API key) for claims and chunks.

OpenRouter exposes no embedding models, so vectors are produced locally with a small ONNX model and stored in
the profile store (pgvector on Postgres/Neon, JSON on SQLite). Set EMBEDDING_PROVIDER=none to disable.
"""

from __future__ import annotations

import threading
from typing import Iterable

from ..config import settings
from ..store.db import Store

_model = None
_lock = threading.Lock()


def available() -> bool:
    return settings.embedding_provider != "none"


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding

                cache = settings.data_dir / "cache" / "fastembed"
                cache.mkdir(parents=True, exist_ok=True)
                _model = TextEmbedding(model_name=settings.embedding_model, cache_dir=str(cache))
    return _model


def embed(texts: Iterable[str]) -> list[list[float]]:
    texts = [t if t.strip() else "empty" for t in texts]
    if not texts:
        return []
    return [list(map(float, v)) for v in _get_model().embed(texts, batch_size=64)]


def embed_query(text: str) -> list[float]:
    # bge models expect a retrieval instruction for queries
    return embed([f"Represent this sentence for searching relevant passages: {text}"])[0]


def index_missing(store: Store, progress=None) -> dict:
    """Embed every claim and chunk that has no vector yet."""
    if not available():
        return {"claims": 0, "chunks": 0, "skipped": True}
    emit = progress or (lambda *_: None)
    done = {"claims": 0, "chunks": 0}
    have = store.embedded_ids("claim")
    claims = [c for c in store.q("SELECT id, statement, excerpt, attribute, value FROM claims ORDER BY id") if c["id"] not in have]
    for i in range(0, len(claims), 128):
        batch = claims[i:i + 128]
        vecs = embed([f"{c['statement']} {c['excerpt'] or ''} ({c['attribute']}: {c['value']})" for c in batch])
        store.put_embeddings("claim", [(c["id"], v) for c, v in zip(batch, vecs)], settings.embedding_model)
        done["claims"] += len(batch)
        emit("embedding", {"claims": done["claims"], "of": len(claims)})
    have = store.embedded_ids("chunk")
    chunks = [c for c in store.q("SELECT ch.id, ch.heading, ch.text FROM chunks ch JOIN documents d ON d.id=ch.doc_id WHERE d.doc_type != 'questionnaire' ORDER BY ch.id") if c["id"] not in have]
    for i in range(0, len(chunks), 32):
        batch = chunks[i:i + 32]
        vecs = embed([f"{c['heading'] or ''}\n{c['text'][:2000]}" for c in batch])
        store.put_embeddings("chunk", [(c["id"], v) for c, v in zip(batch, vecs)], settings.embedding_model)
        done["chunks"] += len(batch)
        emit("embedding", {"chunks": done["chunks"], "of": len(chunks)})
    return done
