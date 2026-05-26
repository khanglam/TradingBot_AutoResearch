"""Baseline crypto strategy: Donchian channel breakout with ATR stop.

This is the starting point for autoresearch. The LLM will mutate it one
change at a time. Keep the class name `Strategy` and the `init`/`next`
structure stable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from backtesting import Strategy as _BaseStrategy


def _donchian_high(series, n):
    return pd.Series(series).rolling(n, min_periods=1).max()


def _donchian_low(series, n):
    return pd.Series(series).rolling(n, min_periods=1).min()


def _atr(high, low, close, n):
    h = pd.Series(high)
    l = pd.Series(low)
    c = pd.Series(close)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


class Strategy(_BaseStrategy):
    donchian_n = 20
    exit_n = 10
    atr_n = 14
    atr_stop = 2.0
    risk_frac = 0.5

    def init(self):
        self.high_n = self.I(_donchian_high, self.data.High, self.donchian_n)
        self.low_n = self.I(_donchian_low, self.data.Low, self.exit_n)
        self.atr = self.I(_atr, self.data.High, self.data.Low, self.data.Close, self.atr_n)

    def next(self):
        # mutation: baseline — Donchian 20/10 breakout with 2.0×ATR stop
        price = self.data.Close[-1]
        if not self.position:
            if price >= self.high_n[-2]:
                stop = price - self.atr_stop * self.atr[-1]
                self.buy(size=self.risk_frac, sl=max(stop, 0.01))
        else:
            if price <= self.low_n[-2]:
                self.position.close()
