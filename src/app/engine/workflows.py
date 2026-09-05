"""Workflow registry: named, multi-step operations the UI can visualise and start.

Each workflow declares its steps up front (so the UI can draw it before it runs) and emits progress events
while running. Last-run summaries persist in kv so the cards show history.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..config import settings
from ..store.db import Store, now

WORKFLOWS: dict[str, dict] = {
    "ingest": {
        "title": "Ingest company documents",
        "summary": "Parse every file, extract checkable claims, embed them for retrieval, detect contradictions, derive first answers and score the buyer's view.",
        "kind": "job",
        "steps": ["Read documents", "Extract claims", "Embed for retrieval", "Detect contradictions", "Derive answers", "Score the buyer's view"],
        "needs": ["openrouter"],
        "accepts_files": True,
    },
    "interview": {
        "title": "Interview: close the gaps",
        "summary": "The analyst asks the highest-priority open questions one at a time, records your answers under your name and re-derives affected questions live.",
        "kind": "chat",
        "steps": ["Rank open items by buyer risk", "Ask one precise question", "Record the fact", "Re-derive & re-score", "Repeat until nothing is open"],
        "needs": ["openrouter"],
    },
    "conflicts": {
        "title": "Resolve contradictions",
        "summary": "Walk through every place where a policy, an audit report and a record disagree, and settle each with a recorded statement.",
        "kind": "chat",
        "steps": ["List open conflicts", "Show both sides with sources", "Ask the resolving question", "Record & resolve", "Re-derive"],
        "needs": ["openrouter"],
    },
    "research": {
        "title": "Outside-in research",
        "summary": "What the buyer's analyst will find on the public web: entity facts, breach news, our own security pages, attestation claims, subprocessor incidents and a live TLS probe.",
        "kind": "job",
        "steps": ["Probe the website", "Look up the company", "Find security & privacy pages", "Check attestation claims", "Search breach news", "Watch subprocessors", "Compile the reputational view"],
        "needs": ["tavily", "openrouter"],
    },
    "buyer_review": {
        "title": "Buyer's-eye review",
        "summary": "Apply the customer's own risk tables to our answers, predict escalations and draft the exception requests their assessor rules ask for.",
        "kind": "job",
        "steps": ["Compute criticality & risk points", "Predict escalations", "Check requested documents", "Draft exception requests", "Rank fixes"],
        "needs": ["openrouter"],
    },
    "export": {
        "title": "Export the package",
        "summary": "Fill the customer's workbook (responses, evidence, reputational tab, exception requests) and refresh the printable report.",
        "kind": "job",
        "steps": ["Apply the provenance guard", "Fill the workbook", "Build the report"],
        "needs": [],
    },
}


def _remember(store: Store, key: str, summary: dict) -> None:
    store.kv_set(f"workflow:{key}:last", {"at": now(), **summary})


def run_ingest(store: Store, emit, root: Path | None = None) -> dict:
    from .pipeline import full_run

    res = full_run(store, root or settings.datasets_dir, progress=emit)
    summary = {"files": res["index"]["files"], "claims": res["index"]["claims"], "embeddings": res.get("embeddings", {}), "conflicts": res["conflicts"], "rating": res["score"]["predicted_rating"]}
    _remember(store, "ingest", summary)
    return summary


def run_research(store: Store, emit) -> dict:
    from ..research import outside_in

    res = outside_in.run_all(store, progress=emit)
    summary = {"modes": [k for k in res if k != "summary"], "discrepancies": len((res.get("summary") or {}).get("discrepancies", []) or [])}
    _remember(store, "research", summary)
    return summary


def run_buyer_review(store: Store, emit) -> dict:
    from .scorer import draft_exceptions, score

    emit("stage", {"stage": "score"})
    sc = score(store)
    emit("stage", {"stage": "exceptions"})
    exc = draft_exceptions(store)
    summary = {"rating": sc["predicted_rating"], "escalations": len(sc["escalations"]), "exceptions": len(exc)}
    _remember(store, "buyer_review", summary)
    return summary


def run_export(store: Store, emit) -> dict:
    from ..export.report import build_report
    from ..export.workbook import fill_workbook

    emit("stage", {"stage": "workbook"})
    path = fill_workbook(store)
    emit("stage", {"stage": "report"})
    (settings.data_dir / "exports").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "exports" / "report.md").write_text(build_report(store))
    summary = {"workbook": path.name, "urls": {"workbook": "/api/export/workbook", "report": "/report"}}
    _remember(store, "export", summary)
    return summary


RUNNERS: dict[str, Callable] = {"ingest": run_ingest, "research": run_research, "buyer_review": run_buyer_review, "export": run_export}


def describe(store: Store) -> list[dict]:
    from .cache import memo

    return memo(store, "workflows", lambda: _describe(store))


def _describe(store: Store) -> list[dict]:
    from .diagrams import diagrams

    keys = {"openrouter": bool(settings.openrouter_api_key), "tavily": bool(settings.tavily_api_key)}
    dg = diagrams(store)
    last = store.kv_prefix("workflow:")
    out = []
    for key, w in WORKFLOWS.items():
        out.append({"key": key, **w, "last_run": last.get(f"workflow:{key}:last"), "diagram": dg.get(key),
                    "available": all(keys.get(n, False) for n in w["needs"]), "missing_keys": [n for n in w["needs"] if not keys.get(n)]})
    return out
