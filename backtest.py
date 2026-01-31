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
"""

import argparse
import sys
from datetime import datetime

import backtrader as bt
import pandas as pd

import config
from config import BROKER, DATA, get_strategy, get_params, V8_TUNE_VARIATIONS, V8_FAST_TUNE_VARIATIONS
from results import (
    create_result,
    save_result,
    print_result,
    print_comparison_table,
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
        df = df[df.index <= end_date]
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
        """,
    )

    # Strategy selection
    parser.add_argument(
        "--strategy", "-s",
        default="v8",
        choices=["v3", "v6", "v7", "v8", "v8_fast", "v8_fast_sol", "v8_fast_vet", "v8_baseline", "v9", "v9_baseline", "v9_universal", "v9_sol", "v9_vet", "v10", "v10_baseline", "v10_sol"],
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
        choices=["final_value", "sharpe", "return"],
        help="Metric to optimize (default: final_value)"
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

    # Parameter overrides (common ones)
    parser.add_argument("--trailing-pct", type=float, help="Override trailing stop %")
    parser.add_argument("--fixed-stop-pct", type=float, help="Override fixed stop %")
    parser.add_argument("--min-drop-pct", type=float, help="Override min drop % (V8)")

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
        else:
            print(f"No result found with run ID: {args.detail}")
            return 1
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
