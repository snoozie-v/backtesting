# run_backtest.py
"""
Legacy multi-timeframe backtest runner.
For the new unified CLI, use: python backtest.py

This file is kept for backwards compatibility.
"""

import backtrader as bt
import pandas as pd

# Import configuration
from config import BROKER, DATA, get_strategy, get_params

# Import strategies (for direct use if needed)
from strategies.sol_strategy_v6 import SolStrategyV6
from strategies.sol_strategy_v7 import SolStrategyV7
from strategies.sol_strategy_v8 import SolStrategyV8


if __name__ == '__main__':
    # Use centralized config
    params = get_params("v8")
    strategy_class = get_strategy("v8")

    # runonce=False is critical for multi-resampling stability
    cerebro = bt.Cerebro(runonce=False, stdstats=True)

    # Load 15m data from configured path
    df = pd.read_csv(DATA.binance_15m, parse_dates=True, index_col=DATA.binance_timestamp_col)
    data15 = bt.feeds.PandasData(dataname=df)

    # Add base 15m data
    cerebro.adddata(data15, name='15m')

    # Resample higher timeframes
    cerebro.resampledata(data15, name='1h',
                         timeframe=bt.TimeFrame.Minutes,
                         compression=60,
                         bar2edge=True,
                         rightedge=True)

    cerebro.resampledata(data15, name='4h',
                         timeframe=bt.TimeFrame.Minutes,
                         compression=240,
                         bar2edge=True,
                         rightedge=True)

    cerebro.resampledata(data15, name='weekly',
                         timeframe=bt.TimeFrame.Weeks,
                         compression=1,
                         bar2edge=True,
                         rightedge=True)

    cerebro.resampledata(data15, name='daily',
                         timeframe=bt.TimeFrame.Days,
                         compression=1,
                         bar2edge=True,
                         rightedge=True)

    # Add strategy with params from config
    cerebro.addstrategy(strategy_class, **params)

    # Use broker settings from config
    cerebro.broker.setcash(BROKER.cash)
    cerebro.broker.setcommission(BROKER.commission)

    print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
    print('Running backtest... (bar-by-bar mode)')
    print(f'Strategy: v8 | Params from config.py')

    try:
        cerebro.run()
    except ValueError as e:
        if 'min()' in str(e) or 'empty' in str(e):
            print('(Backtest completed - end of data reached)')
        else:
            raise

    final_value = cerebro.broker.getvalue()
    print('Final Portfolio Value: %.2f' % final_value)
    print('Total Return: %.2f%%' % ((final_value - BROKER.cash) / BROKER.cash * 100))

    # Tip: Use the new CLI for better features
    print('\nTip: Use "python backtest.py" for the new unified CLI with result tracking.')
