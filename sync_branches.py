#!/usr/bin/env python
"""sync_branches.py — two modes:

  --mode sync-harness  Copy frozen harness files main → campaign worktree
  --mode promote       Promote best campaign candidate → main when floors met

Reads campaign worktree at: <repo>/../<basename>-worktrees/<campaign>/
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from core.backtest_lib import run_campaign
from core.config import load_campaign, pin_today_from_data
from core.git_ops import commit_all, current_branch, short_sha

REPO_ROOT = Path(__file__).resolve().parent


HARNESS_ALLOWLIST = [
    "backtest.py", "loop.py", "scan.py", "live_trade.py", "sync_branches.py",
    "program.md", "configs.toml", "requirements.txt", "pyproject.toml",
    "core/__init__.py", "core/config.py", "core/data_fetch.py",
    "core/backtest_lib.py", "core/diff_apply.py", "core/llm_client.py",
    "core/jsonl_logger.py", "core/git_ops.py", "core/webhook.py",
    "core/sse_tail.py", "core/process_registry.py",
    "app.py",
]


def worktree_path(campaign: str, base: Path = REPO_ROOT) -> Path:
    """Sibling-dir layout: <repo>/../<basename>-worktrees/<campaign>/."""
    return base.parent / f"{base.name}-worktrees" / campaign


_SYNC_PROTECTED = {"strategies/{campaign}.py", "results_{campaign}.tsv"}


def _worktree_tracked_files(wt: Path) -> list[str]:
    import subprocess
    result = subprocess.run(
        ["git", "ls-files"], cwd=str(wt), capture_output=True, text=True, check=True
    )
    return result.stdout.splitlines()


def _is_protected(rel: str, campaign: str) -> bool:
    return rel in {f"strategies/{campaign}.py", f"results_{campaign}.tsv"}


def sync_harness(campaign: str, *, dry_run: bool = False,
                 base: Path = REPO_ROOT) -> dict:
    """Copy allowlisted files from main repo to campaign worktree and delete
    any tracked files that were removed from main, then commit."""
    wt = worktree_path(campaign, base)
    if not wt.exists():
        raise FileNotFoundError(f"worktree missing: {wt}. Run init script first.")

    copied = []
    for rel in HARNESS_ALLOWLIST:
        src = base / rel
        dst = wt / rel
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dry_run:
            copied.append(rel)
            continue
        shutil.copy2(src, dst)
        copied.append(rel)

    deleted = []
    for rel in _worktree_tracked_files(wt):
        if _is_protected(rel, campaign):
            continue
        if (base / rel).exists():
            continue
        deleted.append(rel)
        if not dry_run:
            (wt / rel).unlink(missing_ok=True)

    sha = short_sha(base)
    if not dry_run and (copied or deleted):
        commit_all(
            wt, f"sync harness from main @ {sha}",
            author_name="sync-bot", author_email="sync@autoresearch.local",
            paths=copied + deleted,
        )
    return {"campaign": campaign, "copied": copied, "deleted": deleted,
            "from_sha": sha, "dry_run": dry_run}


def _frozen_marker_path(campaign: str, base: Path = REPO_ROOT) -> Path:
    return base / "strategies" / f"{campaign}.frozen.json"


def load_frozen_marker(campaign: str, base: Path = REPO_ROOT) -> Optional[dict]:
    p = _frozen_marker_path(campaign, base)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _read_results_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _best_kept_row(rows: list[dict]) -> Optional[dict]:
    best = None
    best_score = float("-inf")
    for r in rows:
        if str(r.get("kept", "")).lower() not in {"true", "1"}:
            continue
        try:
            s = float(r.get("score", "-inf"))
        except ValueError:
            continue
        if s > best_score:
            best_score = s
            best = r
    return best


def evaluate_promotion(candidate_val_metric: float, candidate_lockbox,
                       cfg, frozen: Optional[dict], *,
                       dsr_required: bool = True) -> tuple[bool, list[str]]:
    """Return (pass, reasons). `candidate_lockbox` is a CampaignResult."""
    reasons: list[str] = []
    # Floor 1: beats frozen on val (or frozen absent)
    if frozen is not None:
        try:
            frozen_val = float(frozen.get("val_metric", 0))
        except (TypeError, ValueError):
            frozen_val = 0.0
        if candidate_val_metric <= frozen_val:
            reasons.append(f"val_metric {candidate_val_metric:.4f} <= frozen {frozen_val:.4f}")
    # Floor 2: lockbox sharpe > floor
    if candidate_lockbox.aggregate_sharpe < cfg.promotion_floor_lockbox_sharpe:
        reasons.append(
            f"lockbox_sharpe {candidate_lockbox.aggregate_sharpe:.4f} < "
            f"{cfg.promotion_floor_lockbox_sharpe}"
        )
    # Floor 3: lockbox trades floor
    if candidate_lockbox.aggregate_total_trades < cfg.promotion_floor_lockbox_min_trades:
        reasons.append(
            f"lockbox_trades {candidate_lockbox.aggregate_total_trades} < "
            f"{cfg.promotion_floor_lockbox_min_trades}"
        )
    # Floor 4: lockbox max_dd
    if candidate_lockbox.aggregate_max_drawdown >= cfg.max_drawdown_limit:
        reasons.append(
            f"lockbox_max_dd {candidate_lockbox.aggregate_max_drawdown:.4f} >= "
            f"{cfg.max_drawdown_limit}"
        )
    # Floor 5: DSR > 0 (against trial baseline; 0.5 = neutral)
    if dsr_required and candidate_lockbox.dsr <= 0.5:
        reasons.append(f"dsr {candidate_lockbox.dsr:.4f} <= 0.5")
    return (len(reasons) == 0), reasons


def promote(campaign: str, *, dry_run: bool = False,
            base: Path = REPO_ROOT) -> dict:
    wt = worktree_path(campaign, base)
    if not wt.exists():
        raise FileNotFoundError(f"worktree missing: {wt}")

    tsv_path = wt / f"results_{campaign}.tsv"
    rows = _read_results_tsv(tsv_path)
    candidate = _best_kept_row(rows)
    if candidate is None:
        return {"promoted": False, "reason": "no kept candidate", "campaign": campaign}

    # Load campaign config — pin today from data on main repo (consistent across both)
    cfg = load_campaign(campaign)
    pinned = pin_today_from_data(cfg.symbols, cfg.asset, cfg.timeframe)
    cfg = load_campaign(campaign, today=pinned)

    # Run lockbox backtest on the candidate's strategy file (currently HEAD of campaign branch)
    # We point strategy_root at the worktree so it loads the campaign-branch strategy.
    lockbox_result = run_campaign(cfg, "lockbox",
                                  trial_sharpes=[
                                      float(r.get("val_sharpe", 0) or 0) for r in rows
                                  ],
                                  strategy_root=wt,
                                  prefetch=True)

    candidate_val_metric = float(candidate.get("score", 0) or 0)
    frozen = load_frozen_marker(campaign, base)
    ok, reasons = evaluate_promotion(candidate_val_metric, lockbox_result, cfg, frozen)

    result = {
        "campaign": campaign,
        "promoted": ok,
        "reasons": reasons,
        "candidate_score": candidate_val_metric,
        "lockbox_sharpe": lockbox_result.aggregate_sharpe,
        "lockbox_trades": lockbox_result.aggregate_total_trades,
        "lockbox_max_dd": lockbox_result.aggregate_max_drawdown,
        "lockbox_dsr": lockbox_result.dsr,
        "dry_run": dry_run,
    }

    if not ok or dry_run:
        return result

    # Copy strategy file campaign → main
    src = wt / cfg.strategy_path
    dst = base / cfg.strategy_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

    # Write frozen marker
    marker = {
        "campaign": campaign,
        "val_metric": candidate_val_metric,
        "lockbox_sharpe": lockbox_result.aggregate_sharpe,
        "lockbox_trades": lockbox_result.aggregate_total_trades,
        "lockbox_dsr": lockbox_result.dsr,
        "ts": datetime.now(timezone.utc).isoformat(),
        "from_campaign_commit": candidate.get("commit_sha", ""),
    }
    _frozen_marker_path(campaign, base).write_text(json.dumps(marker, indent=2),
                                                    encoding="utf-8")
    commit_all(
        base,
        f"promote {campaign}: val={candidate_val_metric:.4f} "
        f"lockbox_sharpe={lockbox_result.aggregate_sharpe:.4f}",
        author_name="promote-bot",
        author_email="promote@autoresearch.local",
        paths=[cfg.strategy_path, f"strategies/{campaign}.frozen.json"],
    )
    result["promoted_commit"] = short_sha(base)
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", required=True, choices=["sync-harness", "promote"])
    p.add_argument("--campaign", required=True, choices=["crypto", "stocks"])
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    if args.mode == "sync-harness":
        out = sync_harness(args.campaign, dry_run=args.dry_run)
    else:
        out = promote(args.campaign, dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
