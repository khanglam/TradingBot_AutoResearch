"""Tests for core.data_fetch: raise-on-failure + idempotency + normalization."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from core.data_fetch import (
    DataFetchError,
    fetch_symbol,
    parquet_path,
    prefetch_all,
)


def test_filename_normalization_slash_to_dash(tmp_path):
    p = parquet_path("BTC/USDT", "crypto", "4h", data_dir=tmp_path)
    assert p.name == "BTC-USDT_4h.parquet"


def test_fetch_symbol_unknown_asset_raises(tmp_path):
    with pytest.raises(DataFetchError):
        fetch_symbol("FOO", "other", "1d", date(2024, 1, 1), data_dir=tmp_path)


def test_fetch_symbol_unknown_exchange_raises(tmp_path):
    with pytest.raises(DataFetchError, match="unknown exchange"):
        fetch_symbol("BTC/USDT", "crypto", "4h", date(2024, 1, 1),
                     exchange="nonexistent", data_dir=tmp_path)


def test_fetch_stock_empty_result_raises(tmp_path):
    empty_df = pd.DataFrame()
    with patch("yfinance.download", return_value=empty_df):
        with pytest.raises(DataFetchError, match="empty result"):
            fetch_symbol("SPY", "stocks", "1d", date(2024, 1, 1), date(2024, 1, 5),
                         data_dir=tmp_path)


def test_fetch_crypto_ccxt_error_raises(tmp_path):
    import ccxt

    class FakeBinance:
        rateLimit = 100

        def __init__(self, *_args, **_kwargs):
            pass

        def fetch_ohlcv(self, *_args, **_kwargs):
            raise RuntimeError("network down")

    with patch.object(ccxt, "binance", FakeBinance):
        with pytest.raises(DataFetchError, match="ccxt error"):
            fetch_symbol("BTC/USDT", "crypto", "4h",
                         date(2024, 1, 1), date(2024, 1, 5),
                         data_dir=tmp_path)


def test_idempotent_no_refetch_when_fresh(tmp_path):
    asset_dir = tmp_path / "stocks"
    asset_dir.mkdir()
    today = date.today()
    idx = pd.date_range(today - timedelta(days=10), today, freq="D")
    df = pd.DataFrame(
        {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 100},
        index=idx,
    )
    df.index.name = "Date"
    df.to_parquet(asset_dir / "SPY_1d.parquet")
    called = {"n": 0}

    def fake_dl(*args, **kwargs):
        called["n"] += 1
        return df

    with patch("yfinance.download", side_effect=fake_dl):
        path = fetch_symbol("SPY", "stocks", "1d", today - timedelta(days=20),
                            today, data_dir=tmp_path)
    assert called["n"] == 0
    assert path.exists()


def test_prefetch_all_raises_on_any_missing(tmp_path):
    with patch("yfinance.download", return_value=pd.DataFrame()):
        with pytest.raises(DataFetchError):
            prefetch_all(["SPY", "QQQ"], "stocks", "1d",
                         date(2024, 1, 1), date(2024, 1, 5),
                         data_dir=tmp_path)
