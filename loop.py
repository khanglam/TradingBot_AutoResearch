#!/usr/bin/env python
"""loop.py — autoresearch loop. Runs INSIDE a campaign worktree.

Usage:
    python loop.py --campaign crypto --iters 1 [--run-id <uuid>]

Loop body per iteration:
  1. Branch guard: HEAD must be autoresearch/<campaign>.
  2. Build system prompt (program.md + current strategy + recent results).
  3. Stream LLM completion via OpenRouter.
  4. Extract unified diff; apply with core.diff_apply (rejects on context fuzz).
  5. Run backtest on val window. If keep rules pass: append TSV + dump equity
     JSON + commit. Else: git checkout the strategy file.
  6. Log every event to logs/loop_{campaign}.jsonl.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from filelock import FileLock

from core.backtest_lib import run_campaign
from core.config import CampaignConfig, load_campaign, pin_today_from_data
from core.data_fetch import prefetch_all
from core.diff_apply import DiffApplyError, apply_unified_diff
from core.git_ops import (
    GitError,
    assert_campaign_branch,
    commit_all,
    current_branch,
    reset_workdir,
    short_sha,
)
from core.jsonl_logger import JsonlLogger
from core.llm_client import stream_completion


REPO_ROOT = Path(__file__).resolve().parent
TSV_COLUMNS = [
    "ts", "run_id", "iter", "mutation_category", "mutation_label",
    "score", "val_sharpe", "val_sortino", "val_calmar", "val_max_drawdown",
    "val_win_rate", "val_total_trades", "val_equity_final", "val_psr", "val_dsr",
    "anchor_symbol", "pinned_today",
    "val_start", "val_end", "lockbox_start", "lockbox_end",
    "kept", "discarded_reason", "equity_uri", "commit_sha",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _results_tsv_path(campaign: str) -> Path:
    return REPO_ROOT / f"results_{campaign}.tsv"


def _equity_path(campaign: str, run_id: str, iter_n: int) -> Path:
    return REPO_ROOT / "equity" / f"{campaign}_{run_id}_{iter_n}.json"


def _log_path(campaign: str) -> Path:
    return REPO_ROOT / "logs" / f"loop_{campaign}.jsonl"


def _ensure_tsv_header(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(TSV_COLUMNS)


def _append_tsv_row(path: Path, row: dict) -> None:
    _ensure_tsv_header(path)
    lock = FileLock(str(path) + ".lock", timeout=5)
    with lock:
        with open(path, "a", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t")
            w.writerow([row.get(c, "") for c in TSV_COLUMNS])


def _read_recent_results(path: Path, n: int = 8) -> list[dict]:
    if not path.exists():
        return []
    lock = FileLock(str(path) + ".lock", timeout=5)
    with lock:
        with open(path, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
    return rows[-n:]


def _read_trial_sharpes(path: Path) -> list[float]:
    if not path.exists():
        return []
    lock = FileLock(str(path) + ".lock", timeout=5)
    with lock:
        with open(path, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
    out = []
    for r in rows:
        try:
            out.append(float(r.get("val_sharpe", "0") or 0))
        except ValueError:
            continue
    return out


_DIFF_FENCE_RE = re.compile(r"```(?:diff)?\s*\n(?P<body>.*?)\n```", re.DOTALL)
_MUTATION_LINE_RE = re.compile(r"#\s*mutation:\s*(?P<cat>[a-z_]+)\s*(?:—|--|-)\s*(?P<label>.+)")


def _extract_diff(text: str) -> Optional[str]:
    matches = list(_DIFF_FENCE_RE.finditer(text))
    if not matches:
        return None
    # Prefer the first fence that looks like a diff (has --- or @@)
    for m in matches:
        body = m.group("body")
        if "@@" in body or body.startswith("---"):
            return body
    return matches[0].group("body")


def _parse_mutation(diff_text: str) -> tuple[str, str]:
    for line in diff_text.splitlines():
        m = _MUTATION_LINE_RE.search(line)
        if m:
            return m.group("cat"), m.group("label").strip()
    return "unknown", ""


def _build_messages(cfg: CampaignConfig, strategy_text: str,
                    recent_results: list[dict], program_text: str) -> list[dict]:
    recent_summary = "\n".join(
        f"  iter {r.get('iter','?')}: cat={r.get('mutation_category','?')} "
        f"sharpe={r.get('val_sharpe','?')} dd={r.get('val_max_drawdown','?')} "
        f"trades={r.get('val_total_trades','?')} kept={r.get('kept','?')}"
        for r in recent_results
    ) or "  (no prior iterations)"
    user_msg = (
        f"Campaign: {cfg.name} ({cfg.asset}, symbols={list(cfg.symbols)}, "
        f"timeframe={cfg.timeframe}, optimize={cfg.optimize_metric})\n\n"
        f"Recent results (most recent last):\n{recent_summary}\n\n"
        f"Current `{cfg.strategy_path}` contents:\n```python\n{strategy_text}```\n\n"
        f"Propose ONE mutation per the rules in the system prompt."
    )
    return [
        {"role": "system", "content": program_text},
        {"role": "user", "content": user_msg},
    ]


def _keep_rules(result, cfg: CampaignConfig, prior_best_score: float) -> tuple[bool, str]:
    if result.aggregate_total_trades < cfg.min_trades:
        return False, f"trades<{cfg.min_trades}"
    if result.aggregate_max_drawdown >= cfg.max_drawdown_limit:
        return False, f"max_dd>={cfg.max_drawdown_limit}"
    if result.score <= prior_best_score:
        return False, "score<=best"
    dsr_gate = os.environ.get("DSR_GATE", "false").lower() in {"1", "true", "yes"}
    if dsr_gate and result.dsr <= 0.5:
        return False, "dsr<=0.5"
    return True, ""


def _best_score_so_far(rows: list[dict]) -> float:
    best = float("-inf")
    for r in rows:
        if str(r.get("kept", "")).lower() not in {"true", "1"}:
            continue
        try:
            s = float(r.get("score", "-inf"))
        except ValueError:
            continue
        if s > best:
            best = s
    return best


def run_loop(campaign: str, iters: int, *, run_id: Optional[str] = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    run_id = run_id or uuid.uuid4().hex[:12]

    assert_campaign_branch(REPO_ROOT, campaign)

    log = JsonlLogger(_log_path(campaign), run_id)
    log.event("run_start", campaign=campaign, iters=iters, branch=current_branch(REPO_ROOT))

    program_text = (REPO_ROOT / "program.md").read_text(encoding="utf-8")
    tsv_path = _results_tsv_path(campaign)
    _ensure_tsv_header(tsv_path)

    try:
        cfg = load_campaign(campaign)
        # If parquet cache is empty, prefetch up to today; otherwise pin to
        # what we have and prefetch up to that (idempotent / fast).
        from core.data_fetch import parquet_path
        any_missing = any(
            not parquet_path(s, cfg.asset, cfg.timeframe).exists()
            for s in cfg.symbols
        )
        if any_missing:
            prefetch_all(list(cfg.symbols), cfg.asset, cfg.timeframe,
                         cfg.data_fetch_start, exchange=cfg.exchange)
        pinned = pin_today_from_data(cfg.symbols, cfg.asset, cfg.timeframe)
        # Pinned-bounded prefetch ensures no-op when data already covers pinned.
        prefetch_all(list(cfg.symbols), cfg.asset, cfg.timeframe,
                     cfg.data_fetch_start, end=pinned, exchange=cfg.exchange)
        cfg = load_campaign(campaign, today=pinned)
        log.event("config_loaded", pinned_today=pinned.isoformat(),
                  val_start=cfg.val_start.isoformat(), val_end=cfg.val_end.isoformat())
    except Exception as e:
        log.event("error", kind=type(e).__name__, message=str(e), phase="config")
        log.close()
        raise

    for i in range(1, iters + 1):
        log.set_iter(i)
        log.event("iter_start", iter=i)

        strategy_path = REPO_ROOT / cfg.strategy_path
        strategy_text = strategy_path.read_text(encoding="utf-8")
        recent = _read_recent_results(tsv_path)
        messages = _build_messages(cfg, strategy_text, recent, program_text)

        # Stream LLM
        log.event("llm_call", model=os.environ.get("OPENROUTER_MODEL", "minimax/minimax-m2"))
        full_text = []
        for delta in stream_completion(
            messages,
            max_tokens=int(os.environ.get("MAX_OUTPUT_TOKENS", "8000")),
        ):
            full_text.append(delta)
            sys.stdout.write(delta)
            sys.stdout.flush()
            log.event("llm_chunk", delta=delta)
        sys.stdout.write("\n")
        response = "".join(full_text)
        log.event("llm_response", chars=len(response))

        # Extract diff
        diff_text = _extract_diff(response)
        if not diff_text:
            log.event("discarded", reason="no_diff")
            continue
        cat, label = _parse_mutation(diff_text)

        # Apply
        try:
            applied = apply_unified_diff(
                diff_text, REPO_ROOT,
                allowed_paths={cfg.strategy_path},
            )
            log.event("diff_applied", mode=applied.mode, file=applied.file,
                      old_sha=applied.old_sha256[:12], new_sha=applied.new_sha256[:12])
        except DiffApplyError as e:
            log.event("error", kind="DiffApplyError", message=str(e))
            reset_workdir(REPO_ROOT, [cfg.strategy_path])
            _append_tsv_row(tsv_path, {
                "ts": _now_iso(), "run_id": run_id, "iter": i,
                "mutation_category": cat, "mutation_label": label,
                "kept": "false", "discarded_reason": f"diff_apply_error:{e}",
            })
            continue

        # Degenerate check
        new_strategy = strategy_path.read_text(encoding="utf-8")
        if new_strategy == strategy_text:
            log.event("discarded", reason="identical")
            reset_workdir(REPO_ROOT, [cfg.strategy_path])
            continue

        # Backtest
        trial_sharpes = _read_trial_sharpes(tsv_path)
        try:
            result = run_campaign(cfg, "val", trial_sharpes=trial_sharpes, prefetch=False)
            log.event("backtest_result",
                      score=result.score,
                      sharpe=result.aggregate_sharpe,
                      max_dd=result.aggregate_max_drawdown,
                      trades=result.aggregate_total_trades,
                      dsr=result.dsr)
        except Exception as e:
            log.event("error", kind=type(e).__name__, message=str(e), phase="backtest")
            reset_workdir(REPO_ROOT, [cfg.strategy_path])
            _append_tsv_row(tsv_path, {
                "ts": _now_iso(), "run_id": run_id, "iter": i,
                "mutation_category": cat, "mutation_label": label,
                "kept": "false", "discarded_reason": f"backtest_error:{type(e).__name__}",
            })
            continue

        # Keep rules
        prior_best = _best_score_so_far(recent + _read_recent_results(tsv_path, n=10_000))
        keep, reason = _keep_rules(result, cfg, prior_best)

        # Dump equity JSON
        equity_path = _equity_path(campaign, run_id, i)
        equity_path.parent.mkdir(parents=True, exist_ok=True)
        with open(equity_path, "w", encoding="utf-8") as f:
            json.dump({
                "campaign": campaign, "run_id": run_id, "iter": i,
                "anchor_symbol": result.anchor_symbol,
                "curve": result.equity_curve,
            }, f)
        equity_uri = str(equity_path.relative_to(REPO_ROOT))

        row = {
            "ts": _now_iso(), "run_id": run_id, "iter": i,
            "mutation_category": cat, "mutation_label": label,
            "score": result.score,
            "val_sharpe": result.aggregate_sharpe,
            "val_sortino": result.aggregate_sortino,
            "val_calmar": result.aggregate_calmar,
            "val_max_drawdown": result.aggregate_max_drawdown,
            "val_win_rate": result.aggregate_win_rate,
            "val_total_trades": result.aggregate_total_trades,
            "val_equity_final": result.aggregate_equity_final,
            "val_psr": result.aggregate_psr,
            "val_dsr": result.dsr,
            "anchor_symbol": result.anchor_symbol,
            "pinned_today": result.pinned_today,
            "val_start": result.val_start, "val_end": result.val_end,
            "lockbox_start": result.lockbox_start, "lockbox_end": result.lockbox_end,
            "kept": "true" if keep else "false",
            "discarded_reason": reason,
            "equity_uri": equity_uri,
        }

        if keep:
            # commit on campaign branch
            try:
                sha = commit_all(
                    REPO_ROOT,
                    f"iter {i}: {cat} — score {result.score:.4f}",
                    paths=[cfg.strategy_path, f"results_{campaign}.tsv", equity_uri],
                )
                row["commit_sha"] = sha[:12] if sha else ""
            except GitError as e:
                log.event("error", kind="GitError", message=str(e))
                row["commit_sha"] = ""
            _append_tsv_row(tsv_path, row)
            log.event("kept", score=result.score, sha=row["commit_sha"])
        else:
            reset_workdir(REPO_ROOT, [cfg.strategy_path])
            _append_tsv_row(tsv_path, row)
            log.event("discarded", reason=reason, score=result.score)

        log.event("iter_end", iter=i)

    log.event("run_end", campaign=campaign)
    log.close()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--campaign", default=os.environ.get("CAMPAIGN"))
    p.add_argument("--iters", type=int, default=1)
    p.add_argument("--run-id", default=None)
    args = p.parse_args(argv)

    if not args.campaign:
        print("error: --campaign or CAMPAIGN env required", file=sys.stderr)
        return 2

    return run_loop(args.campaign, args.iters, run_id=args.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
