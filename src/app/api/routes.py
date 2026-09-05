"""HTTP API for the analyst UI."""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from ..agent.loop import Agent
from ..catalog.loader import get_catalog
from ..config import settings
from ..engine.conflicts import detect_conflicts, open_conflicts_for
from ..engine.derive import derive_all, question_states
from ..engine.pipeline import full_run, record_user_fact, resolve_conflict
from ..engine.planner import open_items
from ..engine.scorer import draft_exceptions, score
from ..engine.search import index_for
from ..engine.overview import overview
from ..engine import workflows as wf
from ..engine.embeddings import index_missing
from ..export.report import build_report, report_data
from ..export.workbook import fill_workbook
from ..ingest.indexer import index_folder
from ..research import outside_in
from ..store.db import loads, now, store

router = APIRouter(prefix="/api")
JOBS: dict[str, dict[str, Any]] = {}


def _job(kind: str, fn) -> dict:
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "kind": kind, "state": "running", "events": [], "result": None, "error": None, "started_at": now()}
    JOBS[jid] = job

    def emit(ev, data):
        job["events"].append({"ev": ev, **(data or {})})
        job["events"] = job["events"][-200:]

    def run():
        try:
            job["result"] = fn(emit)
            job["state"] = "done"
        except Exception as e:  # noqa: BLE001
            job["error"] = str(e)
            job["state"] = "error"
        job["finished_at"] = now()

    threading.Thread(target=run, daemon=True).start()
    return job


@router.get("/status")
def status():
    from ..engine.cache import memo

    s = store()
    body = memo(s, "status", lambda: _status_body(s), ttl=10)
    return {**body, "jobs": [{k: v for k, v in j.items() if k != "events"} | {"last_event": (j["events"] or [None])[-1]} for j in JOBS.values() if j["state"] == "running"]}


def _status_body(s) -> dict:
    counts = s.counts()
    kv = s.kv_prefix("last_")
    sc = kv.get("last_score") or {}
    return {
        "vendor": {"legal_name": settings.vendor_legal_name, "brand": settings.vendor_brand, "domain": settings.vendor_domain},
        "documents": counts["documents"], "claims": counts["claims"], "indexed": counts["claims"] > 0,
        "last_run": kv.get("last_run"), "last_research": kv.get("last_research"),
        "counts": sc.get("counts"), "predicted_rating": sc.get("predicted_rating"),
        "inherent_points": sc.get("inherent_points"), "max_inherent_points": sc.get("max_inherent_points"),
        "escalations": len(sc.get("escalations", [])), "vendor_criticality": sc.get("vendor_criticality"),
        "keys": {"openrouter": bool(settings.openrouter_api_key), "tavily": bool(settings.tavily_api_key)},
        "store": {"dialect": s.dialect, "pgvector": s.has_pgvector, "embeddings": counts["embeddings"], "provider": settings.embedding_provider},
    }


@router.post("/run")
def run():
    if not settings.openrouter_api_key:
        raise HTTPException(400, "OPENROUTER_API_KEY not set")
    return _job("index", lambda emit: full_run(store(), progress=emit))


@router.post("/research")
def research(mode: str = "all"):
    if not settings.tavily_api_key and mode != "live_probe":
        raise HTTPException(400, "TAVILY_API_KEY not set")
    def fn(emit):
        if mode == "all":
            return outside_in.run_all(store(), progress=emit)
        if mode not in outside_in.MODES:
            raise ValueError(f"unknown mode {mode}")
        res = outside_in.MODES[mode](store())
        return json.loads(json.dumps(res, default=str))
    return _job(f"research:{mode}", fn)


@router.get("/jobs/{jid}")
def job(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "job not found")
    return {**j, "events": j["events"][-60:], "result": json.loads(json.dumps(j["result"], default=str)) if j["state"] == "done" else None}


@router.get("/questions")
def questions():
    return question_states(store())


@router.get("/questions/{qid}")
def question(qid: str):
    s = next((x for x in question_states(store()) if x["qid"] == qid), None)
    if not s:
        raise HTTPException(404, "unknown question")
    s["conflicts"] = open_conflicts_for(store(), s["controls"])
    ph = ",".join("?" for _ in s["controls"])
    s["all_claims"] = store().q(
        f"SELECT c.id, c.control, c.attribute, c.value, c.statement, c.excerpt, c.authority, c.observed_at, d.name AS doc, d.doc_type, d.is_template "
        f"FROM claims c JOIN documents d ON d.id=c.doc_id WHERE c.control IN ({ph}) ORDER BY c.authority DESC, c.id", s["controls"])
    s["statements"] = store().q(f"SELECT * FROM user_statements WHERE control IN ({ph}) OR qids LIKE ? ORDER BY id", [*s["controls"], f'%"{qid}"%'])
    return s


@router.get("/conflicts")
def conflicts():
    from ..engine.overview import conflict_rows

    return conflict_rows(store())


class Resolve(BaseModel):
    resolution: str
    speaker: str = "Employee"
    role: str = ""


@router.post("/conflicts/{cid}/resolve")
def resolve(cid: int, body: Resolve):
    return resolve_conflict(store(), cid, body.resolution, f"{body.speaker} ({body.role})" if body.role else body.speaker)


class Fact(BaseModel):
    control: str
    attribute: str
    value: str
    statement: str
    speaker: str = "Employee"
    role: str = "CTO"
    qids: list[str] | None = None


@router.post("/facts")
def facts(body: Fact):
    if body.control not in get_catalog().controls:
        raise HTTPException(400, f"unknown control {body.control}")
    return record_user_fact(store(), **body.model_dump())


@router.get("/facts")
def list_facts():
    return store().q("SELECT * FROM user_statements ORDER BY id DESC")


@router.get("/open-items")
def open_items_route(role: str | None = None, limit: int = 20):
    return open_items(store(), role)[:limit]


@router.get("/score")
def get_score(vendor_type: str = "Technology", access: str = "Network&Data"):
    return score(store(), vendor_type, access)


@router.post("/score/exceptions")
def exceptions():
    return _job("exceptions", lambda emit: draft_exceptions(store()))


@router.get("/score/exceptions")
def get_exceptions():
    return store().kv_get("exceptions") or []


@router.get("/reputational")
def reputational():
    return {"summary": store().kv_get("reputational"), "findings": store().q("SELECT * FROM external_findings ORDER BY id DESC LIMIT 200")}


@router.get("/documents")
def documents():
    rows = store().q("SELECT d.*, (SELECT count(*) FROM claims c WHERE c.doc_id=d.id) AS n_claims FROM documents d ORDER BY authority DESC, name")
    return rows


@router.get("/documents/{doc_id}/claims")
def document_claims(doc_id: int):
    return store().q("SELECT * FROM claims WHERE doc_id=? ORDER BY id", (doc_id,))


@router.get("/search")
def search(q: str, k: int = 10):
    return index_for(store()).search(q, k=k)


class ChatIn(BaseModel):
    session: str
    message: str
    speaker: str = "Employee"
    role: str = "CTO"


@router.post("/chat")
def chat(body: ChatIn):
    if not settings.openrouter_api_key:
        raise HTTPException(400, "OPENROUTER_API_KEY not set")
    agent = Agent(store(), body.session, body.speaker, body.role)
    return agent.run(body.message)


@router.post("/chat/stream")
def chat_stream(body: ChatIn):
    """Server-sent events: status / tool / delta / reset / done / error."""
    if not settings.openrouter_api_key:
        raise HTTPException(400, "OPENROUTER_API_KEY not set")
    agent = Agent(store(), body.session, body.speaker, body.role)

    def gen():
        for ev in agent.run_stream(body.message):
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@router.get("/chat/{session}")
def history(session: str):
    rows = store().q("SELECT role, content, meta, created_at FROM messages WHERE session=? ORDER BY id", (session,))
    for r in rows:
        r["meta"] = loads(r["meta"], {})
    return rows


@router.get("/sessions")
def sessions():
    return store().q("SELECT session, count(*) n, min(created_at) started, max(created_at) last FROM messages GROUP BY session ORDER BY last DESC")


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    up = settings.data_dir / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        dest = up / Path(f.filename or "upload").name
        with dest.open("wb") as fh:
            shutil.copyfileobj(f.file, fh)
        saved.append(dest.name)

    def fn(emit):
        s = store()
        stats = index_folder(up, s, progress=emit)
        emit("stage", {"stage": "embed"})
        emb = index_missing(s, progress=emit)
        emit("stage", {"stage": "conflicts"})
        n = detect_conflicts(s)
        emit("stage", {"stage": "derive", "total": 66})
        counts = derive_all(s, progress=emit)
        emit("stage", {"stage": "score"})
        score(s)
        return {"index": stats, "embeddings": emb, "conflicts": n, "derive": counts}

    return {"saved": saved, "job": _job("workflow:ingest", fn)}


@router.get("/data/overview")
def data_overview():
    return overview(store())


@router.get("/workflows")
def workflows():
    running = [{k: v for k, v in j.items() if k != "events"} for j in JOBS.values() if j["state"] == "running"]
    return {"workflows": wf.describe(store()), "running": running}


@router.post("/workflows/{key}/start")
def start_workflow(key: str):
    if key not in wf.WORKFLOWS:
        raise HTTPException(404, "unknown workflow")
    w = wf.WORKFLOWS[key]
    missing = [n for n in w["needs"] if not {"openrouter": settings.openrouter_api_key, "tavily": settings.tavily_api_key}.get(n)]
    if missing:
        raise HTTPException(400, f"missing keys: {', '.join(missing)}")
    if w["kind"] == "chat":
        prompt = {"interview": "Let's close the gaps. Ask me the single most important open question, and tell me in one clause why it matters.",
                  "conflicts": "Let's resolve the contradictions. Show me the most important open conflict with both sides and ask me the resolving question."}[key]
        return {"kind": "chat", "prompt": prompt}
    if any(j["state"] == "running" and j["kind"] == f"workflow:{key}" for j in JOBS.values()):
        raise HTTPException(409, "already running")
    runner = wf.RUNNERS[key]
    return {"kind": "job", **_job(f"workflow:{key}", lambda emit: runner(store(), emit))}


@router.get("/export/workbook")
def export_workbook():
    p = fill_workbook(store())
    return FileResponse(str(p), filename=p.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/report")
def report_json():
    return report_data(store())


@router.get("/export/report", response_class=PlainTextResponse)
def export_report():
    return build_report(store())


@router.post("/reset")
def reset(keep_statements: bool = True):
    s = store()
    if keep_statements:
        s.reset_derived()
    else:
        s.wipe()
    return {"ok": True}


# ---------------------------------------------------------------------------- dashboards (query-driven charts)
from ..engine import dashboards as dash  # noqa: E402


class DashboardItemIn(BaseModel):
    spec: dict
    source: str = "chat"
    title: str | None = None


class DashboardOrder(BaseModel):
    ids: list[int]


@router.get("/dashboard")
def dashboard():
    return {"items": dash.list_items(store()), "live_sources": list(dash.LIVE_SOURCES)}


@router.post("/dashboard/items")
def dashboard_add(body: DashboardItemIn):
    try:
        return dash.add_item(store(), body.spec, body.source, body.title)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/dashboard/items/{item_id}")
def dashboard_delete(item_id: int):
    if not dash.delete_item(store(), item_id):
        raise HTTPException(404, "dashboard item not found")
    return {"ok": True}


@router.get("/dashboard/items/{item_id}/live")
def dashboard_live(item_id: int):
    item = dash.get_item(store(), item_id)
    if not item:
        raise HTTPException(404, "dashboard item not found")
    return {**item, "spec": dash.resolve_live(item["spec"], store())}


@router.post("/dashboard/reorder")
def dashboard_reorder(body: DashboardOrder):
    return {"items": dash.reorder(store(), body.ids)}


@router.get("/dashboard/metrics/{name}")
def dashboard_metrics(name: str):
    try:
        return dash.metrics(store(), name)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'"))
