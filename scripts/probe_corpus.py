"""Inspect the built corpus: by file, or by search term."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "index" / "corpus.json"


def show(chunk: dict, width: int = 520) -> None:
    text = chunk["text"].encode("ascii", "replace").decode("ascii")
    print(f"  [{chunk['source_category']}] {chunk['source_file'].split('/')[-1]} :: {chunk['locator']}")
    print(f"    {text[:width]}\n")


def main() -> None:
    chunks = json.loads(CORPUS.read_text(encoding="utf-8"))["chunks"]
    mode = sys.argv[1] if len(sys.argv) > 1 else "file"
    needle = sys.argv[2] if len(sys.argv) > 2 else ""
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    if mode == "file":
        hits = [c for c in chunks if needle.lower() in c["source_file"].lower()]
    else:
        hits = [c for c in chunks if needle.lower() in c["text"].lower()]

    print(f"{len(hits)} chunks matching {mode}='{needle}'\n")
    for c in hits[:limit]:
        show(c)


if __name__ == "__main__":
    main()
