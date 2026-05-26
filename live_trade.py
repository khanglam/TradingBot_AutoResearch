#!/usr/bin/env python
"""live_trade.py — Phase 2 scaffold: Alpaca paper executor.

Reads frozen strategy from main, polls latest bars, places paper orders via
Alpaca. With ALPACA_API_KEY unset (or --dry-run), prints intended orders
instead of submitting.

This module is intentionally minimal — production wiring (order reconciliation,
position limits, kill switches) is out of scope for MVP.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent


def _frozen_marker(campaign: str, base: Path = REPO_ROOT) -> Optional[dict]:
    p = base / "strategies" / f"{campaign}.frozen.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def compute_intended_orders(campaign: str, *, base: Path = REPO_ROOT) -> list[dict]:
    """Run frozen strategy on the last 12 months of bars and return the
    intended action for each symbol on the most recent bar."""
    from backtesting import Backtest

    from core.backtest_lib import load_strategy_class
    from core.config import load_campaign, pin_today_from_data
    from core.data_fetch import parquet_path, prefetch_all

    if not _frozen_marker(campaign, base):
        return []

    cfg = load_campaign(campaign)
    prefetch_all(list(cfg.symbols), cfg.asset, cfg.timeframe,
                 cfg.data_fetch_start, exchange=cfg.exchange)
    pinned = pin_today_from_data(cfg.symbols, cfg.asset, cfg.timeframe)
    cfg = load_campaign(campaign, today=pinned)
    strategy_cls = load_strategy_class(base / cfg.strategy_path)
    window_start = pinned - timedelta(days=365)

    orders: list[dict] = []
    for sym in cfg.symbols:
        df = pd.read_parquet(parquet_path(sym, cfg.asset, cfg.timeframe))
        df = df[[c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]]
        idx = pd.to_datetime(df.index)
        df = df.loc[idx >= pd.Timestamp(window_start)]
        if df.empty or len(df) < 30:
            orders.append({"symbol": sym, "action": "HOLD", "reason": "insufficient_data"})
            continue
        bt = Backtest(df, strategy_cls, cash=10_000, commission=cfg.commission,
                      exclusive_orders=True)
        stats = bt.run()
        try:
            trades = stats._trades
        except AttributeError:
            trades = None
        if trades is None or trades.empty:
            action = "HOLD"
        else:
            last = trades.iloc[-1]
            action = "BUY" if pd.isna(last.get("ExitTime")) else "FLAT"
        orders.append({
            "symbol": sym, "action": action,
            "last_close": float(df["Close"].iloc[-1]),
            "bar": str(df.index[-1])[:19],
        })
    return orders


def submit_orders_alpaca(orders: list[dict], *, paper: bool = True) -> list[dict]:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    key = os.environ["ALPACA_API_KEY"]
    secret = os.environ["ALPACA_SECRET_KEY"]
    client = TradingClient(key, secret, paper=paper)
    submitted = []
    for o in orders:
        if o["action"] != "BUY":
            continue
        req = MarketOrderRequest(
            symbol=o["symbol"].replace("/", ""),  # crypto-friendly
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(req)
        submitted.append({"symbol": o["symbol"], "id": str(order.id)})
    return submitted


def main(argv=None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    p = argparse.ArgumentParser()
    p.add_argument("--campaign", required=True, choices=["crypto", "stocks"])
    p.add_argument("--dry-run", action="store_true",
                   help="print intended orders without submitting")
    args = p.parse_args(argv)

    orders = compute_intended_orders(args.campaign)
    if not orders:
        print(json.dumps({"campaign": args.campaign,
                          "skipped": "no frozen strategy"}, indent=2))
        return 0

    dry = args.dry_run or not os.environ.get("ALPACA_API_KEY")
    print(json.dumps({"campaign": args.campaign, "dry_run": dry,
                      "intended": orders}, indent=2, default=str))
    if dry:
        return 0
    submitted = submit_orders_alpaca(orders,
                                     paper=os.environ.get("ALPACA_PAPER", "true").lower() != "false")
    print(json.dumps({"submitted": submitted}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
