"""Tests for core.config window resolution and loading."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from core.config import (
    CampaignConfig,
    load_campaign,
    pin_today_from_data,
    resolve_windows,
)


def test_resolve_windows_default_formula():
    raw = {
        "data_fetch_start": "2019-01-01",
        "lockbox_months": 12,
        "val_months": 18,
    }
    out = resolve_windows(raw, today=date(2025, 6, 15))
    assert out["lockbox_end"] == date(2025, 6, 15)
    assert out["lockbox_start"] == date(2024, 6, 15)
    assert out["val_end"] == date(2024, 6, 15)
    assert out["val_start"] == date(2022, 12, 15)
    assert out["train_start"] == date(2019, 1, 1)
    assert out["train_end"] == date(2022, 12, 15)
    assert out["pinned_today"] == date(2025, 6, 15)


def test_resolve_windows_custom_months():
    raw = {
        "data_fetch_start": "2020-01-01",
        "lockbox_months": 6,
        "val_months": 12,
    }
    out = resolve_windows(raw, today=date(2024, 1, 1))
    assert out["lockbox_start"] == date(2023, 7, 1)
    assert out["val_start"] == date(2022, 7, 1)
    assert out["val_end"] == date(2023, 7, 1)


def test_resolve_windows_empty_train_raises():
    raw = {
        "data_fetch_start": "2024-01-01",
        "lockbox_months": 12,
        "val_months": 12,
    }
    with pytest.raises(ValueError, match="train window empty"):
        resolve_windows(raw, today=date(2024, 6, 1))


def test_load_campaign_unknown_raises():
    with pytest.raises(KeyError):
        load_campaign("nonexistent")


def test_load_campaign_crypto_resolves_dates_when_today_given():
    cfg = load_campaign("crypto", today=date(2025, 6, 15))
    assert cfg.name == "crypto"
    assert any("BTC" in s for s in cfg.symbols)
    assert cfg.asset == "crypto"
    assert cfg.lockbox_end == date(2025, 6, 15)
    assert cfg.train_start == date(2019, 1, 1)


def test_env_override_only_optimize_metric(monkeypatch):
    monkeypatch.setenv("OPTIMIZE_METRIC", "calmar")
    cfg = load_campaign("crypto", today=date(2025, 6, 15))
    assert cfg.optimize_metric == "calmar"


def test_pin_today_raises_when_parquet_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        pin_today_from_data(["BTC/USDT"], "crypto", "4h", data_dir=tmp_path)


def test_pin_today_from_data(tmp_path):
    asset_dir = tmp_path / "crypto"
    asset_dir.mkdir()
    idx = pd.date_range("2024-01-01", "2024-05-01", freq="D")
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0}, index=idx)
    df.index.name = "Date"
    df.to_parquet(asset_dir / "BTC-USDT_4h.parquet")
    idx2 = pd.date_range("2024-01-01", "2024-04-15", freq="D")
    df2 = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0}, index=idx2)
    df2.index.name = "Date"
    df2.to_parquet(asset_dir / "ETH-USDT_4h.parquet")
    today = pin_today_from_data(["BTC/USDT", "ETH/USDT"], "crypto", "4h", data_dir=tmp_path)
    assert today == date(2024, 4, 15)
