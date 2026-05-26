#!/usr/bin/env python
"""bootstrap.py — single source of truth for repo bootstrap.

Called by init.sh / init.ps1 AFTER venv exists and pip install succeeded.
Steps (all idempotent):
  1. Verify Node is installed (>=20).
  2. npm install + npm run build in dashboard/.
  3. Create autoresearch/crypto + autoresearch/stocks branches if missing.
  4. Create git worktrees in <repo>/../<basename>-worktrees/{crypto,stocks}.
  5. Configure loop-bot identity inside each worktree.
  6. Install pre-commit hooks in main repo + each worktree.
  7. Prefetch all symbols for both campaigns (idempotent).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_NODE_MAJOR = 20

CAMPAIGNS = ["crypto", "stocks"]


def log(msg: str, level: str = "info") -> None:
    color = {"info": "\033[36m", "ok": "\033[32m", "warn": "\033[33m",
             "err": "\033[31m"}.get(level, "")
    reset = "\033[0m" if color else ""
    print(f"{color}[bootstrap]{reset} {msg}", flush=True)


def run(args: list[str], cwd: Path = REPO_ROOT, check: bool = True,
        env: dict | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(args, cwd=str(cwd), capture_output=True,
                          text=True, env=env)
    if check and proc.returncode != 0:
        log(f"FAILED: {' '.join(args)}", "err")
        log(proc.stderr.strip() or proc.stdout.strip(), "err")
        raise SystemExit(1)
    return proc


def check_node() -> None:
    if shutil.which("node") is None:
        log("Node.js not found. Install Node 20+ from https://nodejs.org", "err")
        raise SystemExit(1)
    v = run(["node", "--version"]).stdout.strip().lstrip("v")
    major = int(v.split(".")[0])
    if major < REQUIRED_NODE_MAJOR:
        log(f"Node {v} too old; need >={REQUIRED_NODE_MAJOR}", "err")
        raise SystemExit(1)
    log(f"node {v}", "ok")


def build_dashboard() -> None:
    log("installing dashboard deps + building (this may take a minute)…")
    dash = REPO_ROOT / "dashboard"
    nm = dash / "node_modules"
    pkg_lock = dash / "package-lock.json"
    nm_lock = nm / ".package-lock.json"
    need_install = (not nm.exists()) or (pkg_lock.exists() and (not nm_lock.exists() or
                   pkg_lock.stat().st_mtime > nm_lock.stat().st_mtime))
    if need_install:
        run(["npm", "install", "--no-audit", "--no-fund"], cwd=dash)
        log("npm install done", "ok")
    else:
        log("dashboard deps already installed", "ok")
    run(["npm", "run", "build"], cwd=dash)
    log("dashboard built → dashboard/dist/", "ok")


def branch_exists(name: str) -> bool:
    proc = run(["git", "rev-parse", "--verify", "--quiet",
                f"refs/heads/{name}"], check=False)
    return proc.returncode == 0


def create_branches() -> None:
    for c in CAMPAIGNS:
        b = f"autoresearch/{c}"
        if branch_exists(b):
            log(f"branch {b} exists", "ok")
            continue
        # Create from main (HEAD)
        run(["git", "branch", b])
        log(f"created branch {b}", "ok")


def worktree_dir(campaign: str) -> Path:
    return REPO_ROOT.parent / f"{REPO_ROOT.name}-worktrees" / campaign


def worktree_registered(path: Path) -> bool:
    proc = run(["git", "worktree", "list", "--porcelain"], check=True)
    return str(path.resolve()) in proc.stdout


def create_worktrees() -> None:
    for c in CAMPAIGNS:
        path = worktree_dir(c)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if worktree_registered(path):
                log(f"worktree {path.name} present", "ok")
                continue
            log(f"path {path} exists but is not a registered worktree. "
                f"Move/remove it and rerun.", "err")
            raise SystemExit(1)
        run(["git", "worktree", "add", str(path), f"autoresearch/{c}"])
        log(f"worktree {path.name} → autoresearch/{c}", "ok")


def configure_worktree_identity() -> None:
    for c in CAMPAIGNS:
        wt = worktree_dir(c)
        run(["git", "config", "user.name", "loop-bot"], cwd=wt)
        run(["git", "config", "user.email", "loop@autoresearch.local"], cwd=wt)
    log("loop-bot identity configured per worktree", "ok")


PRE_COMMIT_HOOK = """#!/bin/sh
# Block loop-bot commits to main
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
email="$(git config user.email)"
if [ "$branch" = "main" ] && [ "$email" = "loop@autoresearch.local" ]; then
  echo "pre-commit: refusing loop-bot commit to main." >&2
  exit 1
fi
exit 0
"""


def install_hook(repo_dir: Path) -> None:
    """Install pre-commit hook in the .git dir for a repo OR worktree.

    For worktrees, hooks live in `.git/worktrees/<name>/hooks` per Git's design;
    install in BOTH the per-worktree dir AND the shared dir for safety.
    """
    # Resolve the actual git dir for this path
    proc = run(["git", "rev-parse", "--git-path", "hooks"], cwd=repo_dir, check=True)
    hooks_dir = (repo_dir / proc.stdout.strip()).resolve()
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "pre-commit"
    hook_path.write_text(PRE_COMMIT_HOOK, encoding="utf-8")
    try:
        hook_path.chmod(0o755)
    except Exception:
        pass


def install_hooks() -> None:
    install_hook(REPO_ROOT)
    for c in CAMPAIGNS:
        install_hook(worktree_dir(c))
    log("pre-commit hooks installed", "ok")


def prefetch_data() -> None:
    log("prefetching OHLCV (this may take a few minutes on first run)…")
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from core.config import load_campaign
        from core.data_fetch import prefetch_all
    except Exception as e:
        log(f"cannot import data modules: {e}", "err")
        raise SystemExit(1)
    skip_prefetch = os.environ.get("SKIP_PREFETCH", "").lower() in {"1", "true", "yes"}
    if skip_prefetch:
        log("SKIP_PREFETCH set — skipping data fetch", "warn")
        return
    for c in CAMPAIGNS:
        try:
            cfg = load_campaign(c)
            paths = prefetch_all(list(cfg.symbols), cfg.asset, cfg.timeframe,
                                  cfg.data_fetch_start, exchange=cfg.exchange)
            log(f"  {c}: {len(paths)} symbol(s) ready", "ok")
        except Exception as e:
            log(f"  {c}: {e}", "err")
            log("hint: set SKIP_PREFETCH=1 to bootstrap without data (e.g. on CI without net)", "warn")
            raise SystemExit(1)


def main() -> int:
    log("=== TradingBot AutoResearch bootstrap ===")
    log(f"repo: {REPO_ROOT}")

    # Sanity: must be inside a git repo
    if not (REPO_ROOT / ".git").exists():
        # Initialize on demand for fresh-clone fork case where init was deferred
        log("no .git dir — initializing a fresh git repo at root")
        run(["git", "init", "-b", "main"])
        run(["git", "add", "-A"])
        # Ensure user identity exists (best-effort)
        proc_email = run(["git", "config", "user.email"], check=False)
        if proc_email.returncode != 0 or not proc_email.stdout.strip():
            run(["git", "config", "user.email", "human@local"])
            run(["git", "config", "user.name", "human"])
        run(["git", "commit", "-m", "initial bootstrap commit"], check=False)

    check_node()
    build_dashboard()
    create_branches()
    create_worktrees()
    configure_worktree_identity()
    install_hooks()
    prefetch_data()

    log("=== bootstrap complete ===", "ok")
    log("next steps:", "ok")
    log("  1. ensure .env has OPENROUTER_API_KEY", "ok")
    log("  2. start dashboard:  python app.py", "ok")
    log("  3. or run loop:      CAMPAIGN=crypto python loop.py --iters 1", "ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
