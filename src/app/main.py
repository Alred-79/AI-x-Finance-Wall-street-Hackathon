"""FastAPI entry point. Run: uvicorn src.app.main:app --reload --port 8000"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .catalog.loader import seed_questions
from .config import ROOT
from .store.db import store

app = FastAPI(title="AI Security Analyst", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            # Never hand the SPA shell to an API caller: an unknown route (typically a stale server) must fail loudly as JSON.
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": f"unknown API route /{path} — is the server up to date?"}, status_code=404)
        if path in ("report", "report.html"):
            return FileResponse(str(DIST / "report.html"))
        target = DIST / path
        return FileResponse(str(target if target.is_file() else DIST / "index.html"))


@app.on_event("startup")
def _startup() -> None:
    s = store()
    seed_questions(s)
    from .config import settings
    from .api.routes import JOBS, _job
    from .engine import workflows as wf
    empty = s.one("SELECT count(*) AS n FROM claims")["n"] == 0
    if empty and settings.auto_index and settings.openrouter_api_key and not any(j["state"] == "running" for j in JOBS.values()):
        _job("workflow:ingest", lambda emit: wf.run_ingest(s, emit))


def run() -> None:
    import uvicorn

    uvicorn.run("src.app.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
