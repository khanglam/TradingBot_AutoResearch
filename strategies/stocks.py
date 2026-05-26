"""Baseline stocks strategy: SMA-50/200 trend filter + EMA-20 pullback entry.

This is the starting point for autoresearch. The LLM will mutate it one
change at a time. Keep the class name `Strategy` and the `init`/`next`
structure stable.
"""

from __future__ import annotations

import pandas as pd
from backtesting import Strategy as _BaseStrategy


def _sma(series, n):
    return pd.Series(series).rolling(n, min_periods=1).mean()


def _ema(series, n):
    return pd.Series(series).ewm(span=n, adjust=False).mean()


class Strategy(_BaseStrategy):
    sma_fast = 50
    sma_slow = 200
    ema_pullback = 20
    trail_pct = 0.08
    risk_frac = 0.95

    def init(self):
        self.fast = self.I(_sma, self.data.Close, self.sma_fast)
        self.slow = self.I(_sma, self.data.Close, self.sma_slow)
        self.pull = self.I(_ema, self.data.Close, self.ema_pullback)

    def next(self):
        # mutation: baseline — SMA-50/200 trend with EMA-20 pullback, 8% trail
        if len(self.data) < self.sma_slow + 2:
            return
        price = self.data.Close[-1]
        trend_up = self.fast[-1] > self.slow[-1]
        if not self.position:
            if trend_up and price <= self.pull[-1]:
                stop = price * (1.0 - self.trail_pct)
                self.buy(size=self.risk_frac, sl=max(stop, 0.01))
        else:
            # exit on trend break
            if not trend_up:
                self.position.close()
