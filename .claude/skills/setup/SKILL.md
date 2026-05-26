---
name: setup
description: Bootstrap the TradingBot AutoResearch project from a fresh clone — creates venv, installs Python + Node deps, builds the dashboard, creates campaign branches + worktrees, and prefetches OHLCV data. Use when the user says "set up", "bootstrap", "install", "initialize", or asks how to get the project running for the first time.
---

# Project setup

You are setting up the TradingBot AutoResearch repo on the user's machine. The project lives at the current working directory. Work step-by-step, run each block of commands, verify the result before moving on, and stop with a clear actionable error if anything goes wrong.

The user does NOT want shell-script bootstrappers — you ARE the bootstrapper. Run commands directly, read their output, decide what to do next.

## Pre-flight: detect the platform

```bash
uname -s
```

Branch on the result:
- `Darwin` → macOS
- `Linux` → Linux
- `MINGW*` / `MSYS*` / `CYGWIN*` → Windows (Git Bash) — prefer PowerShell paths below
- If shell is PowerShell: `$IsWindows` is `True`

For Windows commands, swap:
- `.venv/bin/python` → `.venv\Scripts\python.exe`
- `python3.12` → `py -3.12`
- POSIX `cp` → PowerShell `Copy-Item` or just keep using bash if Git Bash is available

## Step 1 — Find a supported Python interpreter

The project requires Python **3.11 or 3.12** (`backtesting.py` and `pyarrow` wheel compatibility). 3.13+ and 3.10- are not supported.

```bash
# macOS / Linux
command -v python3.12 || command -v python3.11
```

```powershell
# Windows
py -3.12 --version 2>$null; if (-not $?) { py -3.11 --version }
```

If neither exists, STOP and tell the user:
- macOS: `brew install python@3.12`
- Ubuntu/Debian: `sudo apt install python3.12 python3.12-venv`
- Windows: install from https://www.python.org/downloads/ (check "Add to PATH")

## Step 2 — Create the venv (if missing)

```bash
# macOS / Linux
[ -d .venv ] || python3.12 -m venv .venv  # or python3.11
.venv/bin/python --version
```

```powershell
# Windows
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
.venv\Scripts\python.exe --version
```

Verify the printed version is 3.11.x or 3.12.x.

## Step 3 — Install Python dependencies

```bash
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

(Windows: `.venv\Scripts\python.exe ...`)

If any install fails, read the error carefully. Common issues:
- **SSL cert verify failed on a corporate network** — corporate TLS inspection. Try once with `--index-url=https://pypi.org/simple/` and `REQUESTS_CA_BUNDLE=/opt/homebrew/etc/openssl@3/cert.pem` (or `/etc/ssl/cert.pem` on Linux). If still failing, ask the user for their IT-provided CA bundle path.
- **Wheel build failure for `pyarrow` or `backtesting`** — usually means wrong Python version. Verify Step 1.

## Step 4 — Verify Node 20+ for the dashboard

```bash
node --version
```

If absent or below `v20`, STOP and tell the user to install Node 20+ from https://nodejs.org.

## Step 5 — Install dashboard deps + build

```bash
cd dashboard
[ -d node_modules ] || npm install --no-audit --no-fund
npm run build
cd ..
ls dashboard/dist/index.html  # must exist
```

If `npm install` fails on corp network, again it's likely TLS inspection — `npm config set cafile /opt/homebrew/etc/openssl@3/cert.pem` may help.

## Step 6 — Create campaign branches + worktrees

Skip silently if already present (idempotent).

```bash
# 1. Branches
git rev-parse --verify --quiet refs/heads/autoresearch/crypto || git branch autoresearch/crypto
git rev-parse --verify --quiet refs/heads/autoresearch/stocks || git branch autoresearch/stocks

# 2. Worktrees in sibling dir: <repo>/../<basename>-worktrees/<campaign>
REPO="$(pwd)"
WT_BASE="$(dirname "$REPO")/$(basename "$REPO")-worktrees"
mkdir -p "$WT_BASE"
for c in crypto stocks; do
  if ! git worktree list --porcelain | grep -q "$WT_BASE/$c"; then
    git worktree add "$WT_BASE/$c" "autoresearch/$c"
  fi
done
git worktree list
```

Windows PowerShell equivalent for the worktree loop:

```powershell
$repo = (Get-Location).Path
$wtBase = Join-Path (Split-Path $repo -Parent) ((Split-Path $repo -Leaf) + "-worktrees")
New-Item -ItemType Directory -Force -Path $wtBase | Out-Null
foreach ($c in 'crypto','stocks') {
    $path = Join-Path $wtBase $c
    if (-not ((git worktree list --porcelain) -match [regex]::Escape($path))) {
        git worktree add $path "autoresearch/$c"
    }
}
git worktree list
```

**IMPORTANT — do NOT touch git config or hooks.** The previous bootstrap polluted the shared `.git/config` with `loop-bot` identity, which broke human commits on main. The Python-level branch guard in `core/git_ops.assert_campaign_branch` is sufficient — no hooks, no per-worktree identity writes.

## Step 7 — Prefetch OHLCV data

Run this from the repo root (the main branch). It populates `data/crypto/` and `data/stocks/`.

```bash
.venv/bin/python -c "
from core.config import load_campaign
from core.data_fetch import prefetch_all
for camp in ['crypto', 'stocks']:
    cfg = load_campaign(camp)
    paths = prefetch_all(list(cfg.symbols), cfg.asset, cfg.timeframe,
                        cfg.data_fetch_start, exchange=cfg.exchange)
    print(f'  {camp}: {len(paths)} symbol(s) cached')
"
```

If the crypto fetch fails with HTTP 451 (geo-block), the user is hitting an exchange not available in their region. Defaults are Kraken (US-OK). If you see another error, surface it verbatim.

If yfinance fails for stocks with `SSLCertVerificationError`:
- On macOS with Homebrew Python: `export REQUESTS_CA_BUNDLE=/opt/homebrew/etc/openssl@3/cert.pem` then retry the command.
- Don't add this to the codebase — just run it inline.

If yfinance fails with empty results / scraping errors, try upgrading: `.venv/bin/python -m pip install -U yfinance`.

## Step 8 — Run the test suite

```bash
.venv/bin/python -m pytest -q
```

Expect ~78 tests to pass. If any fail, surface the failure to the user before declaring setup complete.

## Step 9 — Tell the user how to use it

After everything succeeds, print this summary:

```
✅ setup complete.

Next steps:
  1. Confirm OPENROUTER_API_KEY is set in .env
  2. Start the dashboard:   .venv/bin/python app.py
                            → http://127.0.0.1:8787
  3. Or run a loop:         cd ../<repo>-worktrees/crypto
                            CAMPAIGN=crypto python /path/to/repo/loop.py --iters 1
```

## Re-running this skill

This skill is idempotent: every step checks if the work is already done. Safe to re-run after pulling new code.

## Things to NOT do

- Do NOT create `init.sh` / `init.ps1` / `scripts/bootstrap.py`. Those were removed intentionally; the user wants the agent to drive setup.
- Do NOT write to git config (user.email, user.name) at the repo or worktree level.
- Do NOT install pre-commit hooks.
- Do NOT export SSL env vars permanently in shell rc files. Set them inline for the command that needs them and explain.
- Do NOT commit changes unless the user explicitly asks.
