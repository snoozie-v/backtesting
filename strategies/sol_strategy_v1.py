# strategies/sol_strategy_v1.py
import backtrader as bt

class SolStrategyV1(bt.Strategy):
    params = (
        ('period', 20),           # example param - you will change these
    )

    def __init__(self):
        self.sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.period)
        # add more indicators here later...

    def next(self):
        if not self.position:                    # not in market
            if self.data.close[0] > self.sma[0]: # simple example condition
                self.buy(size=1.0)               # buy 1 SOL (adjust size!)
        else:
            if self.data.close[0] < self.sma[0]:
                self.sell(size=1.0)
