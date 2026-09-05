"""Orchestration: index → conflicts → derive → score; and incremental updates after user statements."""

from __future__ import annotations

import json
from pathlib import Path

from ..catalog.loader import get_catalog
from ..config import settings
from ..ingest.indexer import index_folder
from ..store.db import Store, now
from .conflicts import detect_conflicts, groups_for_control
from .derive import derive_all
from .scorer import score


def full_run(store: Store, root: Path | None = None, progress=None) -> dict:
    emit = progress or (lambda *_: None)
    emit("stage", {"stage": "index"})
    stats = index_folder(root or settings.datasets_dir, store, progress=progress)
    emit("stage", {"stage": "embed"})
    from .embeddings import index_missing
    try:
        emb = index_missing(store, progress=progress)
    except Exception as e:  # noqa: BLE001 - dense retrieval is optional
        emb = {"error": str(e)}
        store.log("embedding_error", str(e))
    emit("stage", {"stage": "conflicts"})
    n = detect_conflicts(store)
    emit("stage", {"stage": "derive", "conflicts": n, "total": len(get_catalog().questions)})
    counts = derive_all(store, progress=progress)
    emit("stage", {"stage": "score"})
    sc = score(store)
    store.kv_set("last_run", {"at": now(), "index": stats, "embeddings": emb, "conflicts": n, "derive": counts})
    emit("done", {"index": stats, "embeddings": emb, "conflicts": n, "derive": counts, "rating": sc["predicted_rating"]})
    return {"index": stats, "embeddings": emb, "conflicts": n, "derive": counts, "score": sc}


def record_user_fact(store: Store, *, control: str, attribute: str, value: str, statement: str, speaker: str,
                     role: str, qids: list[str] | None = None, rederive: bool = True) -> dict:
    """Store an attributed statement; supersede the previous statement on the same (control, attribute)."""
    prev = store.one(
        "SELECT id FROM user_statements WHERE control=? AND attribute=? AND id NOT IN "
        "(SELECT supersedes FROM user_statements WHERE supersedes IS NOT NULL) ORDER BY id DESC LIMIT 1",
        (control, attribute))
    cat = get_catalog()
    qids = qids or [q.qid for q in cat.questions_for_control(control)]
    sid = store.insert("user_statements", {
        "control": control, "attribute": attribute, "value": value, "statement": statement, "speaker": speaker,
        "role": role, "qids": json.dumps(qids), "supersedes": prev["id"] if prev else None, "created_at": now(),
    })
    store.log("user_fact", {"id": sid, "control": control, "attribute": attribute, "speaker": speaker, "supersedes": prev["id"] if prev else None})
    affected = sorted(set(qids) | {q.qid for q in cat.questions_for_control(control)}, key=float)
    if rederive and affected:
        derive_all(store, affected)
        score(store)
    return {"id": sid, "supersedes": prev["id"] if prev else None, "affected_qids": affected}


def resolve_conflict(store: Store, conflict_id: int, resolution: str, resolved_by: str, rederive: bool = True) -> dict:
    c = store.one("SELECT * FROM conflicts WHERE id=?", (conflict_id,))
    if not c:
        raise ValueError(f"conflict {conflict_id} not found")
    meta = json.loads(c["resolution"] or "{}")
    meta["text"] = resolution
    store.execute("UPDATE conflicts SET status='resolved', resolution=?, resolved_by=?, resolved_at=? WHERE id=?",
                  (json.dumps(meta), resolved_by, now(), conflict_id))
    store.log("conflict_resolved", {"id": conflict_id, "by": resolved_by})
    controls = set(meta.get("controls", [])) | {c["control"]}
    cat = get_catalog()
    affected = sorted({q.qid for ctl in controls for q in cat.questions_for_control(ctl)}, key=float)
    if rederive and affected:
        derive_all(store, affected)
        score(store)
    return {"id": conflict_id, "affected_qids": affected}


def recheck_conflicts_for(store: Store, control: str) -> int:
    groups = groups_for_control(control)
    return detect_conflicts(store, groups) if groups else 0
