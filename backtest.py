#!/usr/bin/env python3
# backtest.py
"""
Unified CLI for running backtests.

Usage examples:
    python backtest.py                          # Run V8 with default params
    python backtest.py --strategy v7            # Run V7 strategy
    python backtest.py --strategy v8 --tune     # Run parameter tuning for V8
    python backtest.py --strategy v8_fast -o    # Run automated optimization
    python backtest.py -s v8_fast -o --trials 100  # Optimize with 100 trials
    python backtest.py --strategy v3 --data daily  # Run V3 with daily data
    python backtest.py --list-results           # Show recent results
    python backtest.py --compare v8             # Compare all V8 runs
    python backtest.py -s v8_fast --walk-forward  # Walk-forward validation
    python backtest.py --compare-all            # Compare all strategies head-to-head
"""

import argparse
import sys
from datetime import datetime

import backtrader as bt
import pandas as pd

import config
from config import BROKER, DATA, get_strategy, get_params, V8_TUNE_VARIATIONS, V8_FAST_TUNE_VARIATIONS
from regime import MarketRegime
from results import (
    create_result,
    save_result,
    print_result,
    print_trade_journal,
    print_comparison_table,
    print_ranked_table,
    print_regime_comparison,
    print_walk_forward_report,
    save_comparison,
    load_all_results,
    TradeTracker,
)


def load_data(source: str = "binance", timeframe: str = "15m"):
    """
    Load price data from CSV.

    Args:
        source: "binance" or "yfinance"
        timeframe: "15m" or "daily"

    Returns:
        tuple: (DataFrame, timestamp_col)
    """
    if timeframe == "daily":
        filepath = DATA.daily
        timestamp_col = DATA.daily_timestamp_col
    elif source == "binance":
        filepath = DATA.binance_15m
        timestamp_col = DATA.binance_timestamp_col
    else:
        filepath = DATA.yfinance_15m
        timestamp_col = DATA.yfinance_timestamp_col

    df = pd.read_csv(filepath, parse_dates=True, index_col=timestamp_col)
    return df


def setup_cerebro_multi_tf(df, strategy_class, params, cash=None, commission=None):
    """
    Set up cerebro with multi-timeframe data (for V6, V7, V8).

    Returns:
        cerebro instance ready to run
    """
    cerebro = bt.Cerebro(runonce=False, stdstats=True)

    data15 = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data15, name='15m')

    # Resample to higher timeframes
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

    cerebro.addstrategy(strategy_class, **params)

    # Add analyzers for trade statistics
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days, annualize=True)

    cerebro.broker.setcash(cash or BROKER.cash)
    cerebro.broker.setcommission(commission or BROKER.commission)

    return cerebro


def setup_cerebro_single_tf(df, strategy_class, params, cash=None, commission=None):
    """
    Set up cerebro with single timeframe data (for V3).

    Returns:
        cerebro instance ready to run
    """
    cerebro = bt.Cerebro(stdstats=True)

    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data, name='base')

    cerebro.addstrategy(strategy_class, **params)

    # Add analyzers for trade statistics
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days, annualize=True)

    cerebro.broker.setcash(cash or BROKER.cash)
    cerebro.broker.setcommission(commission or BROKER.commission)

    return cerebro


def run_backtest(
    strategy_name: str = "v8",
    data_source: str = "binance",
    params_override: dict = None,
    save: bool = True,
    verbose: bool = True,
    notes: str = "",
    start_date: str = None,
    end_date: str = None,
):
    """
    Run a backtest with the specified strategy.

    Args:
        strategy_name: Strategy to use (v3, v6, v7, v8, v8_baseline, v9)
        data_source: Data source (binance, yfinance, daily)
        params_override: Override default params with custom values
        save: Whether to save results to JSON
        verbose: Whether to print progress
        notes: Optional notes to save with result
        start_date: Start date filter (YYYY-MM-DD)
        end_date: End date filter (YYYY-MM-DD)

    Returns:
        BacktestResult object
    """
    # Get strategy class and params
    strategy_class = get_strategy(strategy_name)
    params = get_params(strategy_name)

    # Apply any overrides
    if params_override:
        params.update(params_override)

    # Determine data loading
    is_single_tf = strategy_name == "v3"
    timeframe = "daily" if is_single_tf or data_source == "daily" else "15m"
    source = data_source if data_source != "daily" else "binance"

    # Load data
    if verbose:
        print(f"Loading data from {data_source}...")
    df = load_data(source=source, timeframe=timeframe)

    # Filter by date range if specified
    if start_date:
        df = df[df.index >= start_date]
        if verbose:
            print(f"Filtering from {start_date}")
    if end_date:
        # Add time component so "2024-12-31" includes the full day
        end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        df = df[df.index <= end_ts]
        if verbose:
            print(f"Filtering to {end_date}")

    # Get date range
    start_date = str(df.index.min().date()) if len(df) > 0 else None
    end_date = str(df.index.max().date()) if len(df) > 0 else None

    # Calculate buy-and-hold benchmark
    buy_hold_value = None
    buy_hold_return_pct = None
    if len(df) > 0:
        first_price = df['close'].iloc[0]
        last_price = df['close'].iloc[-1]
        buy_hold_return_pct = (last_price - first_price) / first_price * 100
        # What would starting_value be worth if we just bought and held?
        buy_hold_value = (BROKER.cash) * (last_price / first_price)

    # Use a wrapper strategy to capture the instance even if ValueError occurs
    captured_strat = []

    class StrategyWrapper(strategy_class):
        def __init__(self):
            super().__init__()
            captured_strat.append(self)
            self.trade_log = []
            self._entry_context = None  # Strategies can set this at entry time
            self._max_pos_size = 0  # Track peak position size for current trade
            self._current_regime = {}  # Updated each bar by regime classifier

            # Initialize regime classifier if multi-TF data available
            # Need at least 5 feeds: 15m[0], 1h[1], 4h[2], weekly[3], daily[4]
            self._regime_classifier = None
            if len(self.datas) >= 5:
                try:
                    self._regime_classifier = MarketRegime(self.datas[4], self.datas[2])
                except Exception:
                    pass  # Skip regime if data feeds aren't compatible

        def next(self):
            super().next()
            # Update regime classification each bar
            if self._regime_classifier is not None:
                try:
                    self._current_regime = self._regime_classifier.classify()
                except Exception:
                    pass

        def notify_order(self, order):
            super().notify_order(order)
            if order.status == order.Completed:
                # Track peak position size for PnL % calculation
                current_size = abs(self.position.size) if self.position else 0
                if current_size > self._max_pos_size:
                    self._max_pos_size = current_size

        def notify_trade(self, trade):
            super().notify_trade(trade)
            if trade.isclosed:
                # Extract entry/exit datetimes from backtrader's numeric format
                try:
                    entry_dt = bt.num2date(trade.dtopen).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    entry_dt = str(trade.dtopen)
                try:
                    exit_dt = bt.num2date(trade.dtclose).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    exit_dt = str(trade.dtclose)

                entry_price = trade.price
                # Use tracked max position size (handles partials correctly)
                max_size = self._max_pos_size if self._max_pos_size > 0 else 1
                # Calculate effective exit price and PnL %
                if entry_price > 0:
                    exit_price = entry_price + (trade.pnl / max_size)
                    initial_value = entry_price * max_size
                    pnl_pct = (trade.pnl / initial_value) * 100
                else:
                    exit_price = entry_price
                    pnl_pct = 0.0

                # Determine direction from trade history
                direction = "long" if trade.long else "short"

                # Merge strategy-specific context with regime classification
                context = self._entry_context or {}
                if self._current_regime:
                    context.update(self._current_regime)

                record = {
                    "entry_dt": entry_dt,
                    "exit_dt": exit_dt,
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "size": round(max_size, 6),
                    "pnl": round(trade.pnl, 2),
                    "pnl_net": round(trade.pnlcomm, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "bars_held": trade.barlen,
                    "direction": direction,
                    "market_context": context,
                }
                self.trade_log.append(record)
                self._entry_context = None  # Reset for next trade
                self._max_pos_size = 0  # Reset for next trade

    # Set up cerebro with wrapper
    if is_single_tf:
        cerebro = setup_cerebro_single_tf(df, StrategyWrapper, params)
    else:
        cerebro = setup_cerebro_multi_tf(df, StrategyWrapper, params)

    starting_value = cerebro.broker.getvalue()

    if verbose:
        print(f"Strategy: {strategy_name}")
        print(f"Starting Portfolio Value: ${starting_value:,.2f}")
        print("Running backtest...")

    # Run backtest
    strat = None
    try:
        results = cerebro.run()
        if results and len(results) > 0:
            strat = results[0]
    except ValueError as e:
        # Known backtrader issue with resampled feeds at end of data
        if 'min()' in str(e) or 'empty' in str(e):
            if verbose:
                print("(Backtest completed - end of data reached)")
            # Use the captured strategy instance
            if captured_strat:
                strat = captured_strat[0]
        else:
            raise

    final_value = cerebro.broker.getvalue()

    # Extract trade statistics from analyzers
    total_trades = 0
    winning_trades = 0
    losing_trades = 0
    max_drawdown_pct = None
    sharpe_ratio = None

    if strat is not None:
        # Get trade analyzer results
        try:
            trade_analysis = strat.analyzers.trades.get_analysis()
            total_trades = trade_analysis.get('total', {}).get('closed', 0)
            winning_trades = trade_analysis.get('won', {}).get('total', 0)
            losing_trades = trade_analysis.get('lost', {}).get('total', 0)
        except (AttributeError, KeyError):
            pass

        # Get drawdown analyzer results
        try:
            dd_analysis = strat.analyzers.drawdown.get_analysis()
            max_drawdown_pct = dd_analysis.get('max', {}).get('drawdown', None)
        except (AttributeError, KeyError):
            pass

        # Get Sharpe ratio
        try:
            sharpe_analysis = strat.analyzers.sharpe.get_analysis()
            sharpe_ratio = sharpe_analysis.get('sharperatio', None)
        except (AttributeError, KeyError):
            pass

    if verbose:
        print(f"Final Portfolio Value: ${final_value:,.2f}")
        print(f"Total Return: {(final_value - starting_value) / starting_value * 100:+.2f}%")
        if total_trades > 0:
            print(f"Trades: {total_trades} (Won: {winning_trades}, Lost: {losing_trades})")
        if max_drawdown_pct is not None:
            print(f"Max Drawdown: {max_drawdown_pct:.2f}%")
        if sharpe_ratio is not None:
            print(f"Sharpe Ratio: {sharpe_ratio:.2f}")
        if buy_hold_value is not None:
            strategy_return = (final_value - starting_value) / starting_value * 100
            alpha = strategy_return - buy_hold_return_pct
            print(f"Buy & Hold: ${buy_hold_value:,.2f} ({buy_hold_return_pct:+.2f}%)")
            print(f"Alpha: {alpha:+.2f}%")

    # Extract per-trade journal from wrapper
    trade_log = None
    if strat is not None and hasattr(strat, 'trade_log') and strat.trade_log:
        trade_log = strat.trade_log

    # Create result
    result = create_result(
        strategy=strategy_name,
        params=params,
        starting_value=starting_value,
        final_value=final_value,
        data_source=data_source,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        start_date=start_date,
        end_date=end_date,
        buy_hold_value=buy_hold_value,
        buy_hold_return_pct=buy_hold_return_pct,
        notes=notes,
        trades=trade_log,
    )

    # Save result
    if save:
        filepath = save_result(result)
        if verbose:
            print(f"Result saved to: {filepath}")

    return result


def run_tune(strategy_name: str = "v8", verbose: bool = True):
    """
    Run parameter tuning with predefined variations.

    Args:
        strategy_name: Strategy to tune (v8 or v8_fast)
        verbose: Whether to print progress

    Returns:
        List of (name, result) tuples
    """
    if strategy_name == "v8":
        variations = V8_TUNE_VARIATIONS
    elif strategy_name == "v8_fast":
        variations = V8_FAST_TUNE_VARIATIONS
    else:
        print(f"Tuning currently only supported for v8 and v8_fast, not {strategy_name}")
        return []

    print(f"\n{'Test':<40} {'Final Value':>12} {'Return':>10} {'Trades':>8} {'Win%':>8}")
    print("-" * 82)

    results = []
    for name, params in variations:
        result = run_backtest(
            strategy_name=strategy_name,
            params_override=params,
            save=True,
            verbose=False,
            notes=f"Tune: {name}",
        )
        results.append((name, result))
        win_rate = f"{result.win_rate_pct:.0f}%" if result.win_rate_pct is not None else "N/A"
        print(f"{name:<40} ${result.final_value:>11,.2f} {result.total_return_pct:>+9.1f}% {result.total_trades:>8} {win_rate:>8}")

    print("-" * 82)

    if results:
        best_name, best_result = max(results, key=lambda x: x[1].total_return_pct)
        print(f"\nBest: {best_name} with ${best_result.final_value:,.2f} ({best_result.total_return_pct:+.1f}%)")

    return results


def run_walk_forward(
    strategy_name: str = "v8",
    data_source: str = "binance",
    train_pct: int = 70,
    n_trials: int = 50,
    metric: str = "final_value",
    verbose: bool = True,
    params_override: dict = None,
):
    """
    Run walk-forward validation: optimize on train period, test on unseen data.

    Args:
        strategy_name: Strategy to validate
        data_source: Data source
        train_pct: Percentage of data for training (default: 70%)
        n_trials: Number of optimization trials for training phase
        metric: Optimization metric
        verbose: Whether to print progress
        params_override: If provided, skip optimization and use these params directly

    Returns:
        Tuple of (in_sample_result, out_of_sample_result)
    """
    from optimizer import optimize

    # Load full data to determine split point
    is_single_tf = strategy_name == "v3"
    timeframe = "daily" if is_single_tf or data_source == "daily" else "15m"
    source = data_source if data_source != "daily" else "binance"
    df = load_data(source=source, timeframe=timeframe)

    total_rows = len(df)
    split_idx = int(total_rows * train_pct / 100)
    train_end = str(df.index[split_idx - 1].date())
    test_start = str(df.index[split_idx].date())

    if verbose:
        print(f"\nWalk-Forward Validation for {strategy_name}")
        print(f"Total data: {df.index.min().date()} to {df.index.max().date()} ({total_rows} bars)")
        print(f"Train period ({train_pct}%): {df.index.min().date()} to {train_end} ({split_idx} bars)")
        print(f"Test period ({100 - train_pct}%): {test_start} to {df.index.max().date()} ({total_rows - split_idx} bars)")

    if params_override:
        # Skip optimization, use provided params directly
        best_params = params_override
        if verbose:
            print(f"\n--- Skipping optimization, using provided params ---")
            for k, v in sorted(best_params.items()):
                print(f"  {k}: {v}")
    else:
        # Phase 1: Optimize on training data
        if verbose:
            print(f"\n--- Phase 1: Optimizing on training data ({n_trials} trials) ---")

        # Map strategy names to their optimizer base name
        optimizer_strategy = strategy_name.split("_sol")[0].split("_vet")[0].split("_baseline")[0].split("_universal")[0]

        study = optimize(
            strategy=optimizer_strategy,
            n_trials=n_trials,
            metric=metric,
            start_date=str(df.index.min().date()),
            end_date=train_end,
        )

        best_params = study.best_trial.params
        if verbose:
            print(f"\nBest training params (Trial #{study.best_trial.number}):")
            for k, v in sorted(best_params.items()):
                print(f"  {k}: {v}")

    # Phase 2: Run in-sample with best params
    if verbose:
        print(f"\n--- Phase 2: In-sample backtest ---")

    in_sample = run_backtest(
        strategy_name=strategy_name,
        data_source=data_source,
        params_override=best_params,
        save=False,
        verbose=verbose,
        notes=f"Walk-forward in-sample ({train_pct}%)",
        end_date=train_end,
    )

    # Phase 3: Run out-of-sample with same params
    if verbose:
        print(f"\n--- Phase 3: Out-of-sample backtest ---")

    out_of_sample = run_backtest(
        strategy_name=strategy_name,
        data_source=data_source,
        params_override=best_params,
        save=False,
        verbose=verbose,
        notes=f"Walk-forward out-of-sample ({100 - train_pct}%)",
        start_date=test_start,
    )

    # Print report
    print_walk_forward_report(in_sample, out_of_sample, train_pct)

    return in_sample, out_of_sample


def run_compare_all(
    strategies: list = None,
    data_source: str = "binance",
    start_date: str = None,
    end_date: str = None,
    verbose: bool = True,
):
    """
    Run all registered strategies on the same data and compare results.

    Args:
        strategies: List of strategy names to compare (None = all primary strategies)
        data_source: Data source
        start_date: Start date filter
        end_date: End date filter
        verbose: Whether to print progress

    Returns:
        List of BacktestResult objects
    """
    if strategies is None:
        # Use primary strategies only (skip asset-specific variants and baselines)
        strategies = ["v3", "v6", "v7", "v8", "v8_fast", "v9", "v11", "v13", "v14", "v15", "v16", "v17"]

    if verbose:
        print(f"\nComparing {len(strategies)} strategies head-to-head")
        print(f"Data source: {data_source}")
        if start_date:
            print(f"Start date: {start_date}")
        if end_date:
            print(f"End date: {end_date}")
        print("-" * 50)

    results = []
    for name in strategies:
        if verbose:
            print(f"\nRunning {name}...")
        try:
            result = run_backtest(
                strategy_name=name,
                data_source=data_source,
                save=False,
                verbose=False,
                notes="compare-all",
                start_date=start_date,
                end_date=end_date,
            )
            results.append(result)
            if verbose:
                ret = result.total_return_pct
                print(f"  {name}: {ret:+.1f}% return, {result.total_trades} trades")
        except Exception as e:
            if verbose:
                print(f"  {name}: FAILED - {e}")

    if results:
        print_ranked_table(results)

        # Save comparison
        filepath = save_comparison(results, label="compare_all")
        if verbose:
            print(f"\nComparison saved to: {filepath}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="SOL/USD Backtesting CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python backtest.py                          # Run V8 with default params
  python backtest.py --strategy v7            # Run V7 strategy
  python backtest.py -s v8_fast tune          # Run parameter tuning
  python backtest.py -s v8_fast optimize      # Run automated optimization
  python backtest.py -s v8_fast --asset SUI   # Run on SUI/USD data
  python backtest.py -s v8_fast --asset VET   # Run on VET/USD data
  python backtest.py --list-results           # Show recent results
  python backtest.py --compare v8             # Compare V8 runs
  python backtest.py -s v8_fast --walk-forward  # Walk-forward validation
  python backtest.py --compare-all            # Compare all strategies
  python backtest.py --compare-all --strategies v8_fast,v9,v13  # Compare subset
        """,
    )

    # Strategy selection
    parser.add_argument(
        "--strategy", "-s",
        default="v8",
        choices=["v3", "v6", "v7", "v8", "v8_fast", "v8_fast_sol", "v8_fast_vet", "v8_baseline", "v9", "v9_baseline", "v9_universal", "v9_sol", "v9_vet", "v11", "v13", "v14", "v15", "v15_baseline", "v15_sol", "v15_btc", "v15_eth", "v16", "v17", "v18"],
        help="Strategy to run (default: v8)"
    )

    # Data source
    parser.add_argument(
        "--data", "-d",
        default="binance",
        choices=["binance", "yfinance", "daily"],
        help="Data source (default: binance)"
    )

    # Asset selection
    parser.add_argument(
        "--asset", "-a",
        default=None,
        help="Asset to backtest (e.g., SOL, SUI, VET). Requires data file in data/ folder."
    )

    # Tuning mode
    parser.add_argument(
        "--tune", "-t",
        action="store_true",
        help="Run parameter tuning instead of single backtest"
    )

    # Optimization mode
    parser.add_argument(
        "--optimize", "-o",
        action="store_true",
        help="Run automated parameter optimization using Optuna"
    )

    parser.add_argument(
        "--trials",
        type=int,
        default=50,
        help="Number of optimization trials (default: 50)"
    )

    parser.add_argument(
        "--metric",
        default="final_value",
        choices=["final_value", "sharpe", "return", "win_rate", "expectancy"],
        help="Metric to optimize (default: final_value, use expectancy for v15)"
    )

    # Result management
    parser.add_argument(
        "--list-results", "-l",
        action="store_true",
        help="List recent backtest results"
    )

    parser.add_argument(
        "--compare", "-c",
        metavar="STRATEGY",
        help="Compare results for a specific strategy"
    )

    parser.add_argument(
        "--detail",
        metavar="RUN_ID",
        help="Show detailed result for a specific run ID"
    )
    parser.add_argument(
        "--trades",
        action="store_true",
        help="Show per-trade journal (use with --detail or after a backtest run)"
    )

    # Output control
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save results to JSON"
    )

    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Minimal output"
    )

    parser.add_argument(
        "--notes", "-n",
        default="",
        help="Add notes to the result"
    )

    # Date range filtering
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date for backtest (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date for backtest (YYYY-MM-DD)"
    )

    # Walk-forward validation
    parser.add_argument(
        "--walk-forward", "-wf",
        action="store_true",
        help="Run walk-forward validation (train/test split)"
    )
    parser.add_argument(
        "--params",
        type=str,
        help="Override params for walk-forward (e.g., 'channel_period=78,atr_trail_mult=6.25')"
    )
    parser.add_argument(
        "--train-pct",
        type=int,
        default=70,
        help="Percentage of data for training in walk-forward (default: 70)"
    )

    # Strategy comparison
    parser.add_argument(
        "--compare-all",
        action="store_true",
        help="Compare all primary strategies head-to-head on same data"
    )
    parser.add_argument(
        "--compare-regimes",
        action="store_true",
        help="Compare strategies by market regime (shows best strategy per regime)"
    )
    parser.add_argument(
        "--strategies",
        type=str,
        default=None,
        help="Comma-separated list of strategies to compare (default: all primary)"
    )

    # Parameter overrides (common ones)
    parser.add_argument("--trailing-pct", type=float, help="Override trailing stop pct")
    parser.add_argument("--fixed-stop-pct", type=float, help="Override fixed stop pct")
    parser.add_argument("--min-drop-pct", type=float, help="Override min drop pct (V8)")

    # Positional command (optional)
    parser.add_argument(
        "command",
        nargs="?",
        choices=["optimize", "tune"],
        help="Command to run: 'optimize' or 'tune'"
    )

    args = parser.parse_args()

    # Set active asset if specified
    if args.asset:
        import config
        config.ACTIVE_ASSET = args.asset.upper()
        print(f"Using asset: {config.ACTIVE_ASSET}/USD")

    # Handle result viewing commands
    if args.list_results:
        results = load_all_results()
        print_comparison_table(results)
        return 0

    if args.compare:
        results = load_all_results()
        filtered = [r for r in results if args.compare.lower() in r.strategy.lower()]
        print_comparison_table(filtered)
        return 0

    if args.detail:
        results = load_all_results()
        found = [r for r in results if r.run_id == args.detail]
        if found:
            print_result(found[0])
            if args.trades:
                print_trade_journal(found[0])
        else:
            print(f"No result found with run ID: {args.detail}")
            return 1
        return 0

    # Handle walk-forward validation
    if args.walk_forward:
        # Parse --params if provided
        params_override = None
        if args.params:
            params_override = {}
            for pair in args.params.split(","):
                k, v = pair.strip().split("=")
                # Auto-detect type: int or float
                try:
                    params_override[k] = int(v)
                except ValueError:
                    params_override[k] = float(v)

        run_walk_forward(
            strategy_name=args.strategy,
            data_source=args.data,
            train_pct=args.train_pct,
            n_trials=args.trials,
            metric=args.metric,
            verbose=not args.quiet,
            params_override=params_override,
        )
        return 0

    # Handle strategy comparison
    if args.compare_all:
        strategy_list = None
        if args.strategies:
            strategy_list = [s.strip() for s in args.strategies.split(",")]
        run_compare_all(
            strategies=strategy_list,
            data_source=args.data,
            start_date=args.start_date,
            end_date=args.end_date,
            verbose=not args.quiet,
        )
        return 0

    # Handle regime comparison
    if args.compare_regimes:
        strategy_list = None
        if args.strategies:
            strategy_list = [s.strip() for s in args.strategies.split(",")]
        results = run_compare_all(
            strategies=strategy_list,
            data_source=args.data,
            start_date=args.start_date,
            end_date=args.end_date,
            verbose=not args.quiet,
        )
        if results:
            print_regime_comparison(results)
        return 0

    # Handle tuning mode
    if args.tune or args.command == "tune":
        run_tune(args.strategy, verbose=not args.quiet)
        return 0

    # Handle optimization mode
    if args.optimize or args.command == "optimize":
        from optimizer import optimize, print_results
        study = optimize(
            strategy=args.strategy,
            n_trials=args.trials,
            metric=args.metric,
        )
        print_results(study, args.strategy)
        return 0

    # Build parameter overrides from CLI args
    overrides = {}
    if args.trailing_pct is not None:
        overrides["trailing_pct"] = args.trailing_pct
    if args.fixed_stop_pct is not None:
        overrides["fixed_stop_pct"] = args.fixed_stop_pct
    if args.min_drop_pct is not None:
        overrides["min_drop_pct"] = args.min_drop_pct

    # Run single backtest
    result = run_backtest(
        strategy_name=args.strategy,
        data_source=args.data,
        params_override=overrides if overrides else None,
        save=not args.no_save,
        verbose=not args.quiet,
        notes=args.notes,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    if not args.quiet:
        print_result(result)
        if args.trades:
            print_trade_journal(result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
