---
name: sync
description: Sync harness changes from main into both campaign worktrees (crypto + stocks). Use when the user says "sync", "sync worktrees", "push harness to worktrees", or has just edited harness files (configs.toml, core/, loop.py, app.py, backtest.py, etc.) on main and wants the worktrees to pick up those changes. Do NOT use this for syncing strategy files — those are excluded by design.
---

# Sync harness → worktrees

The user just edited harness code on `main` and the campaign worktrees still have the old version. `sync_branches.py --mode sync-harness` copies the harness-allowlist files from main into each worktree and commits with `sync-bot` identity on the campaign branch.

Strategy files (`strategies/crypto.py`, `strategies/stocks.py`) are excluded from sync — those belong to the loop.

## Step 1 — Sanity-check the worktrees exist

```bash
git worktree list
```

If the crypto or stocks worktree is missing, STOP. Tell the user to run the `setup` skill first.

## Step 2 — Sync both campaigns

```bash
.venv/bin/python sync_branches.py --mode sync-harness --campaign crypto
.venv/bin/python sync_branches.py --mode sync-harness --campaign stocks
```

(Windows: `.venv\Scripts\python.exe`.)

Each invocation prints JSON listing files copied + the source SHA from main. Surface that to the user verbatim.

If `sync_branches.py` fails:

- **"worktree missing"** → setup skill not run; redirect.
- **"git commit failed"** → most likely git identity issue. Check:
  ```bash
  git config user.email
  ```
  If empty, ask the user to set it (`git config --global user.email "you@example.com"`). Do NOT auto-set it.
- **Anything else** → surface the error verbatim.

## Step 3 — Verify drift is gone

Quick check that a known field matches between main and each worktree:

```bash
REPO="$(pwd)"
WT_BASE="$(dirname "$REPO")/$(basename "$REPO")-worktrees"
diff "$REPO/configs.toml" "$WT_BASE/crypto/configs.toml" && echo "  crypto in sync"
diff "$REPO/configs.toml" "$WT_BASE/stocks/configs.toml" && echo "  stocks in sync"
```

If `diff` shows output, something didn't sync — investigate.

## Step 4 — Report

Print a short summary:

```
✅ harness synced
   crypto worktree → autoresearch/crypto @ <short-sha>
   stocks worktree → autoresearch/stocks @ <short-sha>

Strategy files were NOT touched (by design).
```

## What gets synced

The allowlist lives in `sync_branches.HARNESS_ALLOWLIST` — currently:

```
configs.toml, requirements.txt, pyproject.toml, program.md,
backtest.py, loop.py, scan.py, live_trade.py, sync_branches.py, app.py,
core/*.py
```

If the user adds a new harness file (e.g. `core/new_module.py`), it needs to be added to that allowlist too. Otherwise sync silently won't copy it. Flag this if the user mentions a newly-created harness file isn't propagating.

## Things to NOT do

- Do NOT sync `strategies/<campaign>.py` — those are loop-owned.
- Do NOT sync `results_<campaign>.tsv` — those are campaign-state.
- Do NOT touch worktree git config (user.email, user.name).
- Do NOT auto-commit the changes on main — the user is responsible for committing main themselves.
- Do NOT run promotion (`--mode promote`) as part of sync. That's a separate operation triggered explicitly.
