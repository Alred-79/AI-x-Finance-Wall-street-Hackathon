"""Index a folder of company documents into the profile store.

parse → tag → (vision for images / scanned PDFs) → chunk → extract claims (parallel, cached) → store.
Derivation (answers, conflicts, scores) is a separate step in engine.derive.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from ..catalog.loader import seed_questions
from ..config import settings
from ..extract.claims import MODALITIES, extract_claims, summarise
from ..store.db import Store, now
from .parsers import ParsedDoc, iter_files, parse_file
from .tagging import AUTHORITY_LABEL, chunk_text, tag

Progress = Callable[[str, dict], None]


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:24]


def _vision_text(doc: ParsedDoc) -> str:
    """Describe an image / scanned PDF with the vision model. Returns text or '' on failure."""
    from ..llm import describe_image

    img_path = doc.path
    if doc.ext == ".pdf":
        try:
            import pypdfium2 as pdfium  # optional dependency

            pdf = pdfium.PdfDocument(doc.path)
            page = pdf[0]
            img = page.render(scale=2).to_pil()
            out = settings.data_dir / "cache" / "renders"
            out.mkdir(parents=True, exist_ok=True)
            img_path = str(out / (Path(doc.path).stem + ".png"))
            img.save(img_path)
        except Exception as e:  # noqa: BLE001
            return f"[scanned PDF; could not render for vision: {e}]"
    prompt = (
        "You are helping a security assessor. Describe this image precisely. If it is a diagram, list every component, "
        "trust boundary, network tier, authentication step (MFA/VPN/bastion), logging/SIEM path, and encryption note "
        "shown, then state whether it is labelled as illustrative/template. If it is a form (e.g. a W-9), transcribe the "
        "business/legal name, DBA name, entity type, address, and signature date, but DO NOT output any tax ID, SSN or "
        "EIN digits (write [redacted]). Plain text."
    )
    try:
        return describe_image(img_path, prompt)
    except Exception as e:  # noqa: BLE001
        return f"[vision unavailable: {e}]"


def index_folder(root: Path, store: Store, progress: Progress | None = None, workers: int = 6,
                 use_llm: bool = True) -> dict:
    root = Path(root).resolve()  # absolute, so the same file never registers twice under two spellings
    seed_questions(store)
    files = iter_files(root)
    stats = {"files": 0, "chunks": 0, "claims": 0, "skipped": 0, "errors": []}
    emit = progress or (lambda *_: None)

    jobs: list[tuple[int, int, str, dict]] = []  # (doc_id, chunk_id, text, meta)
    for f in files:
        try:
            doc = parse_file(f, root)
        except Exception as e:  # noqa: BLE001
            stats["errors"].append(f"{f.name}: {e}")
            continue
        if doc.needs_vision and use_llm:
            doc.text = _vision_text(doc)
        t = tag(doc)
        sha = _sha(doc.text)
        existing = store.one("SELECT id, sha FROM documents WHERE path=?", (str(f),))
        if existing and existing["sha"] == sha:
            # Unchanged file. If a previous run parsed it but extraction failed (e.g. bad API key), its chunks
            # have no claims yet — re-queue them instead of silently skipping forever.
            n_claims = store.one("SELECT count(*) AS n FROM claims WHERE doc_id=?", (existing["id"],))["n"]
            if n_claims == 0 and not t.skip_claims and doc.text.strip():
                meta = {"name": doc.name, "doc_type": t.doc_type, "authority": t.authority, "authority_label": AUTHORITY_LABEL[t.authority],
                        "is_template": t.is_template, "entity": t.entity, "effective_date": t.effective_date}
                for ch in store.q("SELECT id, heading, text FROM chunks WHERE doc_id=? ORDER BY idx", (existing["id"],)):
                    jobs.append((existing["id"], ch["id"], ch["text"], {**meta, "heading": ch["heading"]}))
                emit("requeue", {"file": f.name})
            else:
                stats["skipped"] += 1
                emit("skip", {"file": f.name})
            continue
        if existing:
            store.execute("DELETE FROM documents WHERE id=?", (existing["id"],))
        doc_id = store.insert("documents", {
            "path": str(f), "name": doc.name, "folder": doc.folder, "ext": doc.ext, "doc_type": t.doc_type,
            "authority": t.authority, "is_template": int(t.is_template), "entity": t.entity,
            "effective_date": t.effective_date, "text_len": len(doc.text), "sha": sha, "summary": "",
            "indexed_at": now(),
        })
        stats["files"] += 1
        emit("parsed", {"file": f.name, "doc_type": t.doc_type, "authority": t.authority})
        if t.skip_claims or not doc.text.strip():
            continue
        meta = {
            "name": doc.name, "doc_type": t.doc_type, "authority": t.authority,
            "authority_label": AUTHORITY_LABEL[t.authority], "is_template": t.is_template,
            "entity": t.entity, "effective_date": t.effective_date,
        }
        for idx, (heading, text) in enumerate(chunk_text(doc.text)):
            cid = store.insert("chunks", {"doc_id": doc_id, "idx": idx, "heading": heading, "text": text, "sha": _sha(text)})
            stats["chunks"] += 1
            jobs.append((doc_id, cid, text, {**meta, "heading": heading}))

    if not use_llm:
        return stats
    emit("extracting", {"chunks": len(jobs), "files": stats["files"]})

    def work(job):
        doc_id, cid, text, meta = job
        claims = extract_claims(text, meta)
        modality = "template_text" if meta["is_template"] else MODALITIES.get(meta["doc_type"], "document_describes")
        rows = []
        for c in claims:
            rows.append({
                "doc_id": doc_id, "chunk_id": cid, "control": c["control"], "attribute": c["attribute"],
                "value": c["value"], "statement": c["statement"], "modality": modality,
                "authority": meta["authority"], "observed_at": c["observed_at"] or meta["effective_date"],
                "excerpt": c["excerpt"],
            })
        return meta["name"], rows

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, j) for j in jobs]
        for fut in as_completed(futs):
            try:
                name, rows = fut.result()
            except Exception as e:  # noqa: BLE001
                stats["errors"].append(str(e))
                emit("error", {"error": str(e)})
                continue
            for r in rows:
                store.insert("claims", r)
            stats["claims"] += len(rows)
            emit("claims", {"file": name, "n": len(rows), "total": stats["claims"]})

    # document summaries (cheap, parallel)
    docs = store.q("SELECT id, name, summary FROM documents WHERE (summary IS NULL OR summary='') AND text_len > 0")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for d in docs:
            text = "\n".join(r["text"] for r in store.q("SELECT text FROM chunks WHERE doc_id=? ORDER BY idx LIMIT 2", (d["id"],)))
            if not text:
                continue
            futs[ex.submit(summarise, text, d["name"])] = d["id"]
        for fut in as_completed(futs):
            store.execute("UPDATE documents SET summary=? WHERE id=?", (fut.result(), futs[fut]))
    store.log("index", stats)
    return stats


if __name__ == "__main__":
    import sys

    from ..store.db import store as _store

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else settings.datasets_dir
    def p(ev, d):
        print(ev, json.dumps(d))
    print(index_folder(target, _store(), progress=p))
