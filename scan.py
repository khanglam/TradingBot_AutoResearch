#!/usr/bin/env python
"""scan.py — read frozen strategy from main, emit BUY/SELL/HOLD per symbol.

For each campaign with a frozen marker, runs the strategy on the last
12 months of data and emits the current signal based on the last bar's
order state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from backtesting import Backtest

from core.backtest_lib import load_strategy_class
from core.config import load_campaign, pin_today_from_data
from core.data_fetch import parquet_path, prefetch_all
from core.webhook import post_signal


REPO_ROOT = Path(__file__).resolve().parent


def _frozen_path(campaign: str, base: Path = REPO_ROOT) -> Path:
    return base / "strategies" / f"{campaign}.frozen.json"


def _signal_from_stats(stats) -> str:
    """Inspect the Backtest stats `_trades` table for the most recent action."""
    try:
        trades = stats._trades
    except AttributeError:
        return "HOLD"
    if trades is None or trades.empty:
        return "HOLD"
    last = trades.iloc[-1]
    # Open trade ⇒ BUY (entered but not exited)
    if pd.isna(last.get("ExitTime")):
        return "BUY"
    # Last completed exit was very recent ⇒ SELL signal in this window
    return "SELL"


def scan_campaign(campaign: str, *, base: Path = REPO_ROOT,
                  webhook_url: str = "", webhook_kind: str = "discord") -> dict:
    if not _frozen_path(campaign, base).exists():
        return {"campaign": campaign, "skipped": True,
                "reason": "no frozen strategy"}
    cfg = load_campaign(campaign)
    # Prefetch and pin today from data
    prefetch_all(list(cfg.symbols), cfg.asset, cfg.timeframe,
                 cfg.data_fetch_start, exchange=cfg.exchange)
    pinned = pin_today_from_data(cfg.symbols, cfg.asset, cfg.timeframe)
    cfg = load_campaign(campaign, today=pinned)

    strategy_cls = load_strategy_class(base / cfg.strategy_path)
    window_start = pinned - timedelta(days=365)
    results = []
    for sym in cfg.symbols:
        df = pd.read_parquet(parquet_path(sym, cfg.asset, cfg.timeframe))
        df = df.rename(columns=str.title) if "open" in df.columns else df
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        df = df[cols]
        idx = pd.to_datetime(df.index)
        df = df.loc[idx >= pd.Timestamp(window_start)]
        if df.empty or len(df) < 30:
            results.append({"symbol": sym, "signal": "HOLD", "reason": "insufficient_data"})
            continue
        bt = Backtest(df, strategy_cls, cash=10_000, commission=cfg.commission,
                      exclusive_orders=True)
        stats = bt.run()
        signal = _signal_from_stats(stats)
        results.append({
            "symbol": sym, "signal": signal,
            "last_close": float(df["Close"].iloc[-1]),
            "bar_ts": str(df.index[-1])[:19],
        })
        if signal != "HOLD" and webhook_url:
            post_signal(webhook_url, webhook_kind, sym, signal, {
                "campaign": campaign,
                "close": f"{df['Close'].iloc[-1]:.4f}",
                "bar": str(df.index[-1])[:19],
            })
    return {"campaign": campaign, "skipped": False, "results": results}


def main(argv=None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    p = argparse.ArgumentParser()
    p.add_argument("--campaign", required=True, choices=["crypto", "stocks"])
    args = p.parse_args(argv)

    webhook_url = os.environ.get("WEBHOOK_URL", "")
    webhook_kind = os.environ.get("WEBHOOK_KIND", "discord")
    out = scan_campaign(args.campaign, webhook_url=webhook_url,
                        webhook_kind=webhook_kind)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
