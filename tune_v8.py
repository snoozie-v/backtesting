# tune_v8.py
"""
Legacy parameter tuning for V8 strategy.
For the new unified CLI, use: python backtest.py --tune

This file is kept for backwards compatibility.
"""

import backtrader as bt
import pandas as pd

from config import BROKER, DATA, V8_TUNE_VARIATIONS
from strategies.sol_strategy_v8 import SolStrategyV8


def run_backtest(params):
    """Run backtest with given parameters, return final value"""
    cerebro = bt.Cerebro(runonce=False, stdstats=False)

    df = pd.read_csv(DATA.binance_15m, parse_dates=True, index_col=DATA.binance_timestamp_col)
    data15 = bt.feeds.PandasData(dataname=df)

    cerebro.adddata(data15, name='15m')
    cerebro.resampledata(data15, name='1h', timeframe=bt.TimeFrame.Minutes, compression=60, bar2edge=True, rightedge=True)
    cerebro.resampledata(data15, name='4h', timeframe=bt.TimeFrame.Minutes, compression=240, bar2edge=True, rightedge=True)
    cerebro.resampledata(data15, name='weekly', timeframe=bt.TimeFrame.Weeks, compression=1, bar2edge=True, rightedge=True)
    cerebro.resampledata(data15, name='daily', timeframe=bt.TimeFrame.Days, compression=1, bar2edge=True, rightedge=True)

    cerebro.addstrategy(SolStrategyV8, **params)
    cerebro.broker.setcash(BROKER.cash)
    cerebro.broker.setcommission(BROKER.commission)

    try:
        cerebro.run()
    except ValueError:
        pass

    return cerebro.broker.getvalue()


if __name__ == '__main__':
    # Use parameter variations from config
    tests = V8_TUNE_VARIATIONS

    print(f"{'Test':<45} {'Final Value':>12} {'Return':>10}")
    print('-' * 70)

    results = []
    for name, params in tests:
        final = run_backtest(params)
        ret = (final - BROKER.cash) / BROKER.cash * 100
        results.append((name, final, ret))
        print(f"{name:<45} ${final:>11,.2f} {ret:>9.1f}%")

    print('-' * 70)
    best = max(results, key=lambda x: x[1])
    print(f"\nBest: {best[0]} with ${best[1]:,.2f} ({best[2]:.1f}%)")

    print('\nTip: Use "python backtest.py --tune" for the new CLI with result saving.')
