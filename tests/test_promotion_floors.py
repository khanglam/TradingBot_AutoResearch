"""Tests for promotion floors (without git ops — pure logic)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from sync_branches import evaluate_promotion


def make_cfg(**overrides):
    base = dict(
        promotion_floor_lockbox_sharpe=0.0,
        promotion_floor_lockbox_min_trades=10,
        max_drawdown_limit=0.30,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def make_lockbox(sharpe=1.0, trades=20, max_dd=0.10, dsr=0.9):
    return SimpleNamespace(
        aggregate_sharpe=sharpe,
        aggregate_total_trades=trades,
        aggregate_max_drawdown=max_dd,
        dsr=dsr,
    )


def test_promotion_passes_when_all_floors_met():
    ok, reasons = evaluate_promotion(
        candidate_val_metric=1.5,
        candidate_lockbox=make_lockbox(),
        cfg=make_cfg(),
        frozen={"val_metric": 1.0},
    )
    assert ok, reasons
    assert reasons == []


def test_promotion_fails_when_candidate_val_lte_frozen():
    ok, reasons = evaluate_promotion(
        candidate_val_metric=0.9,
        candidate_lockbox=make_lockbox(),
        cfg=make_cfg(),
        frozen={"val_metric": 1.0},
    )
    assert not ok
    assert any("val_metric" in r for r in reasons)


def test_promotion_first_run_no_frozen_passes_if_lockbox_ok():
    ok, reasons = evaluate_promotion(
        candidate_val_metric=0.5,
        candidate_lockbox=make_lockbox(sharpe=0.3, trades=15, max_dd=0.1, dsr=0.8),
        cfg=make_cfg(),
        frozen=None,
    )
    assert ok, reasons


def test_promotion_first_run_no_frozen_fails_if_lockbox_negative():
    ok, reasons = evaluate_promotion(
        candidate_val_metric=0.5,
        candidate_lockbox=make_lockbox(sharpe=-0.2),
        cfg=make_cfg(),
        frozen=None,
    )
    assert not ok
    assert any("lockbox_sharpe" in r for r in reasons)


def test_promotion_fails_on_low_trade_count():
    ok, reasons = evaluate_promotion(
        candidate_val_metric=2.0,
        candidate_lockbox=make_lockbox(trades=3),
        cfg=make_cfg(),
        frozen=None,
    )
    assert not ok
    assert any("lockbox_trades" in r for r in reasons)


def test_promotion_fails_on_high_drawdown():
    ok, reasons = evaluate_promotion(
        candidate_val_metric=2.0,
        candidate_lockbox=make_lockbox(max_dd=0.4),
        cfg=make_cfg(),
        frozen=None,
    )
    assert not ok
    assert any("lockbox_max_dd" in r for r in reasons)


def test_promotion_dsr_gate():
    ok, reasons = evaluate_promotion(
        candidate_val_metric=2.0,
        candidate_lockbox=make_lockbox(dsr=0.3),
        cfg=make_cfg(),
        frozen=None,
    )
    assert not ok
    assert any("dsr" in r for r in reasons)
