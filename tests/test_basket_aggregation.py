"""Tests for basket aggregation: mean - penalty * std."""

from __future__ import annotations

import math

from core.backtest_lib import _aggregate


def test_aggregate_mean_minus_penalty_std():
    vals = [1.0, 2.0, 3.0]
    out = _aggregate(vals, penalty=0.5)
    # mean=2.0, std(ddof=0)=sqrt(2/3)≈0.8165 → 2 - 0.5*0.8165 ≈ 1.591
    assert math.isclose(out, 2.0 - 0.5 * (2 / 3) ** 0.5, rel_tol=1e-9)


def test_aggregate_zero_penalty_is_mean():
    assert _aggregate([1.0, 3.0, 5.0], 0.0) == 3.0


def test_aggregate_empty_is_zero():
    assert _aggregate([], 0.5) == 0.0


def test_aggregate_single_no_penalty():
    assert _aggregate([4.2], 0.5) == 4.2
