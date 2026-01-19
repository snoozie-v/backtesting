# run_backtestv3.py
"""
Legacy single-timeframe backtest runner for V3 strategy.
For the new unified CLI, use: python backtest.py --strategy v3 --data daily

This file is kept for backwards compatibility.
"""

import backtrader as bt
import pandas as pd

from config import BROKER, DATA, get_params

# Single-timeframe strategies
from strategies.sol_strategy_v1 import SolStrategyV1
from strategies.sol_strategy_v3 import SolStrategyV3


if __name__ == '__main__':
    # Get params from config
    params = get_params("v3")

    cerebro = bt.Cerebro(stdstats=True)

    # Load daily data from config path
    df = pd.read_csv(DATA.daily, parse_dates=True, index_col=DATA.daily_timestamp_col)
    data = bt.feeds.PandasData(dataname=df)

    # Add single data feed - no resampling
    cerebro.adddata(data, name='base')

    # Add strategy with params from config
    cerebro.addstrategy(SolStrategyV3, **params)

    cerebro.broker.setcash(BROKER.cash)
    cerebro.broker.setcommission(BROKER.commission)

    print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
    print('Strategy: v3 | Params from config.py')
    cerebro.run()

    final_value = cerebro.broker.getvalue()
    print('Final Portfolio Value: %.2f' % final_value)
    print('Total Return: %.2f%%' % ((final_value - BROKER.cash) / BROKER.cash * 100))

    print('\nTip: Use "python backtest.py --strategy v3 --data daily" for the new CLI.')
