"""Smoke tests: starter strategies run on synthetic data without crashing."""

from __future__ import annotations

from pathlib import Path

from backtesting import Backtest

from core.backtest_lib import load_strategy_class
from tests.fixtures.synthetic_data import make_synthetic_ohlcv

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_crypto_starter_runs():
    cls = load_strategy_class(REPO_ROOT / "strategies" / "crypto.py")
    df = make_synthetic_ohlcv(seed=7, n=600)
    bt = Backtest(df, cls, cash=10_000, commission=0.001, exclusive_orders=True)
    stats = bt.run()
    assert stats is not None
    assert stats["# Trades"] >= 0
    assert stats["Equity Final [$]"] > 0


def test_stocks_starter_runs():
    cls = load_strategy_class(REPO_ROOT / "strategies" / "stocks.py")
    df = make_synthetic_ohlcv(seed=8, n=900)
    bt = Backtest(df, cls, cash=10_000, commission=0.0005, exclusive_orders=True)
    stats = bt.run()
    assert stats is not None
    assert stats["# Trades"] >= 0
    assert stats["Equity Final [$]"] > 0
