"""Generate deterministic synthetic OHLCV fixtures for backtest tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def make_synthetic_ohlcv(seed: int = 42, n: int = 800,
                         start: str = "2020-01-01", freq: str = "D",
                         drift: float = 0.0005, vol: float = 0.02) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq)
    returns = rng.normal(drift, vol, size=n)
    close = 100.0 * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(rng.normal(0, vol / 3, size=n)))
    low = close * (1 - np.abs(rng.normal(0, vol / 3, size=n)))
    open_ = np.r_[close[0], close[:-1]]
    volume = rng.integers(1_000, 100_000, size=n).astype(float)
    df = pd.DataFrame({
        "Open": open_,
        "High": np.maximum.reduce([open_, high, close]),
        "Low": np.minimum.reduce([open_, low, close]),
        "Close": close,
        "Volume": volume,
    }, index=idx)
    df.index.name = "Date"
    return df


def write_fixture_parquet(symbol: str, asset: str, timeframe: str,
                          data_dir: Path, **kwargs) -> Path:
    df = make_synthetic_ohlcv(**kwargs)
    asset_dir = data_dir / asset
    asset_dir.mkdir(parents=True, exist_ok=True)
    fname = symbol.replace("/", "-") + f"_{timeframe}.parquet"
    path = asset_dir / fname
    df.to_parquet(path)
    return path
