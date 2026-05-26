# Project: TradingBot v2 — Autoresearch for Trading Strategies
Build a clean, minimal, production-minded autoresearch system from scratch.
Do NOT port the old codebase line-by-line. Preserve the *intent* below.

## Canonical reference: karpathy/autoresearch
Study and mirror the *structure and discipline* of https://github.com/karpathy/autoresearch
— not the ML domain. Karpathy's repo is the template for how autonomous research
should feel: tiny surface area, one mutable file, fixed evaluator, human edits
only `program.md`.

## North star

An LLM mutates **one strategy file per campaign**; a **frozen backtest harness**
scores each mutation on a **validation window**; keep/discard is automatic;
promoted strategies on `main` power **scan alerts** and **optional Alpaca paper
trading**. A **local dashboard** (mandatory, MVP) renders live loop progress,
results, and equity curves. The operator never runs one-off download commands —
configuring symbols in `configs.toml` must fetch all required OHLCV automatically
before any backtest or loop iteration.

## Non-negotiable invariants

1. **Harness immutability** — `backtest.py` math, windows, commission, and
   metric definitions are fixed during a research run. Only `strategies/*.py`
   (on campaign branches) mutate.

2. **One change per iteration** — Loop asks LLM for exactly one experiment;
   degenerate identical output skips backtest.

3. **No look-ahead** — Strategies use only past/current bar data.

4. **Zero manual data steps** — On every `backtest.run()` and every loop
   iteration, prefetch ALL symbols listed in the active campaign config
   (idempotent parquet cache under `data/`). Missing file → fetch. Fetch
   failure → raise loudly, do not silently skip.

5. **Cross-platform** — Windows + Linux + macOS. No dependency on GNU `patch`
   CLI. Apply unified diffs in pure Python (or ship a small tested module).

6. **Config single source of truth** — `configs.toml` on `main` defines per
   campaign: symbols, strategy path, timeframe, val/train/lockbox windows
   (see §Time windows), commission, slippage, min_trades, max_drawdown_limit,
   data_fetch_start, optimize defaults, promotion floors.
   `CAMPAIGN=stocks|crypto` loads profile; env vars override one field only.

7. **Three-branch git model** (keep this — it worked conceptually):
   - `main` — frozen strategies, scan, paper, CI workflows, dashboard, configs.toml only
   - `autoresearch/stocks` — loop mutates `strategies/stocks.py` + results TSV
   - `autoresearch/crypto` — loop mutates `strategies/crypto.py` + results TSV
   - Harness files sync main → campaign; promotion syncs strategy campaign → main
   - Loop NEVER commits to `main`
   - Init script creates these branches + git worktrees if missing

8. **Time windows** — train (reasoning only), val (optimize metric), lockbox
   (promotion only, loop never reads). Formula (defaults; overridable in
   configs.toml): lockbox = last 12 months, val = preceding 18 months,
   train = everything from `data_fetch_start` up to val start. All dates
   resolved at config load and pinned for the run.

9. **Basket mode** — N≥2 symbols → score = mean(per-symbol metric) − penalty·std;
   prefetch and backtest every symbol; missing parquet → fail loudly, never silently skip.

10. **LLM output** — Prefer unified diffs (~tokens); `MAX_OUTPUT_TOKENS` from
    `.env` default 8000; floor 4096 when diff mode enabled; stream to console
    and to dashboard SSE.

11. **Integrity before speed** — Any harness optimization (in-process backtest,
    lower token caps, diff mode) requires automated gates: subprocess vs in-process
    metrics match; diff smoke test passes; `loop.py --iters 1` e2e smoke test.

12. **Dashboard is local-only** — bind to `127.0.0.1:8787`, no auth, no public
    exposure. Same FastAPI process serves API + static React build.

## Core modules (small, testable)

| Module | Responsibility |
|--------|----------------|
| `config.py` | Load configs.toml + env; expose `CampaignConfig` dataclass; resolve date windows |
| `data_fetch.py` | CCXT crypto + yfinance stocks → `data/{asset}/{sym}_{tf}.parquet`; raise on failure |
| `backtest.py` | Load strategy class, prefetch symbols, run val/train/lockbox, emit `---` summary block |
| `loop.py` | OpenRouter LLM call, parse response, apply diff, git commit/reset on campaign branch, append results TSV, DSR benchmark, structured JSONL logging |
| `program.md` | LLM system prompt (output format, rules, mutation menu — see §Mutation menu) |
| `sync_branches.py` | Promotion gate: candidate beats frozen on val + lockbox floors |
| `scan.py` | Frozen strategy on main → watchlist → Discord webhook BUY/SELL |
| `live_trade.py` | Alpaca paper executor reading frozen strategy from main (Phase 2) |
| `strategies/stocks.py`, `strategies/crypto.py` | Baseline strategies (Donchian/EMA style starters) |
| `app.py` | FastAPI app: REST + SSE endpoints + serve built dashboard |
| `dashboard/` | Vite + React + shadcn/ui frontend (see §Dashboard) |

## Dashboard (MVP, mandatory)

**Stack:** FastAPI + Uvicorn (backend) · Vite + React + TypeScript + Tailwind +
shadcn/ui (frontend) · Recharts for equity curves · EventSource (SSE) for live
streaming. One process: `python app.py` serves API on `/api/*` and the built
React bundle on `/`.

**Views (all on one page, no router needed for MVP):**
1. **Campaign selector** — dropdown: `crypto | stocks`
2. **Live console** — SSE-tailed JSONL from `logs/loop_{campaign}.jsonl`,
   color-coded by event type (llm_call, backtest_result, kept, discarded, error)
3. **Results table** — read campaign-branch `results_{campaign}.tsv`, sortable
   by val metric, highlight current best
4. **Equity curve** — render val-period equity for the currently selected row
   (backtest dumps equity series as JSON alongside the TSV row)
5. **Frozen strategy panel** — show last-promoted strategy on `main` with its
   metrics + promotion timestamp
6. **Controls** — Start / Stop loop button (spawns `loop.py` as subprocess on
   the active campaign branch via worktree), iteration count input

**Endpoints:**
- `GET  /api/campaigns` → list with active branch + frozen metrics
- `GET  /api/results/{campaign}` → parsed results TSV
- `GET  /api/equity/{campaign}/{run_id}/{iter}` → equity series JSON
- `POST /api/loop/{campaign}/start` (body: `{iters}`) → returns `run_id`
- `POST /api/loop/{campaign}/stop`
- `GET  /api/stream/{campaign}?replay=1` → SSE stream of logs/loop_{campaign}.jsonl

**Build:** `npm run build` in `dashboard/` produces `dashboard/dist/`; FastAPI
mounts it as static. Init script runs the build once so a fresh clone has a
working UI without Node steps at runtime (Node only required for dashboard dev).

## Metrics & keep rules

- Log per iteration: val_sharpe, sortino, calmar, psr, dsr, max_drawdown,
  win_rate, total_trades, equity_final, equity_series_uri
- Default optimize: `val_sharpe`; env `OPTIMIZE_METRIC` ∈ {sharpe, calmar, dsr}
- **Keep if:** metric > best_so_far AND max_drawdown < `max_drawdown_limit`
  AND total_trades ≥ `min_trades`
- Optional DSR gate via env (`DSR_GATE=true`)
- Crash / 0 trades → reset commit on campaign branch

## Promotion floors (sync_branches.py)

A candidate strategy is promoted from campaign branch → `main` only if ALL hold:
- `candidate.val_metric > frozen.val_metric` (or frozen absent)
- `candidate.lockbox_sharpe > 0` AND `candidate.lockbox_trades ≥ min_trades`
- `candidate.lockbox_max_dd < max_drawdown_limit`
- `candidate.dsr > 0` (deflated against trial count seen on campaign branch)

DSR baseline = zero return; trial count = rows in `results_{campaign}.tsv` at
candidate time. Implement via `psr`-style formula; document in `backtest.py`.

## Mutation menu (program.md)

The LLM system prompt MUST enumerate categories for the "one change per
iteration" rule. Starter menu (extend in program.md):
1. **Indicator parameter** — tune window/threshold of an existing indicator
2. **Entry condition** — add/swap/remove a single entry filter
3. **Exit / risk** — adjust stop, take-profit, or trailing logic
4. **Regime filter** — gate trading on trend/volatility/session
5. **Position sizing** — fixed → vol-target, or adjust risk fraction

LLM must declare which category in its diff header comment, e.g.
`# mutation: indicator_parameter — ema_fast 20 → 14`.

## Scan / Alerts

- `scan.py` runs frozen `main` strategy across watchlist symbols, emits BUY/SELL
- **Webhook:** Discord by default. Env vars: `WEBHOOK_URL` (required),
  `WEBHOOK_KIND` ∈ {discord, slack, generic} default `discord`
- Cron schedule defined in `scan.yml` (e.g., crypto every 1h, stocks at market close)

## CI (GitHub Actions)

- `loop-crypto.yml` / `loop-stocks.yml` → reusable workflow on campaign branch
- `sync_branches.yml` daily promotion + harness sync
- `scan.yml` / `paper.yml` read **main** only
- Campaign workflow: fetch origin/main configs.toml, prefetch ALL symbols, run loop
- CI never builds dashboard (local-dev only)

## Logging

- Structured JSON Lines → `logs/loop_{campaign}.jsonl`
- Per-event schema: `{ts, run_id, iter, event, payload}` where `event` ∈
  {run_start, llm_call, llm_response, diff_applied, backtest_result, kept,
  discarded, error, run_end}
- Dashboard tails this file via SSE; CI uploads as artifact

## Tech stack

- **Backend:** Python 3.11+, venv, `backtesting.py`, pandas, pyarrow,
  openai (OpenRouter base URL), ccxt, yfinance, alpaca-py, fastapi,
  uvicorn, sse-starlette, python-dotenv
- **Frontend:** Node 20+, Vite, React 18, TypeScript, Tailwind, shadcn/ui, Recharts
- **Default LLM:** `minimax/minimax-m2` via OpenRouter
  (override via `OPENROUTER_MODEL` in `.env`)
- Parquet cache gitignored; results TSV + equity JSON committed on campaign branches
- Dashboard build artifacts (`dashboard/dist/`) gitignored; rebuilt by init script

## Explicit anti-patterns (learned from v1 failure)

- Do NOT bundle token-cap reduction + diff mode + in-process backtest in one commit
- Do NOT skip basket symbols when parquet missing
- Do NOT rely on worktree copies of harness without sync story — document one command to sync
- Do NOT hardcode MAX_OUTPUT_TOKENS=800
- Do NOT require operator to run `data_fetch.py` manually for symbols in configs.toml
- Do NOT use GNU patch on Windows
- Do NOT ship a 1400-line single-file HTML dashboard — use the React/shadcn stack above
- Do NOT expose the dashboard beyond `127.0.0.1`
- Do NOT swallow data-fetch errors — raise

## Deliverables for first milestone (MVP)

1. Repo scaffold + `AGENTS.md` documenting branch rules
2. `configs.toml` with `[crypto]` and `[stocks]` profiles (BTC+ETH 4h basket for crypto;
   SPY+QQQ daily for stocks) including resolved date windows + promotion floors
3. `data_fetch` + automatic prefetch in backtest (raises on failure)
4. `backtest.py` with fingerprint-tested harness (subprocess vs in-process parity test)
5. `loop.py` with diff apply + streaming + JSONL logging + 1-iter smoke test
6. `program.md` + starter strategies + mutation menu
7. `app.py` + `dashboard/` React app — all six MVP views working against live data
8. `init.{sh,ps1}` script: create venv, install Python deps, install dashboard deps,
   build dashboard, create campaign branches + worktrees, prefetch all campaign data
9. Tests: `tests/test_diff_apply.py`, `tests/test_backtest_inprocess_parity.py`,
   `tests/test_config_window_resolution.py`, `tests/test_data_fetch_raises.py`,
   `tests/test_promotion_floors.py`
10. README with ONLY automated setup commands — no manual data steps

**Stop condition:** On a fresh clone with only `.env` filled (`OPENROUTER_API_KEY`):
1. `./init.sh` (or `.\init.ps1`) completes without manual intervention
2. `CAMPAIGN=crypto python loop.py --iters 1` runs end-to-end
3. `python app.py` serves the dashboard on `http://127.0.0.1:8787` showing live SSE
   console, results table, and equity curve for the iteration above

## My operating preference

- Local dev on Windows; CI on Ubuntu
- OpenRouter for LLM (default `minimax/minimax-m2`, configurable via `OPENROUTER_MODEL`)
- I watch progress in the local dashboard primarily; terminal secondarily
- Research runs unattended on GitHub Actions for crypto every 6h, stocks daily
- Alpaca paper trading is Phase 2 — scaffold the module, do not wire into MVP stop condition

---

## Quick start

```bash
# 1. Set your OpenRouter key
cp .env.example .env
$EDITOR .env   # set OPENROUTER_API_KEY=...

# 2. Bootstrap via Claude Code — there is no shell script.
#    In Claude Code, just say "set up the project" (or run /setup).
#    The `setup` skill at .claude/skills/setup/SKILL.md handles venv,
#    deps, dashboard build, worktrees, and data prefetch cross-platform.

# 3. Start the dashboard (binds 127.0.0.1:8787)
.venv/bin/python app.py                # macOS / Linux
.venv\Scripts\python.exe app.py        # Windows

# 4. Or run a single loop iteration from the terminal
cd ../TradingBot_AutoResearch-worktrees/crypto
CAMPAIGN=crypto python ../../TradingBot_AutoResearch/loop.py --iters 1

# 5. Verify the full stop condition end-to-end
.venv/bin/python scripts/verify_stop_condition.py
```

### Project layout

```
TradingBot_AutoResearch/
├── core/                       # internal modules (config, backtest_lib, diff_apply, ...)
├── strategies/                 # mutable strategy files + frozen markers on main
├── scripts/                    # verify_stop_condition.py
├── dashboard/                  # Vite + React + Tailwind frontend
├── tests/                      # pytest
├── .github/workflows/          # loop-crypto, loop-stocks, sync, scan, paper, tests
├── .claude/skills/setup/       # AI-driven bootstrap (cross-platform)
├── loop.py app.py scan.py      # CLI entry points
├── sync_branches.py backtest.py live_trade.py
└── configs.toml program.md     # config + LLM system prompt
```
