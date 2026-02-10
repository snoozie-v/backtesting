# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a cryptocurrency backtesting framework for SOL/USD and other assets using the backtrader library with multi-timeframe analysis. Active strategies: V3, V6, V7, V8, V8 Fast, V9, V11, V13, V14, V15, V16, V17.

## Commands

```bash
# Run backtest (main entry point)
python backtest.py

# Run optimizer
python optimizer.py

# Fetch historical 15m data from Binance (recommended - full history)
python fetch_sol_binance_15m.py

# Fetch 15m data from yfinance (limited to ~60 days)
python fetch_sol_data.py
```

There is no formal test suite - strategy validation is done manually by running backtests and examining output logs and P&L metrics.

## Dependencies

Key packages:
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

### Risk Management Model (R-Based, Leveraged)
- **Leverage**: 100x on crypto perpetuals (BTC, SOL, ETH)
- **Risk per trade**: 3% of account at the stop loss
- **Position sizing**: `risk_amount / stop_distance` (not cash-based)
- **Partial exits**: 30% at 1R, 30% at 2R, 30% at 3R, 10% runner with ATR trail
- **Stop ratcheting**: Breakeven at 1R, +1R at 2R, +2R at 3R
- **1R definition**: Strategy-specific (e.g., ATR * multiplier)
- **Commission**: 0.1% on notional value
- **Starting cash**: $10,000 (reference amount — position sizes are risk-based)
- **Shared module**: `risk_manager.py` provides `RiskManager` class used by all strategies

## Strategy Structure

Strategies live in `strategies/` and follow a versioned naming pattern. All are registered in `config.py`. V10 and V12 were deleted after failing walk-forward validation.

**Walk-forward validated strategies (only these are trustworthy):**
- V8 Fast — GOOD (74% OOS retention, ATR-based exits, pattern entries, partial profits)
- V11 — FAIR but NOT USED (34% OOS retention, but fixed R:R ratios make exits non-adaptive)

**Remaining strategies (failed walk-forward, kept for reference):**
- V3, V6, V7 — legacy, no optimizer objectives
- V8 — FAIL (v8_fast is the improved version)
- V9 — FAIL (0 OOS trades, fixed vol thresholds)
- V13 — POOR (13% retained, regime-sensitive entries despite ATR exits)
- V14 — FAIL (barely profitable IS, too many trades with tiny edge)
- V15 — FAIL (overfit, -53% OOS)
- V16 — FAIL (too complex, 3 entry types = overfitting)
- V17 — FAIL (IS +16%, OOS -15%, wick rejection + pullback entries, too many params)

Each strategy class:
- Inherits from `bt.Strategy`
- Defines parameters in a `params` tuple
- Implements `__init__()` for indicator setup
- Implements `next()` for bar-by-bar logic
- Uses `notify_order()` and `notify_trade()` for execution tracking

**IMPORTANT: Before creating or modifying strategies, read `strategies/STRATEGY_NOTES.md`** — it documents walk-forward results for every strategy, why past strategies failed, design principles that work vs don't, and lessons learned. Key takeaways: use ATR-based exits (not fixed %), use pattern-based entries (not indicator crossovers), implement R-based partial profit-taking (30/30/30/10), risk-based position sizing (3% at stop), keep 20-60 trades/year, and always validate with `--walk-forward`.

**ALL new strategies MUST use R-based risk management** via `risk_manager.py`:
- Import `from risk_manager import RiskManager`
- Size positions with `risk_mgr.calculate_position_size(equity, stop_distance)`
- Exit at 1R/2R/3R with `risk_mgr.partial_schedule` and trail runner
- Include `stop_distance` and `risk_pct` in `_entry_context` for R-multiple tracking
