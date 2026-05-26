"""Campaign config loader + deterministic date-window resolution.

Single source of truth: `configs.toml` on `main`. Env vars override exactly one
field via an explicit allowlist (currently `OPTIMIZE_METRIC` -> `optimize_metric`).

"Today" is pinned to the latest bar date available across the campaign's
parquet cache — NOT `datetime.now()` — so reruns are bit-reproducible.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

from dateutil.relativedelta import relativedelta


REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_PATH = REPO_ROOT / "configs.toml"
DATA_DIR = REPO_ROOT / "data"

ENV_OVERRIDE_ALLOWLIST = {
    "OPTIMIZE_METRIC": "optimize_metric",
}


@dataclass(frozen=True)
class CampaignConfig:
    name: str
    symbols: tuple[str, ...]
    exchange: str
    asset: str
    timeframe: str
    strategy_path: str
    data_fetch_start: date
    commission: float
    slippage: float
    min_trades: int
    max_drawdown_limit: float
    basket_std_penalty: float
    lockbox_months: int
    val_months: int
    optimize_metric: str
    promotion_floor_lockbox_sharpe: float
    promotion_floor_lockbox_min_trades: int

    train_start: date = field(default=date(1970, 1, 1))
    train_end: date = field(default=date(1970, 1, 1))
    val_start: date = field(default=date(1970, 1, 1))
    val_end: date = field(default=date(1970, 1, 1))
    lockbox_start: date = field(default=date(1970, 1, 1))
    lockbox_end: date = field(default=date(1970, 1, 1))
    pinned_today: date = field(default=date(1970, 1, 1))


def _coerce_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"Cannot coerce {value!r} to date")


def _raw_campaign(name: str, configs_path: Path) -> dict:
    configs_path = Path(configs_path)
    if not configs_path.exists():
        raise FileNotFoundError(f"configs.toml not found at {configs_path}")
    with open(configs_path, "rb") as f:
        data = tomllib.load(f)
    if name not in data:
        raise KeyError(f"Campaign '{name}' not found in {configs_path}")
    return data[name]


def resolve_windows(raw: dict, today: date) -> dict:
    """Pure function: given raw config + pinned today, return window dates."""
    lockbox_months = int(raw["lockbox_months"])
    val_months = int(raw["val_months"])
    data_fetch_start = _coerce_date(raw["data_fetch_start"])

    lockbox_end = today
    lockbox_start = today - relativedelta(months=lockbox_months)
    val_end = lockbox_start
    val_start = val_end - relativedelta(months=val_months)
    train_start = data_fetch_start
    train_end = val_start

    if train_start >= train_end:
        raise ValueError(
            f"train window empty: data_fetch_start={train_start} >= val_start={train_end}. "
            f"Lower data_fetch_start or shorten val/lockbox windows."
        )
    return {
        "train_start": train_start,
        "train_end": train_end,
        "val_start": val_start,
        "val_end": val_end,
        "lockbox_start": lockbox_start,
        "lockbox_end": lockbox_end,
        "pinned_today": today,
    }


def _apply_env_overrides(raw: dict) -> dict:
    for env_var, field_name in ENV_OVERRIDE_ALLOWLIST.items():
        if env_var in os.environ and os.environ[env_var]:
            raw[field_name] = os.environ[env_var]
    return raw


def pin_today_from_data(symbols, asset: str, timeframe: str,
                        data_dir: Path = DATA_DIR) -> date:
    """Latest common bar date across symbols' parquet caches.

    Returns min(max_bar_date_per_symbol). Raises if any parquet missing.
    """
    import pandas as pd

    max_dates: list[date] = []
    for sym in symbols:
        filename = sym.replace("/", "-") + f"_{timeframe}.parquet"
        path = data_dir / asset / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Missing parquet for {sym} at {path}. Run prefetch first."
            )
        df = pd.read_parquet(path)
        if df.empty:
            raise ValueError(f"Empty parquet for {sym} at {path}")
        ts = df.index.max() if df.index.name else df["timestamp"].max()
        if hasattr(ts, "date"):
            max_dates.append(ts.date())
        else:
            max_dates.append(_coerce_date(str(ts)[:10]))
    return min(max_dates)


def load_campaign(name: str, today: Optional[date] = None,
                  configs_path: Path = CONFIGS_PATH) -> CampaignConfig:
    """Load campaign config; resolve windows if `today` provided.

    If `today` is None, the returned config has zero windows (caller is expected
    to call `pin_today_from_data` and re-load, OR explicitly accept un-resolved).
    """
    raw = _raw_campaign(name, configs_path)
    raw = _apply_env_overrides(dict(raw))

    base_kwargs = dict(
        name=name,
        symbols=tuple(raw["symbols"]),
        exchange=raw.get("exchange", ""),
        asset=raw["asset"],
        timeframe=raw["timeframe"],
        strategy_path=raw["strategy_path"],
        data_fetch_start=_coerce_date(raw["data_fetch_start"]),
        commission=float(raw["commission"]),
        slippage=float(raw["slippage"]),
        min_trades=int(raw["min_trades"]),
        max_drawdown_limit=float(raw["max_drawdown_limit"]),
        basket_std_penalty=float(raw["basket_std_penalty"]),
        lockbox_months=int(raw["lockbox_months"]),
        val_months=int(raw["val_months"]),
        optimize_metric=str(raw["optimize_metric"]),
        promotion_floor_lockbox_sharpe=float(raw["promotion_floor_lockbox_sharpe"]),
        promotion_floor_lockbox_min_trades=int(raw["promotion_floor_lockbox_min_trades"]),
    )

    cfg = CampaignConfig(**base_kwargs)
    if today is not None:
        windows = resolve_windows(raw, today)
        cfg = replace(cfg, **windows)
    return cfg
