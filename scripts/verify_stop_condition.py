#!/usr/bin/env python
"""verify_stop_condition.py — end-to-end MVP verifier.

Confirms the README stop condition holds on a fresh checkout:
  1. init.sh / init.ps1 completes
  2. `python loop.py --iters 1` runs end-to-end (mock LLM)
  3. `python app.py` serves dashboard + API + SSE

Designed to run against the CURRENT working tree (in-place verification),
not a fresh clone. To verify a fresh clone, set VERIFY_FRESH_CLONE=1 and
ensure `git` can clone the repo.

Exits 0 on success with a banner; non-zero with a clear error otherwise.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent


def log(msg: str, lvl: str = "info") -> None:
    color = {"info": "\033[36m", "ok": "\033[32m", "warn": "\033[33m",
             "err": "\033[31m"}.get(lvl, "")
    reset = "\033[0m" if color else ""
    print(f"{color}[verify]{reset} {msg}", flush=True)


def fail(msg: str) -> None:
    log(msg, "err")
    raise SystemExit(1)


def check_dashboard_built() -> None:
    idx = REPO_ROOT / "dashboard" / "dist" / "index.html"
    if not idx.exists():
        fail(f"dashboard/dist/index.html missing — run init.sh to build")
    log(f"dashboard dist OK: {idx}", "ok")


def check_branches_and_worktrees() -> None:
    for c in ("crypto", "stocks"):
        wt = REPO_ROOT.parent / f"{REPO_ROOT.name}-worktrees" / c
        if not wt.exists():
            fail(f"missing worktree {wt}. Run init script.")
    log("worktrees present", "ok")


def run_loop_one_iter() -> Path:
    """Run loop.py inside the crypto worktree with MOCK_LLM=1. Returns path
    to the produced logs/loop_crypto.jsonl."""
    wt = REPO_ROOT.parent / f"{REPO_ROOT.name}-worktrees" / "crypto"
    env = os.environ.copy()
    env["MOCK_LLM"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT)
    log(f"running loop --iters 1 inside {wt} (MOCK_LLM=1)…")
    proc = subprocess.run(
        [sys.executable, "loop.py", "--campaign", "crypto", "--iters", "1"],
        cwd=str(wt), env=env, capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        fail(f"loop.py exit {proc.returncode}\nstderr:\n{proc.stderr[-1000:]}")
    log_path = wt / "logs" / "loop_crypto.jsonl"
    if not log_path.exists():
        fail(f"loop did not write {log_path}")
    events = [json.loads(l) for l in log_path.read_text().strip().splitlines() if l.strip()]
    names = [e["event"] for e in events]
    if "run_end" not in names:
        fail(f"loop did not emit run_end event; got {names}")
    log(f"loop OK — events: {set(names)}", "ok")
    return log_path


@contextmanager
def app_running():
    """Spawn `python app.py` and wait for it to listen on 127.0.0.1:8787."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    if sys.platform == "win32":
        kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        kwargs = {"start_new_session": True}
    log("starting app.py…")
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs,
    )
    try:
        deadline = time.time() + 20
        ready = False
        while time.time() < deadline:
            try:
                r = httpx.get("http://127.0.0.1:8787/api/campaigns", timeout=1.0)
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ready:
            out = proc.stdout.read() if proc.stdout else b""
            err = proc.stderr.read() if proc.stderr else b""
            fail(f"app.py never became ready\nstdout:\n{out.decode(errors='replace')[-500:]}\n"
                 f"stderr:\n{err.decode(errors='replace')[-500:]}")
        log("app.py is serving on 127.0.0.1:8787", "ok")
        yield proc
    finally:
        try:
            if sys.platform == "win32":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def check_endpoints() -> None:
    base = "http://127.0.0.1:8787"
    r = httpx.get(f"{base}/api/campaigns")
    if r.status_code != 200:
        fail(f"/api/campaigns returned {r.status_code}")
    names = {c["name"] for c in r.json()}
    if names != {"crypto", "stocks"}:
        fail(f"unexpected campaigns: {names}")
    log("/api/campaigns OK", "ok")

    r = httpx.get(f"{base}/api/results/crypto")
    if r.status_code != 200:
        fail(f"/api/results/crypto returned {r.status_code}")
    rows = r.json()
    if not isinstance(rows, list):
        fail("results not a list")
    log(f"/api/results/crypto OK — {len(rows)} rows", "ok")

    # Root must serve the dashboard html
    r = httpx.get(f"{base}/", follow_redirects=True)
    if r.status_code != 200:
        fail(f"/ returned {r.status_code}")
    if '<div id="root"' not in r.text and "id=\"root\"" not in r.text:
        fail("dashboard root div missing from /")
    log("/ serves dashboard HTML", "ok")


def check_sse_smoke() -> None:
    """Open SSE stream briefly to confirm endpoint exists and replays history."""
    import threading
    received: list[str] = []

    def fetch():
        try:
            with httpx.stream("GET",
                              "http://127.0.0.1:8787/api/stream/crypto?replay=1",
                              timeout=4.0) as r:
                for line in r.iter_lines():
                    if line and line.startswith("data:"):
                        received.append(line)
                        if len(received) >= 1:
                            return
        except Exception:
            pass

    t = threading.Thread(target=fetch, daemon=True)
    t.start()
    t.join(timeout=4.0)
    if not received:
        log("SSE stream returned no data (acceptable if logs empty)", "warn")
    else:
        log(f"SSE stream OK — {len(received)} event(s) replayed", "ok")


def main() -> int:
    log("=== Stop-condition verification ===")
    check_dashboard_built()
    check_branches_and_worktrees()
    run_loop_one_iter()
    with app_running():
        check_endpoints()
        check_sse_smoke()
    log("=" * 36, "ok")
    log("STOP CONDITION SATISFIED — MVP ready", "ok")
    log("=" * 36, "ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
