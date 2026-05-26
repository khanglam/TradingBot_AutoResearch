"""Tiny deterministic strategy for parity + DSR tests."""

from backtesting import Strategy
from backtesting.lib import crossover


def sma(series, n):
    import pandas as pd
    return pd.Series(series).rolling(n).mean()


class Strategy(Strategy):  # noqa: F811
    fast = 10
    slow = 30

    def init(self):
        self.f = self.I(sma, self.data.Close, self.fast)
        self.s = self.I(sma, self.data.Close, self.slow)

    def next(self):
        if crossover(self.f, self.s):
            self.position.close()
            self.buy()
        elif crossover(self.s, self.f):
            self.position.close()
            self.sell()
