"""Pre-index the company data into the configured store (SQLite or Neon/Postgres).

    python -m src.app.index               # datasets/ from .env
    python -m src.app.index path/to/dir   # any folder

Safe to re-run: unchanged files are skipped, embeddings are only computed for new claims/chunks.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .config import settings
from .engine.workflows import run_ingest
from .store.db import store


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else settings.datasets_dir
    s = store()
    print(f"store: {s.dialect}{' + pgvector' if s.has_pgvector else ''} · embeddings: {settings.embedding_provider} ({settings.embedding_model})")
    t0 = time.time()
    last = {"": 0}

    def emit(ev, data):
        line = f"{ev} {json.dumps(data, default=str)}"
        if ev in ("stage", "extracting", "done", "error") or time.time() - last[""] > 2:
            print(line[:160])
            last[""] = time.time()

    res = run_ingest(s, emit, root)
    print(json.dumps(res, indent=1, default=str))
    print(f"counts: {s.counts()} · {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
