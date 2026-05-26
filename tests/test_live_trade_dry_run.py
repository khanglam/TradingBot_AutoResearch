"""live_trade.py dry-run must work without Alpaca keys."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import live_trade


def test_no_frozen_returns_empty(tmp_path):
    out = live_trade.compute_intended_orders("crypto", base=tmp_path)
    assert out == []


def test_main_dry_run_with_no_frozen(monkeypatch, capsys):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    rc = live_trade.main(["--campaign", "crypto", "--dry-run"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "skipped" in captured.out or "intended" in captured.out
