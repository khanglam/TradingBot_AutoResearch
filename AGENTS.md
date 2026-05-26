# AGENTS.md — Rules for autonomous agents in this repo

## Branch model

- `main` — frozen strategies, scan, paper, CI workflows, dashboard, `configs.toml`. Human-only commits + `promote-bot` + `sync-bot` (via `sync_branches.py`).
- `autoresearch/crypto` — `loop.py` mutates `strategies/crypto.py` and appends `results_crypto.tsv`.
- `autoresearch/stocks` — `loop.py` mutates `strategies/stocks.py` and appends `results_stocks.tsv`.

**The loop NEVER commits to `main`.** Enforced by:
1. Branch guard in `loop.py` (assert `HEAD` starts with `autoresearch/`).
2. Pre-commit hook installed by `scripts/install_git_hooks.py` blocking commits to `main` when author email is `loop@autoresearch.local`.

## Harness immutability

During a research run, only `strategies/<campaign>.py` mutates. These files are off-limits to the loop:
- `backtest.py`, `loop.py`, `config.py`, `data_fetch.py`, `diff_apply.py`, `llm_client.py`, `jsonl_logger.py`, `git_ops.py`, `sync_branches.py`, `program.md`, `configs.toml`, `requirements.txt`, `pyproject.toml`.

Harness changes happen on `main` and propagate via `python sync_branches.py --mode sync-harness --campaign {crypto,stocks}`.

## Mutation menu (LLM must declare category)

1. **indicator_parameter** — tune window/threshold of an existing indicator
2. **entry_condition** — add/swap/remove a single entry filter
3. **exit_risk** — adjust stop, take-profit, or trailing logic
4. **regime_filter** — gate trading on trend/volatility/session
5. **position_sizing** — fixed → vol-target, or adjust risk fraction

LLM output must include a comment line `# mutation: <category> — <change>` in the diff.

## Worktree layout

```
<repo>/                                 # branch: main
<repo>/../<basename>-worktrees/crypto/  # branch: autoresearch/crypto
<repo>/../<basename>-worktrees/stocks/  # branch: autoresearch/stocks
```

`init.sh` / `init.ps1` create these. Do not place worktrees inside the repo.

## Bootstrap

Everything is automated. The only manual steps are:
1. Set `OPENROUTER_API_KEY` in `.env`.
2. Run `./init.sh` (macOS/Linux) or `pwsh -File ./init.ps1` (Windows).

After `init`, all OHLCV data, branches, worktrees, dashboard build, and git hooks exist.
