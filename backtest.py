#!/usr/bin/env python
"""backtest.py — CLI entry to run a campaign in a single window.

Usage:
    python backtest.py --campaign crypto --window val [--json]

Prints `---` summary block to stderr (human-readable) and optionally a full
CampaignResult JSON to stdout. The same in-process function is exposed at
`core.backtest_lib.run_campaign` so subprocess and in-process produce
byte-equal JSON (parity test in tests/test_backtest_inprocess_parity.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.backtest_lib import run_campaign
from core.config import load_campaign, pin_today_from_data


def _summary_block(result) -> str:
    lines = [
        "---",
        f"campaign      : {result.campaign}",
        f"window        : {result.window}",
        f"pinned_today  : {result.pinned_today}",
        f"score         : {result.score:.4f}",
        f"sharpe        : {result.aggregate_sharpe:.4f}",
        f"sortino       : {result.aggregate_sortino:.4f}",
        f"calmar        : {result.aggregate_calmar:.4f}",
        f"max_drawdown  : {result.aggregate_max_drawdown:.4f}",
        f"win_rate      : {result.aggregate_win_rate:.4f}",
        f"total_trades  : {result.aggregate_total_trades}",
        f"equity_final  : {result.aggregate_equity_final:.2f}",
        f"psr           : {result.aggregate_psr:.4f}",
        f"dsr           : {result.dsr:.4f}",
        f"anchor_symbol : {result.anchor_symbol}",
        "---",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--campaign", required=True)
    p.add_argument("--window", default="val", choices=["train", "val", "lockbox"])
    p.add_argument("--json", action="store_true", help="print full JSON to stdout")
    p.add_argument("--no-prefetch", action="store_true")
    p.add_argument("--trial-sharpes", default="", help="comma-separated prior sharpes")
    args = p.parse_args(argv)

    trial_sharpes = []
    if args.trial_sharpes.strip():
        trial_sharpes = [float(x) for x in args.trial_sharpes.split(",") if x.strip()]

    today = pin_today_from_data.__wrapped__ if False else None  # placeholder
    try:
        # Two-step load: first pin today from data, then load with windows resolved.
        cfg = load_campaign(args.campaign)
        pinned = pin_today_from_data(cfg.symbols, cfg.asset, cfg.timeframe)
        cfg = load_campaign(args.campaign, today=pinned)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    result = run_campaign(cfg, args.window, trial_sharpes=trial_sharpes,
                          prefetch=not args.no_prefetch)
    print(_summary_block(result), file=sys.stderr)
    if args.json:
        print(result.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
