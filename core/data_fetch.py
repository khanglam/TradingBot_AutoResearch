"""OHLCV fetcher (yfinance for stocks, ccxt for crypto).

Raises loudly on failure — never silently skips. Idempotent parquet cache
under `data/{asset}/{normalized_symbol}_{timeframe}.parquet`.

Symbol filename normalization: 'BTC/USDT' -> 'BTC-USDT'.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

CRYPTO_TF_TO_MINUTES = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720,
    "1d": 1440,
}


class DataFetchError(RuntimeError):
    def __init__(self, symbol: str, asset: str, reason: str):
        super().__init__(f"fetch failed for {asset}:{symbol} — {reason}")
        self.symbol = symbol
        self.asset = asset
        self.reason = reason


def _normalize_filename(symbol: str) -> str:
    return symbol.replace("/", "-")


def parquet_path(symbol: str, asset: str, timeframe: str,
                 data_dir: Path = DATA_DIR) -> Path:
    return data_dir / asset / f"{_normalize_filename(symbol)}_{timeframe}.parquet"


def _coerce_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"Cannot coerce {value!r} to date")


def _load_existing(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if df.empty:
        return None
    return df


def _save(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.to_parquet(path)


def _fetch_crypto(symbol: str, exchange_name: str, timeframe: str,
                  since_ms: int, until_ms: int) -> pd.DataFrame:
    import ccxt

    if exchange_name not in dir(ccxt):
        raise DataFetchError(symbol, "crypto", f"unknown exchange '{exchange_name}'")
    exchange_cls = getattr(ccxt, exchange_name)
    exchange = exchange_cls({"enableRateLimit": True})

    if timeframe not in CRYPTO_TF_TO_MINUTES:
        raise DataFetchError(symbol, "crypto", f"unsupported timeframe '{timeframe}'")
    tf_ms = CRYPTO_TF_TO_MINUTES[timeframe] * 60 * 1000
    limit = 1000
    rows: list[list] = []
    cursor = since_ms
    while cursor < until_ms:
        try:
            batch = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=limit)
        except Exception as e:
            raise DataFetchError(symbol, "crypto", f"ccxt error: {e}") from e
        if not batch:
            break
        rows.extend(batch)
        last_ts = batch[-1][0]
        next_cursor = last_ts + tf_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(max(exchange.rateLimit, 200) / 1000.0)
    if not rows:
        raise DataFetchError(symbol, "crypto", "empty result")
    df = pd.DataFrame(rows, columns=["ts_ms", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.tz_convert(None)
    df = df.drop(columns=["ts_ms"]).set_index("Date")
    return df


def _fetch_stock(symbol: str, timeframe: str, start: date, end: date) -> pd.DataFrame:
    import yfinance as yf

    interval_map = {"1d": "1d", "1h": "1h", "30m": "30m", "15m": "15m", "5m": "5m"}
    interval = interval_map.get(timeframe)
    if interval is None:
        raise DataFetchError(symbol, "stocks", f"unsupported timeframe '{timeframe}'")
    try:
        df = yf.download(
            symbol,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval=interval,
            auto_adjust=True,
            progress=False,
            actions=False,
            threads=False,
        )
    except Exception as e:
        raise DataFetchError(symbol, "stocks", f"yfinance error: {e}") from e
    if df is None or df.empty:
        raise DataFetchError(symbol, "stocks", "empty result")
    # yfinance may return MultiIndex columns when given a list-like symbol
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    if df.dropna(how="all").empty:
        raise DataFetchError(symbol, "stocks", "all-NaN result")
    df.index = pd.to_datetime(df.index).tz_localize(None) if df.index.tz else pd.to_datetime(df.index)
    df.index.name = "Date"
    return df


def fetch_symbol(symbol: str, asset: str, timeframe: str,
                 start: date, end: Optional[date] = None,
                 *, exchange: str = "binance",
                 force: bool = False,
                 data_dir: Path = DATA_DIR) -> Path:
    """Fetch (or incrementally extend) one symbol's parquet cache.

    Returns the absolute parquet path. Raises DataFetchError on any failure.
    """
    start = _coerce_date(start)
    end = _coerce_date(end) if end else date.today()
    path = parquet_path(symbol, asset, timeframe, data_dir)

    existing = _load_existing(path)
    if existing is not None and not force:
        max_existing = existing.index.max()
        if hasattr(max_existing, "date"):
            max_date = max_existing.date()
        else:
            max_date = _coerce_date(str(max_existing)[:10])
        if max_date >= end - timedelta(days=1):
            return path
        fetch_start = max_date + timedelta(days=1)
    else:
        fetch_start = start

    if asset == "crypto":
        since_ms = int(datetime(fetch_start.year, fetch_start.month, fetch_start.day, tzinfo=timezone.utc).timestamp() * 1000)
        until_ms = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp() * 1000) + 86_400_000
        new_df = _fetch_crypto(symbol, exchange, timeframe, since_ms, until_ms)
    elif asset == "stocks":
        new_df = _fetch_stock(symbol, timeframe, fetch_start, end)
    else:
        raise DataFetchError(symbol, asset, f"unknown asset '{asset}'")

    if existing is not None and not force:
        combined = pd.concat([existing, new_df])
    else:
        combined = new_df
    _save(combined, path)
    return path


def prefetch_all(symbols, asset: str, timeframe: str,
                 start: date, end: Optional[date] = None,
                 *, exchange: str = "binance",
                 data_dir: Path = DATA_DIR) -> list[Path]:
    """Prefetch all symbols. Raises DataFetchError on FIRST failure (after
    completing earlier successes)."""
    paths: list[Path] = []
    for sym in symbols:
        path = fetch_symbol(sym, asset, timeframe, start, end,
                            exchange=exchange, data_dir=data_dir)
        paths.append(path)
    return paths
