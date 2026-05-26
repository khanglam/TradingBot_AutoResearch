#!/usr/bin/env python
"""app.py — FastAPI backend serving the dashboard + REST + SSE.

Runs from `main` (the repo root). Reads campaign data from sibling worktrees
when needed. Local-only: binds 127.0.0.1:8787.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from core import process_registry
from core.config import load_campaign
from core.sse_tail import tail_file
from sync_branches import worktree_path, load_frozen_marker

REPO_ROOT = Path(__file__).resolve().parent
DASHBOARD_DIST = REPO_ROOT / "dashboard" / "dist"

load_dotenv(REPO_ROOT / ".env")
app = FastAPI(title="TradingBot AutoResearch Dashboard")


# ---------------- Helpers ----------------

def _campaign_paths(campaign: str) -> dict:
    wt = worktree_path(campaign, REPO_ROOT)
    return {
        "worktree": wt,
        "tsv": wt / f"results_{campaign}.tsv",
        "log": wt / "logs" / f"loop_{campaign}.jsonl",
    }


def _read_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lock = FileLock(str(path) + ".lock", timeout=5)
    with lock:
        with open(path, "r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f, delimiter="\t"))


# ---------------- API models ----------------

class StartLoopRequest(BaseModel):
    iters: int = 1


# ---------------- Endpoints ----------------

@app.get("/api/campaigns")
def list_campaigns():
    out = []
    for name in ["crypto", "stocks"]:
        try:
            cfg = load_campaign(name)
            frozen = load_frozen_marker(name, REPO_ROOT)
            stat = process_registry.status(name)
            paths = _campaign_paths(name)
            out.append({
                "name": name,
                "asset": cfg.asset,
                "symbols": list(cfg.symbols),
                "timeframe": cfg.timeframe,
                "branch": f"autoresearch/{name}",
                "worktree": str(paths["worktree"]),
                "frozen": frozen,
                "running": stat,
            })
        except Exception as e:
            out.append({"name": name, "error": str(e)})
    return out


@app.get("/api/results/{campaign}")
def get_results(campaign: str):
    if campaign not in {"crypto", "stocks"}:
        raise HTTPException(status_code=404, detail="unknown campaign")
    paths = _campaign_paths(campaign)
    rows = _read_tsv(paths["tsv"])
    return rows


@app.get("/api/equity/{campaign}/{run_id}/{iter_n}")
def get_equity(campaign: str, run_id: str, iter_n: int):
    if campaign not in {"crypto", "stocks"}:
        raise HTTPException(status_code=404, detail="unknown campaign")
    wt = worktree_path(campaign, REPO_ROOT)
    eq_path = wt / "equity" / f"{campaign}_{run_id}_{iter_n}.json"
    if not eq_path.exists():
        raise HTTPException(status_code=404, detail="equity file not found")
    return json.loads(eq_path.read_text(encoding="utf-8"))


@app.post("/api/loop/{campaign}/start")
def start_loop_endpoint(campaign: str, req: StartLoopRequest):
    if campaign not in {"crypto", "stocks"}:
        raise HTTPException(status_code=404, detail="unknown campaign")
    if req.iters < 1 or req.iters > 1000:
        raise HTTPException(status_code=400, detail="iters must be 1..1000")
    paths = _campaign_paths(campaign)
    if not paths["worktree"].exists():
        raise HTTPException(
            status_code=409,
            detail=f"worktree missing: {paths['worktree']}. Run init script.",
        )
    run_id = uuid.uuid4().hex[:12]
    try:
        rl = process_registry.start_loop(campaign, run_id,
                                         cwd=paths["worktree"],
                                         iters=req.iters)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"campaign": campaign, "run_id": rl.run_id, "pid": rl.pid}


@app.post("/api/loop/{campaign}/stop")
def stop_loop_endpoint(campaign: str):
    stopped = process_registry.stop_loop(campaign)
    return {"campaign": campaign, "stopped": stopped}


@app.get("/api/stream/{campaign}")
async def stream_logs(campaign: str, replay: int = 0):
    if campaign not in {"crypto", "stocks"}:
        raise HTTPException(status_code=404, detail="unknown campaign")
    paths = _campaign_paths(campaign)
    log_path = paths["log"]

    async def event_source():
        async for sse_line in tail_file(log_path, replay=bool(replay)):
            # tail_file already formats as "data: ...\n\n" or ":keepalive\n\n"
            yield sse_line

    return EventSourceResponse(event_source())


# ---------------- Static / fallback ----------------

_NOT_BUILT_HTML = """<!doctype html>
<html><head><title>Dashboard not built</title>
<style>body{font-family:system-ui;max-width:560px;margin:80px auto;padding:0 20px;color:#222}
code{background:#f4f4f4;padding:2px 6px;border-radius:4px}</style></head>
<body>
<h2>Dashboard not built</h2>
<p>The React dashboard hasn't been built yet.</p>
<p>Run the init script to bootstrap:</p>
<pre><code>./init.sh   # macOS/Linux
pwsh -File ./init.ps1   # Windows</code></pre>
<p>Or manually:</p>
<pre><code>cd dashboard &amp;&amp; npm install &amp;&amp; npm run build</code></pre>
<p>API endpoints (e.g. <code>/api/campaigns</code>) still work.</p>
</body></html>
"""

if DASHBOARD_DIST.exists() and (DASHBOARD_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=DASHBOARD_DIST / "assets"), name="assets")

    @app.get("/")
    def root():
        return FileResponse(DASHBOARD_DIST / "index.html")

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        # Serve index.html for any unknown path (SPA-style)
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = DASHBOARD_DIST / path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DASHBOARD_DIST / "index.html")
else:
    @app.get("/")
    def not_built_root():
        return HTMLResponse(_NOT_BUILT_HTML)


def main() -> None:
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8787, reload=False, log_level="info")


if __name__ == "__main__":
    main()
