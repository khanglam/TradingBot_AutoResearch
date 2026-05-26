"""Tests for the DSR / PSR implementation."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from core.backtest_lib import deflated_sharpe_ratio, probabilistic_sharpe_ratio


def test_psr_zero_returns_is_half():
    r = pd.Series(np.zeros(100))
    assert probabilistic_sharpe_ratio(r) == 0.5


def test_psr_strong_drift_close_to_one():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.01, 0.005, size=500))  # high SR
    psr = probabilistic_sharpe_ratio(r, sr_star=0.0)
    assert psr > 0.99


def test_dsr_collapses_to_psr_with_few_trials():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.005, 0.01, size=300))
    dsr_no_trials = deflated_sharpe_ratio(r, [])
    psr = probabilistic_sharpe_ratio(r, sr_star=0.0)
    assert math.isclose(dsr_no_trials, psr, rel_tol=1e-9)


def test_dsr_penalizes_many_trials():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.005, 0.01, size=300))
    dsr_few = deflated_sharpe_ratio(r, [0.1, 0.15])
    dsr_many = deflated_sharpe_ratio(r, [0.1, 0.5, -0.1, 0.3, 0.4, 0.2, -0.2, 0.6])
    # More trials with variance ⇒ higher SR0 baseline ⇒ lower DSR
    assert dsr_many < dsr_few
