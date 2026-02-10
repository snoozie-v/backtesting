# results.py
"""
Result persistence and run comparison for backtesting.
Saves backtest results to JSON files and provides analysis tools.
"""

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


RESULTS_DIR = Path("results")


@dataclass
class BacktestResult:
    """Container for backtest run results."""
    # Run metadata
    run_id: str
    timestamp: str
    strategy: str
    data_source: str

    # Parameters used
    params: Dict[str, Any]

    # Portfolio metrics
    starting_value: float
    final_value: float
    total_return_pct: float
    max_drawdown_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None

    # Trade metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: Optional[float] = None
    avg_trade_pct: Optional[float] = None

    # Date range
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    # Buy-and-hold benchmark
    buy_hold_value: Optional[float] = None
    buy_hold_return_pct: Optional[float] = None
    alpha_pct: Optional[float] = None  # Strategy return - buy/hold return

    # R-based metrics (None for backward compat with old results)
    avg_r_multiple: Optional[float] = None  # Average R per trade (R-expectancy)
    best_r: Optional[float] = None          # Largest winning R-multiple
    worst_r: Optional[float] = None         # Largest losing R-multiple (should be ~-1R)

    # Notes
    notes: str = ""

    # Per-trade journal (None for backward compat with old JSONs)
    trades: Optional[List[Dict[str, Any]]] = None


def ensure_results_dir():
    """Create results directory if it doesn't exist."""
    RESULTS_DIR.mkdir(exist_ok=True)


def generate_run_id() -> str:
    """Generate a unique run ID based on timestamp."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_result(result: BacktestResult) -> str:
    """
    Save a backtest result to JSON file.
    Returns the path to the saved file.
    """
    ensure_results_dir()

    filename = f"{result.run_id}_{result.strategy}.json"
    filepath = RESULTS_DIR / filename

    with open(filepath, "w") as f:
        json.dump(asdict(result), f, indent=2, default=str)

    return str(filepath)


def load_result(filepath: str) -> BacktestResult:
    """Load a backtest result from JSON file."""
    with open(filepath, "r") as f:
        data = json.load(f)
    # Handle old JSONs that don't have newer fields
    valid_fields = {f.name for f in BacktestResult.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return BacktestResult(**filtered)


def load_all_results() -> List[BacktestResult]:
    """Load all results from the results directory."""
    ensure_results_dir()

    results = []
    for filepath in RESULTS_DIR.glob("*.json"):
        try:
            results.append(load_result(str(filepath)))
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Warning: Could not load {filepath}: {e}")

    # Sort by timestamp (newest first)
    results.sort(key=lambda r: r.timestamp, reverse=True)
    return results


def create_result(
    strategy: str,
    params: Dict[str, Any],
    starting_value: float,
    final_value: float,
    data_source: str = "binance",
    total_trades: int = 0,
    winning_trades: int = 0,
    losing_trades: int = 0,
    max_drawdown_pct: Optional[float] = None,
    sharpe_ratio: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    buy_hold_value: Optional[float] = None,
    buy_hold_return_pct: Optional[float] = None,
    notes: str = "",
    trades: Optional[List[Dict[str, Any]]] = None,
) -> BacktestResult:
    """
    Create a BacktestResult with calculated metrics.
    """
    run_id = generate_run_id()
    timestamp = datetime.now().isoformat()
    total_return_pct = (final_value - starting_value) / starting_value * 100

    win_rate_pct = None
    if total_trades > 0:
        win_rate_pct = winning_trades / total_trades * 100

    avg_trade_pct = None
    if total_trades > 0:
        avg_trade_pct = total_return_pct / total_trades

    # Calculate alpha (outperformance vs buy-and-hold)
    alpha_pct = None
    if buy_hold_return_pct is not None:
        alpha_pct = total_return_pct - buy_hold_return_pct

    # Calculate R-based metrics from trade journal
    avg_r_multiple = None
    best_r = None
    worst_r = None
    if trades:
        r_values = [t.get("r_multiple") for t in trades if t.get("r_multiple") is not None]
        if r_values:
            avg_r_multiple = round(sum(r_values) / len(r_values), 2)
            best_r = round(max(r_values), 2)
            worst_r = round(min(r_values), 2)

    return BacktestResult(
        run_id=run_id,
        timestamp=timestamp,
        strategy=strategy,
        data_source=data_source,
        params=params,
        starting_value=starting_value,
        final_value=final_value,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate_pct=win_rate_pct,
        avg_trade_pct=avg_trade_pct,
        start_date=start_date,
        end_date=end_date,
        buy_hold_value=buy_hold_value,
        buy_hold_return_pct=buy_hold_return_pct,
        alpha_pct=alpha_pct,
        avg_r_multiple=avg_r_multiple,
        best_r=best_r,
        worst_r=worst_r,
        notes=notes,
        trades=trades,
    )


def print_result(result: BacktestResult):
    """Print a formatted summary of a backtest result."""
    print(f"\n{'='*60}")
    print(f"Run ID: {result.run_id}")
    print(f"Strategy: {result.strategy}")
    print(f"Timestamp: {result.timestamp}")
    print(f"Data Source: {result.data_source}")
    if result.start_date and result.end_date:
        print(f"Date Range: {result.start_date} to {result.end_date}")
    print(f"{'='*60}")

    print(f"\nPortfolio Performance:")
    print(f"  Starting Value: ${result.starting_value:,.2f}")
    print(f"  Final Value:    ${result.final_value:,.2f}")
    print(f"  Total Return:   {result.total_return_pct:+.2f}%")
    if result.max_drawdown_pct is not None:
        print(f"  Max Drawdown:   {result.max_drawdown_pct:.2f}%")
    if result.sharpe_ratio is not None:
        print(f"  Sharpe Ratio:   {result.sharpe_ratio:.2f}")

    if result.buy_hold_value is not None:
        print(f"\nBuy & Hold Benchmark:")
        print(f"  Buy & Hold Value:  ${result.buy_hold_value:,.2f}")
        print(f"  Buy & Hold Return: {result.buy_hold_return_pct:+.2f}%")
        if result.alpha_pct is not None:
            alpha_label = "Alpha (outperformance)" if result.alpha_pct >= 0 else "Alpha (underperformance)"
            print(f"  {alpha_label}: {result.alpha_pct:+.2f}%")

    if result.total_trades > 0:
        print(f"\nTrade Statistics:")
        print(f"  Total Trades:   {result.total_trades}")
        print(f"  Winning:        {result.winning_trades}")
        print(f"  Losing:         {result.losing_trades}")
        if result.win_rate_pct is not None:
            print(f"  Win Rate:       {result.win_rate_pct:.1f}%")
        if result.avg_trade_pct is not None:
            print(f"  Avg Trade:      {result.avg_trade_pct:+.2f}%")
        if result.avg_r_multiple is not None:
            print(f"  R-Expectancy:   {result.avg_r_multiple:+.2f}R per trade")
        if result.best_r is not None:
            print(f"  Best Trade:     {result.best_r:+.1f}R")
        if result.worst_r is not None:
            print(f"  Worst Trade:    {result.worst_r:+.1f}R")

    print(f"\nParameters:")
    for key, value in result.params.items():
        print(f"  {key}: {value}")

    if result.notes:
        print(f"\nNotes: {result.notes}")

    print(f"{'='*60}\n")


def print_comparison_table(results: List[BacktestResult], limit: int = 10):
    """Print a comparison table of recent results."""
    if not results:
        print("No results to compare.")
        return

    results = results[:limit]

    print(f"\n{'Run ID':<18} {'Strategy':<10} {'Final Value':>12} {'Return':>10} {'Trades':>7} {'Win%':>7} {'MaxDD':>8} {'Sharpe':>8}")
    print("-" * 95)

    for r in results:
        win_rate = f"{r.win_rate_pct:.0f}%" if r.win_rate_pct is not None else "N/A"
        max_dd = f"{r.max_drawdown_pct:.1f}%" if r.max_drawdown_pct is not None else "N/A"
        sharpe = f"{r.sharpe_ratio:.2f}" if r.sharpe_ratio is not None else "N/A"
        print(f"{r.run_id:<18} {r.strategy:<10} ${r.final_value:>10,.2f} {r.total_return_pct:>+9.1f}% {r.total_trades:>7} {win_rate:>7} {max_dd:>8} {sharpe:>8}")

    print("-" * 95)

    # Summary stats
    if len(results) > 1:
        best = max(results, key=lambda r: r.total_return_pct)
        worst = min(results, key=lambda r: r.total_return_pct)
        avg_return = sum(r.total_return_pct for r in results) / len(results)

        print(f"\nBest:  {best.run_id} ({best.strategy}) with {best.total_return_pct:+.1f}%")
        print(f"Worst: {worst.run_id} ({worst.strategy}) with {worst.total_return_pct:+.1f}%")
        print(f"Average Return: {avg_return:+.1f}%")


def print_ranked_table(results: List[BacktestResult]):
    """Print a ranked comparison table for strategy head-to-head comparison."""
    if not results:
        print("No results to compare.")
        return

    # Sort by return for ranking
    ranked = sorted(results, key=lambda r: r.total_return_pct, reverse=True)

    print(f"\n{'Rank':<6} {'Strategy':<12} {'Return':>10} {'Sharpe':>8} {'MaxDD':>8} {'Win%':>7} {'Trades':>7} {'Alpha':>10}")
    print("=" * 78)

    for i, r in enumerate(ranked, 1):
        win_rate = f"{r.win_rate_pct:.0f}%" if r.win_rate_pct is not None else "N/A"
        max_dd = f"{r.max_drawdown_pct:.1f}%" if r.max_drawdown_pct is not None else "N/A"
        sharpe = f"{r.sharpe_ratio:.2f}" if r.sharpe_ratio is not None else "N/A"
        alpha = f"{r.alpha_pct:+.1f}%" if r.alpha_pct is not None else "N/A"
        print(f"  {i:<4} {r.strategy:<12} {r.total_return_pct:>+9.1f}% {sharpe:>8} {max_dd:>8} {win_rate:>7} {r.total_trades:>7} {alpha:>10}")

    print("=" * 78)

    # Highlight best by each metric
    print("\nBest by metric:")
    best_return = max(ranked, key=lambda r: r.total_return_pct)
    print(f"  Return:   {best_return.strategy} ({best_return.total_return_pct:+.1f}%)")

    sharpe_candidates = [r for r in ranked if r.sharpe_ratio is not None]
    if sharpe_candidates:
        best_sharpe = max(sharpe_candidates, key=lambda r: r.sharpe_ratio)
        print(f"  Sharpe:   {best_sharpe.strategy} ({best_sharpe.sharpe_ratio:.2f})")

    dd_candidates = [r for r in ranked if r.max_drawdown_pct is not None]
    if dd_candidates:
        best_dd = min(dd_candidates, key=lambda r: r.max_drawdown_pct)
        print(f"  Max DD:   {best_dd.strategy} ({best_dd.max_drawdown_pct:.1f}%)")

    wr_candidates = [r for r in ranked if r.win_rate_pct is not None and r.total_trades > 0]
    if wr_candidates:
        best_wr = max(wr_candidates, key=lambda r: r.win_rate_pct)
        print(f"  Win Rate: {best_wr.strategy} ({best_wr.win_rate_pct:.0f}%)")

    alpha_candidates = [r for r in ranked if r.alpha_pct is not None]
    if alpha_candidates:
        best_alpha = max(alpha_candidates, key=lambda r: r.alpha_pct)
        print(f"  Alpha:    {best_alpha.strategy} ({best_alpha.alpha_pct:+.1f}%)")


def save_comparison(results: List[BacktestResult], label: str = "compare_all") -> str:
    """Save a strategy comparison to a single JSON file."""
    ensure_results_dir()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{label}.json"
    filepath = RESULTS_DIR / filename

    comparison = {
        "timestamp": datetime.now().isoformat(),
        "label": label,
        "strategies": [asdict(r) for r in results],
        "rankings": {
            "by_return": [r.strategy for r in sorted(results, key=lambda r: r.total_return_pct, reverse=True)],
        },
    }

    with open(filepath, "w") as f:
        json.dump(comparison, f, indent=2, default=str)

    return str(filepath)


def print_walk_forward_report(in_sample: BacktestResult, out_of_sample: BacktestResult, train_pct: int):
    """Print side-by-side in-sample vs out-of-sample metrics."""
    print(f"\n{'='*70}")
    print(f"WALK-FORWARD VALIDATION REPORT")
    print(f"Strategy: {in_sample.strategy}  |  Train: {train_pct}% / Test: {100 - train_pct}%")
    print(f"{'='*70}")

    print(f"\n{'Metric':<25} {'In-Sample':>18} {'Out-of-Sample':>18}")
    print("-" * 65)

    print(f"{'Date Range':<25} {(in_sample.start_date or '?') + ' to':>18}")
    print(f"{'':<25} {(in_sample.end_date or '?'):>18} {(out_of_sample.start_date or '?') + ' to':>18}")
    print(f"{'':<25} {'':<18} {(out_of_sample.end_date or '?'):>18}")
    print()

    # Format helpers
    def fmt_pct(v):
        return f"{v:+.2f}%" if v is not None else "N/A"

    def fmt_dollar(v):
        return f"${v:,.2f}" if v is not None else "N/A"

    def fmt_num(v):
        return f"{v}" if v is not None else "N/A"

    def fmt_ratio(v):
        return f"{v:.2f}" if v is not None else "N/A"

    rows = [
        ("Final Value", fmt_dollar(in_sample.final_value), fmt_dollar(out_of_sample.final_value)),
        ("Total Return", fmt_pct(in_sample.total_return_pct), fmt_pct(out_of_sample.total_return_pct)),
        ("Total Trades", fmt_num(in_sample.total_trades), fmt_num(out_of_sample.total_trades)),
        ("Win Rate", fmt_pct(in_sample.win_rate_pct), fmt_pct(out_of_sample.win_rate_pct)),
        ("Max Drawdown", fmt_pct(in_sample.max_drawdown_pct), fmt_pct(out_of_sample.max_drawdown_pct)),
        ("Sharpe Ratio", fmt_ratio(in_sample.sharpe_ratio), fmt_ratio(out_of_sample.sharpe_ratio)),
        ("Buy & Hold Return", fmt_pct(in_sample.buy_hold_return_pct), fmt_pct(out_of_sample.buy_hold_return_pct)),
        ("Alpha", fmt_pct(in_sample.alpha_pct), fmt_pct(out_of_sample.alpha_pct)),
    ]

    for label, is_val, oos_val in rows:
        print(f"{label:<25} {is_val:>18} {oos_val:>18}")

    print(f"\n{'-'*65}")

    # Degradation analysis
    if in_sample.total_return_pct and out_of_sample.total_return_pct:
        degradation = in_sample.total_return_pct - out_of_sample.total_return_pct
        ratio = out_of_sample.total_return_pct / in_sample.total_return_pct if in_sample.total_return_pct != 0 else 0
        print(f"\nReturn degradation: {degradation:+.2f}% (OOS is {ratio:.0%} of IS)")

        if ratio >= 0.5:
            print("Assessment: GOOD - Strategy retains majority of in-sample performance")
        elif ratio >= 0.2:
            print("Assessment: FAIR - Notable degradation, possible overfitting")
        elif ratio > 0:
            print("Assessment: POOR - Severe degradation, likely overfit")
        else:
            print("Assessment: FAIL - Strategy loses money out-of-sample, likely overfit")

    print(f"{'='*70}\n")


def compare_strategies(strategy_filter: Optional[str] = None) -> List[BacktestResult]:
    """
    Load and compare results, optionally filtering by strategy.
    """
    results = load_all_results()

    if strategy_filter:
        results = [r for r in results if strategy_filter.lower() in r.strategy.lower()]

    print_comparison_table(results)
    return results


def print_trade_journal(result: BacktestResult):
    """Print a formatted per-trade journal table."""
    if not result.trades:
        print("No per-trade data available for this run.")
        return

    trades = result.trades
    print(f"\nTRADE JOURNAL ({len(trades)} trades)")
    print("=" * 120)

    # Check if R-multiples are available
    has_r = any(t.get("r_multiple") is not None for t in trades)

    # Header
    if has_r:
        print(f"{'#':<4} {'Entry Date':<20} {'Exit Date':<20} {'Dir':<6} {'Entry':>10} {'Exit':>10} "
              f"{'PnL%':>8} {'R':>6} {'PnL$':>10} {'Bars':>6}  Context")
    else:
        print(f"{'#':<4} {'Entry Date':<20} {'Exit Date':<20} {'Dir':<6} {'Entry':>10} {'Exit':>10} "
              f"{'PnL%':>8} {'PnL$':>10} {'Bars':>6}  Context")
    print("-" * 130)

    for i, t in enumerate(trades, 1):
        entry_dt = t.get("entry_dt", "?")[:16] if t.get("entry_dt") else "?"
        exit_dt = t.get("exit_dt", "?")[:16] if t.get("exit_dt") else "?"
        direction = t.get("direction", "?").upper()
        entry_p = t.get("entry_price", 0)
        exit_p = t.get("exit_price", 0)
        pnl_pct = t.get("pnl_pct", 0)
        pnl_net = t.get("pnl_net", t.get("pnl", 0))
        bars = t.get("bars_held", "?")
        r_mult = t.get("r_multiple")

        # Format context (skip stop_distance/risk_pct/position_size from display — they're internal)
        ctx = t.get("market_context", {})
        ctx_parts = []
        skip_keys = {"stop_distance", "risk_pct", "position_size"}
        for k, v in ctx.items():
            if k in skip_keys:
                continue
            if isinstance(v, float):
                ctx_parts.append(f"{k}={v:.2f}")
            else:
                ctx_parts.append(f"{k}={v}")
        ctx_str = ", ".join(ctx_parts) if ctx_parts else ""

        if has_r:
            r_str = f"{r_mult:>+5.1f}R" if r_mult is not None else "   N/A"
            print(f"{i:<4} {entry_dt:<20} {exit_dt:<20} {direction:<6} {entry_p:>10.2f} {exit_p:>10.2f} "
                  f"{pnl_pct:>+7.1f}% {r_str} {pnl_net:>+10.2f} {str(bars):>6}  {ctx_str}")
        else:
            print(f"{i:<4} {entry_dt:<20} {exit_dt:<20} {direction:<6} {entry_p:>10.2f} {exit_p:>10.2f} "
                  f"{pnl_pct:>+7.1f}% {pnl_net:>+10.2f} {str(bars):>6}  {ctx_str}")

    print("-" * 130)

    # Summary stats from the trade journal
    wins = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) <= 0]
    avg_win = sum(t.get("pnl_pct", 0) for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.get("pnl_pct", 0) for t in losses) / len(losses) if losses else 0
    avg_bars = sum(t.get("bars_held", 0) for t in trades if t.get("bars_held")) / len(trades) if trades else 0

    print(f"\nJournal Summary:")
    print(f"  Wins: {len(wins)}  |  Losses: {len(losses)}  |  Win Rate: {len(wins)/len(trades)*100:.1f}%")
    print(f"  Avg Win: {avg_win:+.2f}%  |  Avg Loss: {avg_loss:+.2f}%  |  Avg Hold: {avg_bars:.0f} bars")

    if wins and losses:
        expectancy = (len(wins)/len(trades) * avg_win) + (len(losses)/len(trades) * avg_loss)
        print(f"  Expectancy: {expectancy:+.2f}% per trade")

    # R-based summary if available
    r_values = [t.get("r_multiple") for t in trades if t.get("r_multiple") is not None]
    if r_values:
        avg_r = sum(r_values) / len(r_values)
        best_r = max(r_values)
        worst_r = min(r_values)
        r_wins = [r for r in r_values if r > 0]
        r_losses = [r for r in r_values if r <= 0]
        avg_r_win = sum(r_wins) / len(r_wins) if r_wins else 0
        avg_r_loss = sum(r_losses) / len(r_losses) if r_losses else 0
        print(f"\n  R-Based Summary ({len(r_values)} trades with R data):")
        print(f"  R-Expectancy: {avg_r:+.2f}R per trade")
        print(f"  Avg Win: {avg_r_win:+.1f}R  |  Avg Loss: {avg_r_loss:+.1f}R")
        print(f"  Best: {best_r:+.1f}R  |  Worst: {worst_r:+.1f}R")

    # Context analysis if available
    ctx_trades = [t for t in trades if t.get("market_context")]
    if ctx_trades:
        print(f"\nMarket Context Analysis ({len(ctx_trades)} trades with context):")
        # Find common context keys
        all_keys = set()
        for t in ctx_trades:
            all_keys.update(t["market_context"].keys())

        for key in sorted(all_keys):
            vals_win = [t["market_context"][key] for t in ctx_trades
                       if key in t["market_context"] and t.get("pnl", 0) > 0
                       and isinstance(t["market_context"][key], (int, float))]
            vals_loss = [t["market_context"][key] for t in ctx_trades
                        if key in t["market_context"] and t.get("pnl", 0) <= 0
                        and isinstance(t["market_context"][key], (int, float))]

            if vals_win and vals_loss:
                avg_w = sum(vals_win) / len(vals_win)
                avg_l = sum(vals_loss) / len(vals_loss)
                print(f"  {key}: avg(wins)={avg_w:.2f}, avg(losses)={avg_l:.2f}")

    # Regime breakdown if regime data is present
    regime_trades = [t for t in trades if t.get("market_context", {}).get("regime")]
    if regime_trades:
        print(f"\nRegime Breakdown ({len(regime_trades)} trades with regime data):")
        # Group by regime
        regime_groups = {}
        for t in regime_trades:
            regime = t["market_context"]["regime"]
            if regime not in regime_groups:
                regime_groups[regime] = []
            regime_groups[regime].append(t)

        # Sort by number of trades descending
        for regime, group in sorted(regime_groups.items(), key=lambda x: -len(x[1])):
            n = len(group)
            w = sum(1 for t in group if t.get("pnl", 0) > 0)
            l = n - w
            wr = (w / n * 100) if n > 0 else 0
            avg_pnl = sum(t.get("pnl_pct", 0) for t in group) / n if n > 0 else 0
            print(f"  {regime:<25} {n:>3} trades, {w}W/{l}L ({wr:.0f}%), avg {avg_pnl:+.1f}%")

    print()


def print_regime_comparison(results: List[BacktestResult]):
    """Print a cross-strategy regime comparison matrix.

    Shows each strategy's performance broken down by regime, and recommends
    the best strategy for each regime.
    """
    # Collect regime stats per strategy: {strategy: {regime: {trades, wins, total_pnl_pct}}}
    strategy_regime_stats = {}
    all_regimes = set()

    for result in results:
        if not result.trades:
            continue
        regime_trades = [t for t in result.trades if t.get("market_context", {}).get("regime")]
        if not regime_trades:
            continue

        stats = {}
        for t in regime_trades:
            regime = t["market_context"]["regime"]
            all_regimes.add(regime)
            if regime not in stats:
                stats[regime] = {"trades": 0, "wins": 0, "total_pnl_pct": 0.0}
            stats[regime]["trades"] += 1
            if t.get("pnl", 0) > 0:
                stats[regime]["wins"] += 1
            stats[regime]["total_pnl_pct"] += t.get("pnl_pct", 0)

        strategy_regime_stats[result.strategy] = stats

    if not strategy_regime_stats:
        print("\nNo regime data available for comparison.")
        return

    strategies = sorted(strategy_regime_stats.keys())
    regimes = sorted(all_regimes)

    # Calculate total trades per regime across all strategies (for sorting)
    regime_total_trades = {}
    for regime in regimes:
        regime_total_trades[regime] = sum(
            strategy_regime_stats[s].get(regime, {}).get("trades", 0) for s in strategies
        )
    regimes.sort(key=lambda r: -regime_total_trades[r])

    # Print header
    print(f"\nREGIME COMPARISON ({len(strategies)} strategies)")
    print("=" * 100)

    # Column width for each strategy
    col_w = max(18, max(len(s) + 4 for s in strategies))
    header = f"{'Regime':<26}"
    for s in strategies:
        header += f"{s:>{col_w}}"
    print(header)
    print("-" * 100)

    # Print each regime row
    for regime in regimes:
        row = f"  {regime:<24}"
        for s in strategies:
            st = strategy_regime_stats[s].get(regime)
            if st and st["trades"] > 0:
                n = st["trades"]
                wr = (st["wins"] / n * 100)
                avg_pnl = st["total_pnl_pct"] / n
                cell = f"{n}T {wr:.0f}% {avg_pnl:+.1f}%"
            else:
                cell = "--"
            row += f"{cell:>{col_w}}"
        print(row)

    print("-" * 100)

    # Best strategy per regime
    print("\nBEST STRATEGY PER REGIME:")
    for regime in regimes:
        best_strategy = None
        best_avg_pnl = -float("inf")
        best_wr = 0
        for s in strategies:
            st = strategy_regime_stats[s].get(regime)
            if st and st["trades"] >= 2:  # Minimum 2 trades to qualify
                avg_pnl = st["total_pnl_pct"] / st["trades"]
                if avg_pnl > best_avg_pnl:
                    best_avg_pnl = avg_pnl
                    best_wr = (st["wins"] / st["trades"] * 100)
                    best_strategy = s

        if best_strategy:
            marker = "*" if best_avg_pnl > 0 else " "
            print(f" {marker} {regime:<26} -> {best_strategy:<12} ({best_wr:.0f}% WR, {best_avg_pnl:+.1f}% avg)")
        else:
            print(f"   {regime:<26} -> insufficient data")

    print()
    print("  * = positive expectancy regime")
    print()


class TradeTracker:
    """
    Helper class to track trades during a backtest.
    Use this in strategies to count wins/losses.
    """

    def __init__(self):
        self.trades: List[Dict[str, Any]] = []
        self.peak_value: float = 0.0
        self.max_drawdown_pct: float = 0.0

    def record_trade(self, entry_price: float, exit_price: float, size: float, entry_time=None, exit_time=None):
        """Record a completed trade."""
        pnl = (exit_price - entry_price) * size
        pnl_pct = (exit_price - entry_price) / entry_price * 100

        self.trades.append({
            "entry_price": entry_price,
            "exit_price": exit_price,
            "size": size,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "entry_time": str(entry_time) if entry_time else None,
            "exit_time": str(exit_time) if exit_time else None,
        })

    def update_drawdown(self, current_value: float):
        """Update max drawdown tracking."""
        if current_value > self.peak_value:
            self.peak_value = current_value
        elif self.peak_value > 0:
            drawdown = (self.peak_value - current_value) / self.peak_value * 100
            self.max_drawdown_pct = max(self.max_drawdown_pct, drawdown)

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trades if t["pnl"] > 0)

    @property
    def losing_trades(self) -> int:
        return sum(1 for t in self.trades if t["pnl"] <= 0)

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics."""
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "max_drawdown_pct": self.max_drawdown_pct,
        }


# CLI for viewing results
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="View backtest results")
    parser.add_argument("--strategy", "-s", help="Filter by strategy name")
    parser.add_argument("--limit", "-n", type=int, default=10, help="Number of results to show")
    parser.add_argument("--detail", "-d", help="Show detailed result for specific run ID")
    parser.add_argument("--trades", action="store_true", help="Show per-trade journal (use with --detail)")

    args = parser.parse_args()

    if args.detail:
        # Find and show detailed result
        results = load_all_results()
        found = [r for r in results if r.run_id == args.detail]
        if found:
            print_result(found[0])
            if args.trades:
                print_trade_journal(found[0])
        else:
            print(f"No result found with run ID: {args.detail}")
    else:
        # Show comparison table
        results = load_all_results()
        if args.strategy:
            results = [r for r in results if args.strategy.lower() in r.strategy.lower()]
        print_comparison_table(results, limit=args.limit)
