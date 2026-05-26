"""Backtest harness library — frozen during research runs.

Key responsibilities:
- Prefetch OHLCV data idempotently before running.
- Run `backtesting.py` per-symbol; aggregate into a basket score.
- Compute Sharpe / Sortino / Calmar + PSR + DSR (Bailey & López de Prado).
- Emit the same `CampaignResult` JSON in-process and via subprocess for parity.

DSR formula (Bailey & López de Prado, 2014):

    PSR(SR*) = Φ( (SR_hat - SR*) * sqrt(N-1) /
                  sqrt(1 - skew*SR_hat + (kurt-1)/4 * SR_hat**2) )

    SR0 = sqrt(2 * ln(trials)) * sqrt(Var(SR_trials))  (Euler-Mascheroni term omitted; conservative)
    DSR = PSR(SR0)

Baseline SR* = 0 (per README). When trials < 2, SR0 falls back to 0 and DSR collapses to PSR.

Basket aggregation (CC-10):
    score = mean(per_symbol_metric) - basket_std_penalty * std(per_symbol_metric)

The "anchor" symbol whose equity curve is rendered in the dashboard is `symbols[0]`.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from core.config import CampaignConfig, load_campaign, pin_today_from_data


def _norm_cdf(x: float) -> float:
    """Standard normal CDF — math.erf based, no scipy dependency."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
from core.data_fetch import parquet_path, prefetch_all

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------- DSR / PSR ----------------

def probabilistic_sharpe_ratio(returns: pd.Series, sr_star: float = 0.0) -> float:
    """PSR vs baseline sr_star. Returns probability in [0,1]."""
    r = returns.dropna()
    n = len(r)
    if n < 3:
        return 0.5
    mu = r.mean()
    sigma = r.std(ddof=1)
    if sigma == 0:
        return 0.5
    sr_hat = mu / sigma
    skew = float(r.skew())
    kurt = float(r.kurt())
    denom = math.sqrt(max(1e-12, 1 - skew * sr_hat + ((kurt - 1) / 4.0) * sr_hat ** 2))
    z = (sr_hat - sr_star) * math.sqrt(n - 1) / denom
    return _norm_cdf(z)


def deflated_sharpe_ratio(returns: pd.Series, trial_sharpes: list[float]) -> float:
    """DSR = PSR(SR0). trial_sharpes excludes the current candidate."""
    valid_trials = [s for s in trial_sharpes if s is not None and not math.isnan(s)]
    if len(valid_trials) < 2:
        sr0 = 0.0
    else:
        var_sr = float(np.var(valid_trials, ddof=1))
        sr0 = math.sqrt(2.0 * math.log(len(valid_trials))) * math.sqrt(max(0.0, var_sr))
    return probabilistic_sharpe_ratio(returns, sr_star=sr0)


# ---------------- Result types ----------------

@dataclass
class SymbolResult:
    symbol: str
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    equity_final: float
    psr: float
    returns: list[float] = field(default_factory=list)


@dataclass
class CampaignResult:
    campaign: str
    window: str
    val_start: str
    val_end: str
    train_start: str
    train_end: str
    lockbox_start: str
    lockbox_end: str
    pinned_today: str
    optimize_metric: str
    score: float
    aggregate_sharpe: float
    aggregate_sortino: float
    aggregate_calmar: float
    aggregate_max_drawdown: float
    aggregate_win_rate: float
    aggregate_total_trades: int
    aggregate_equity_final: float
    aggregate_psr: float
    dsr: float
    trial_count: int
    anchor_symbol: str
    equity_curve: list[dict]
    per_symbol: list[dict]

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=2, default=str)


# ---------------- Strategy loading ----------------

def load_strategy_class(strategy_path: Path):
    """Load the single Strategy subclass from a file."""
    from backtesting import Strategy

    if not strategy_path.exists():
        raise FileNotFoundError(f"strategy file missing: {strategy_path}")
    spec = importlib.util.spec_from_file_location("user_strategy", strategy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load spec for {strategy_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["user_strategy"] = module
    spec.loader.exec_module(module)
    candidates = []
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy:
            candidates.append(obj)
    if not candidates:
        raise ValueError(f"no Strategy subclass found in {strategy_path}")
    if len(candidates) > 1:
        raise ValueError(f"multiple Strategy subclasses in {strategy_path}: {candidates}")
    return candidates[0]


# ---------------- Window slicing ----------------

def slice_window(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    idx = pd.to_datetime(df.index)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    mask = (idx >= start_ts) & (idx < end_ts)
    return df.loc[mask]


def _ensure_ohlc_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for need in ["open", "high", "low", "close", "volume"]:
        if need in cols and cols[need] != need.capitalize():
            rename[cols[need]] = need.capitalize()
    if rename:
        df = df.rename(columns=rename)
    missing = [c for c in ["Open", "High", "Low", "Close"] if c not in df.columns]
    if missing:
        raise ValueError(f"missing OHLC columns: {missing}")
    if "Volume" not in df.columns:
        df["Volume"] = 0.0
    return df[["Open", "High", "Low", "Close", "Volume"]]


def _safe_float(value) -> float:
    """Convert backtesting.py stat values to JSON-safe floats."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(f) or math.isinf(f):
        return 0.0
    return f


def _backtest_one(df: pd.DataFrame, strategy_cls, commission: float,
                  cash: float = 10_000.0) -> SymbolResult:
    from backtesting import Backtest

    bt = Backtest(df, strategy_cls, cash=cash, commission=commission,
                  exclusive_orders=True)
    stats = bt.run()
    equity_curve = bt._results._equity_curve if hasattr(bt, "_results") else None
    try:
        equity_series = stats._equity_curve["Equity"]
    except Exception:
        equity_series = pd.Series(dtype=float)
    rets = equity_series.pct_change().dropna() if not equity_series.empty else pd.Series(dtype=float)
    sharpe = _safe_float(stats.get("Sharpe Ratio", 0.0))
    sortino = _safe_float(stats.get("Sortino Ratio", 0.0))
    calmar = _safe_float(stats.get("Calmar Ratio", 0.0))
    max_dd_pct = _safe_float(stats.get("Max. Drawdown [%]", 0.0))
    win_rate = _safe_float(stats.get("Win Rate [%]", 0.0)) / 100.0
    total_trades = int(_safe_float(stats.get("# Trades", 0)))
    equity_final = _safe_float(stats.get("Equity Final [$]", cash))
    psr = probabilistic_sharpe_ratio(rets, sr_star=0.0) if not rets.empty else 0.5
    return SymbolResult(
        symbol="?",
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        max_drawdown=abs(max_dd_pct) / 100.0,
        win_rate=win_rate,
        total_trades=total_trades,
        equity_final=equity_final,
        psr=psr,
        returns=rets.tolist(),
    )


def _equity_curve_for(df: pd.DataFrame, strategy_cls, commission: float,
                     cash: float = 10_000.0) -> list[dict]:
    from backtesting import Backtest

    bt = Backtest(df, strategy_cls, cash=cash, commission=commission,
                  exclusive_orders=True)
    stats = bt.run()
    try:
        eq = stats._equity_curve["Equity"]
    except Exception:
        return []
    out = []
    for ts, val in eq.items():
        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        out.append({"t": ts_str, "v": _safe_float(val)})
    return out


# ---------------- Public API ----------------

def _aggregate(metric_values: list[float], penalty: float) -> float:
    if not metric_values:
        return 0.0
    arr = np.array(metric_values, dtype=float)
    return float(arr.mean() - penalty * arr.std(ddof=0))


def run_campaign(cfg: CampaignConfig, window: str,
                 trial_sharpes: Optional[list[float]] = None,
                 data_dir: Optional[Path] = None,
                 strategy_root: Optional[Path] = None,
                 prefetch: bool = True) -> CampaignResult:
    """Run a campaign over `window` ∈ {train, val, lockbox}.

    Returns a CampaignResult. Raises DataFetchError on missing parquet (when
    `prefetch=True`, attempts a fetch first).
    """
    if window not in {"train", "val", "lockbox"}:
        raise ValueError(f"window must be train|val|lockbox, got {window!r}")

    data_dir = Path(data_dir) if data_dir else (REPO_ROOT / "data")
    strategy_root = Path(strategy_root) if strategy_root else REPO_ROOT

    if prefetch:
        prefetch_all(list(cfg.symbols), cfg.asset, cfg.timeframe,
                     cfg.data_fetch_start, cfg.pinned_today,
                     exchange=cfg.exchange, data_dir=data_dir)

    if window == "train":
        w_start, w_end = cfg.train_start, cfg.train_end
    elif window == "val":
        w_start, w_end = cfg.val_start, cfg.val_end
    else:
        w_start, w_end = cfg.lockbox_start, cfg.lockbox_end

    strategy_path = strategy_root / cfg.strategy_path
    strategy_cls = load_strategy_class(strategy_path)

    per_symbol: list[SymbolResult] = []
    for sym in cfg.symbols:
        p = parquet_path(sym, cfg.asset, cfg.timeframe, data_dir)
        if not p.exists():
            raise FileNotFoundError(f"parquet missing for {sym}: {p}")
        df = pd.read_parquet(p)
        df = _ensure_ohlc_columns(df)
        sliced = slice_window(df, w_start, w_end)
        if sliced.empty or len(sliced) < 30:
            r = SymbolResult(symbol=sym, sharpe=0.0, sortino=0.0, calmar=0.0,
                             max_drawdown=0.0, win_rate=0.0, total_trades=0,
                             equity_final=10_000.0, psr=0.5, returns=[])
        else:
            r = _backtest_one(sliced, strategy_cls, cfg.commission + cfg.slippage)
            r.symbol = sym
        per_symbol.append(r)

    # Aggregate
    optimize_metric = cfg.optimize_metric
    metric_attr = {"sharpe": "sharpe", "calmar": "calmar", "dsr": "psr"}.get(optimize_metric, "sharpe")
    metric_vals = [getattr(r, metric_attr) for r in per_symbol]
    score = _aggregate(metric_vals, cfg.basket_std_penalty)

    agg_sharpe = _aggregate([r.sharpe for r in per_symbol], cfg.basket_std_penalty)
    agg_sortino = _aggregate([r.sortino for r in per_symbol], cfg.basket_std_penalty)
    agg_calmar = _aggregate([r.calmar for r in per_symbol], cfg.basket_std_penalty)
    agg_max_dd = float(np.mean([r.max_drawdown for r in per_symbol])) if per_symbol else 0.0
    agg_win_rate = float(np.mean([r.win_rate for r in per_symbol])) if per_symbol else 0.0
    agg_trades = int(sum(r.total_trades for r in per_symbol))
    agg_equity_final = float(np.mean([r.equity_final for r in per_symbol])) if per_symbol else 0.0
    agg_psr = float(np.mean([r.psr for r in per_symbol])) if per_symbol else 0.5

    # DSR uses anchor symbol's returns (most representative for the trial)
    anchor = per_symbol[0] if per_symbol else None
    anchor_rets = pd.Series(anchor.returns) if (anchor and anchor.returns) else pd.Series(dtype=float)
    dsr = deflated_sharpe_ratio(anchor_rets, trial_sharpes or [])

    # Anchor equity curve for dashboard
    anchor_symbol = cfg.symbols[0]
    anchor_path = parquet_path(anchor_symbol, cfg.asset, cfg.timeframe, data_dir)
    anchor_df = _ensure_ohlc_columns(pd.read_parquet(anchor_path))
    anchor_sliced = slice_window(anchor_df, w_start, w_end)
    if anchor_sliced.empty or len(anchor_sliced) < 30:
        equity_curve = []
    else:
        equity_curve = _equity_curve_for(anchor_sliced, strategy_cls,
                                          cfg.commission + cfg.slippage)

    result = CampaignResult(
        campaign=cfg.name,
        window=window,
        val_start=cfg.val_start.isoformat(),
        val_end=cfg.val_end.isoformat(),
        train_start=cfg.train_start.isoformat(),
        train_end=cfg.train_end.isoformat(),
        lockbox_start=cfg.lockbox_start.isoformat(),
        lockbox_end=cfg.lockbox_end.isoformat(),
        pinned_today=cfg.pinned_today.isoformat(),
        optimize_metric=cfg.optimize_metric,
        score=float(score),
        aggregate_sharpe=float(agg_sharpe),
        aggregate_sortino=float(agg_sortino),
        aggregate_calmar=float(agg_calmar),
        aggregate_max_drawdown=float(agg_max_dd),
        aggregate_win_rate=float(agg_win_rate),
        aggregate_total_trades=agg_trades,
        aggregate_equity_final=float(agg_equity_final),
        aggregate_psr=float(agg_psr),
        dsr=float(dsr),
        trial_count=len(trial_sharpes or []),
        anchor_symbol=anchor_symbol,
        equity_curve=equity_curve,
        per_symbol=[{
            "symbol": r.symbol,
            "sharpe": r.sharpe,
            "sortino": r.sortino,
            "calmar": r.calmar,
            "max_drawdown": r.max_drawdown,
            "win_rate": r.win_rate,
            "total_trades": r.total_trades,
            "equity_final": r.equity_final,
            "psr": r.psr,
        } for r in per_symbol],
    )
    return result
