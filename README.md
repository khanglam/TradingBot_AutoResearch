# Project: TradingBot v2 — Autoresearch for Trading Strategies

Build a clean, minimal, production-minded autoresearch system from scratch.
Do NOT port the old codebase line-by-line. Preserve the *intent* below.

## North star

An LLM mutates **one strategy file per campaign**; a **frozen backtest harness**
scores each mutation on a **validation window**; keep/discard is automatic;
promoted strategies on `main` power **scan alerts** and **optional Alpaca paper
trading**. The operator never runs one-off download commands — configuring
symbols in `configs.toml` must fetch all required OHLCV automatically before
any backtest or loop iteration.

## Non-negotiable invariants

1. **Harness immutability** — `backtest.py` math, windows, commission, and
   metric definitions are fixed during a research run. Only `strategies/*.py`
   (on campaign branches) mutate.

2. **One change per iteration** — Loop asks LLM for exactly one experiment;
   degenerate identical output skips backtest.

3. **No look-ahead** — Strategies use only past/current bar data.

4. **Zero manual data steps** — On every `backtest.run()` and every loop
   iteration, prefetch ALL symbols listed in the active campaign config
   (idempotent parquet cache under `data/`). Missing file → fetch, never skip.

5. **Cross-platform** — Windows + Linux + macOS. No dependency on GNU `patch`
   CLI. Apply unified diffs in pure Python (or ship a small tested module).

6. **Config single source of truth** — `configs.toml` on `main` defines per
   campaign: symbols, strategy path, val/train/lockbox dates, commission,
   min_trades, max_drawdown_limit, data_fetch_start, optimize defaults.
   `CAMPAIGN=stocks|crypto` loads profile; env vars override one field only.

7. **Three-branch git model** (keep this — it worked conceptually):
   - `main` — frozen strategies, scan, paper, CI workflows, configs.toml only
   - `autoresearch/stocks` — loop mutates `strategies/stocks.py` + results TSV
   - `autoresearch/crypto` — loop mutates `strategies/crypto.py` + results TSV
   - Harness files sync main → campaign; promotion syncs strategy campaign → main
   - Loop NEVER commits to `main`

8. **Time windows** — train (reasoning only), val (optimize metric), lockbox
   (promotion only, loop never reads).

9. **Basket mode** — N≥2 symbols → score = mean(per-symbol metric) − penalty×std;
   prefetch and backtest every symbol; do not silently skip missing parquet.

10. **LLM output** — Prefer unified diffs (~tokens); `MAX_OUTPUT_TOKENS` from
    `.env` default 8000; floor 4096 when diff mode enabled; stream to console.

11. **Integrity before speed** — Any harness optimization (in-process backtest,
    lower token caps, diff mode) requires automated gates: subprocess vs in-process
    metrics match; diff smoke test passes; `loop.py --iters 1` e2e smoke test.

## Core modules (small, testable)

| Module | Responsibility |
|--------|----------------|
| `config.py` | Load configs.toml + env; expose CampaignConfig dataclass |
| `data_fetch.py` | CCXT crypto + yfinance stocks → `data/{asset}/{sym}_{tf}.parquet` |
| `backtest.py` | Load strategy class, prefetch symbols, run val/train/lockbox, emit `---` summary block |
| `loop.py` | OpenRouter LLM call, parse response, apply diff, git commit/reset, append results TSV, DSR benchmark |
| `program.md` | LLM system prompt (output format, rules, mutation menu) |
| `sync_branches.py` | Promotion gate: candidate beats frozen on val + lockbox floors |
| `scan.py` | Frozen strategy on main → watchlist → webhook BUY/SELL |
| `live_trade.py` | Alpaca paper executor reading frozen strategy from main |
| `strategies/stocks.py`, `strategies/crypto.py` | Baseline strategies (Donchian/EMA style starters) |

Optional phase 2: `app.py` + minimal dashboard (SSE console, launch loop, results table).
Do NOT start with 1400-line Alpine HTML — API-first, thin UI later.

## Metrics & keep rules

- Log: val_sharpe, sortino, calmar, psr, dsr, max_drawdown, win_rate, total_trades, etc.
- Default optimize: `val_sharpe`; env `OPTIMIZE_METRIC` = calmar | dsr
- Keep if metric > best_so_far AND max_drawdown < limit AND trades ≥ min_trades
- Optional DSR gate via env
- Crash / 0 trades → reset commit

## CI (GitHub Actions)

- `loop-crypto.yml` / `loop-stocks.yml` → reusable workflow on campaign branch
- `sync_branches.yml` daily promotion + harness sync
- `scan.yml` / `paper.yml` read **main** only
- Campaign workflow: fetch origin/main configs.toml, prefetch ALL symbols, run loop

## Tech stack

- Python 3.11+, venv, `backtesting.py`, pandas, pyarrow, openai (OpenRouter base URL), ccxt, yfinance, alpaca-py, fastapi + sse-starlette (if dashboard), python-dotenv
- Parquet cache gitignored; results TSV committed on campaign branches

## Explicit anti-patterns (learned from v1 failure)

- Do NOT bundle token-cap reduction + diff mode + in-process backtest in one commit
- Do NOT skip basket symbols when parquet missing
- Do NOT rely on worktree copies of harness without sync story — document one command to sync
- Do NOT hardcode MAX_OUTPUT_TOKENS=800
- Do NOT require operator to run `data_fetch.py` manually for symbols in configs.toml
- Do NOT use GNU patch on Windows

## Deliverables for first milestone (MVP)

1. Repo scaffold + AGENTS.md documenting branch rules
2. configs.toml with [crypto] and [stocks] profiles (BTC+ETH 4h basket for crypto)
3. data_fetch + automatic prefetch in backtest
4. backtest.py with fingerprint-tested harness
5. loop.py with diff apply + streaming + 1-iter smoke test documented
6. program.md + starter strategies
7. README with ONLY automated setup (init script: venv, fetch all campaign data, worktrees)
8. Basic tests: `tests/test_diff_apply.py`, `tests/test_backtest_inprocess_parity.py`

Stop when `CAMPAIGN=crypto python loop.py --iters 1` works end-to-end on a fresh clone
with only `.env` filled (OPENROUTER_API_KEY). No other manual steps.

## My operating preference

- Local dev on Windows; CI on Ubuntu
- OpenRouter for LLM (model via OPENROUTER_MODEL in .env)
- I watch progress in terminal or a minimal dashboard later
- Research runs unattended on GitHub Actions for crypto every 6h, stocks daily
