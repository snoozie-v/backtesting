# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a cryptocurrency backtesting framework for SOL/USD using the backtrader library with multi-timeframe analysis. Strategies have evolved through versions V1-V8, with V8 being the current "rounded-bottom catcher" strategy.

## Commands

```bash
# Run backtest (main entry point)
python run_backtest.py

# Fetch historical 15m data from Binance (recommended - full history)
python fetch_sol_binance_15m.py

# Fetch 15m data from yfinance (limited to ~60 days)
python fetch_sol_data.py
```

There is no formal test suite - strategy validation is done manually by running backtests and examining output logs and P&L metrics.

## Dependencies

Key packages (not yet in requirements.txt):
- `backtrader` - backtesting framework
- `pandas` - data handling
- `yfinance` - price data fetching
- `ccxt` - Binance exchange API access

## Architecture

### Data Flow
1. Fetch OHLCV data from Binance (CCXT) or yfinance → CSV in `data/`
2. Load CSV into pandas DataFrame with columns: open, high, low, close, volume
3. Feed into backtrader via PandasData
4. Resample 15m base data into 1h, 4h, daily, weekly timeframes
5. Execute strategy via cerebro engine

### Multi-Timeframe Data Access
Data feeds are indexed numerically:
- `self.datas[0]` - 15m (base)
- `self.datas[1]` - 1h
- `self.datas[2]` - 4h
- `self.datas[3]` - weekly
- `self.datas[4]` - daily

### Key Backtrader Patterns
- Indicators: use `btind` (backtrader.indicators) or `btlib` (TA-Lib wrapper)
- Historical data: negative indexing, e.g., `self.data.close[-1]` for prior bar
- Datetime: `self.data.datetime.datetime(0)` or `.date(0)`
- Position management: `self.buy()`, `self.sell()`, `self.position`

### Cerebro Configuration
```python
cerebro.run(runonce=False)  # Required for multi-TF stability
# Resampling: bar2edge=True, rightedge=True
```

### Risk Management Defaults
- Broker cash: $10,000
- Commission: 0.1%
- Position sizing: 98% of available cash per entry

## Strategy Structure

Strategies live in `strategies/` and follow a versioned naming pattern (`sol_strategy_v1.py` through `sol_strategy_v8.py`).

Each strategy class:
- Inherits from `bt.Strategy`
- Defines parameters in a `params` tuple
- Implements `__init__()` for indicator setup
- Implements `next()` for bar-by-bar logic
- Uses `notify_order()` and `notify_trade()` for execution tracking

To create a new strategy, copy the latest version and modify the entry/exit logic.
