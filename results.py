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

    # Notes
    notes: str = ""


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
    return BacktestResult(**data)


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
        notes=notes,
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


def compare_strategies(strategy_filter: Optional[str] = None) -> List[BacktestResult]:
    """
    Load and compare results, optionally filtering by strategy.
    """
    results = load_all_results()

    if strategy_filter:
        results = [r for r in results if strategy_filter.lower() in r.strategy.lower()]

    print_comparison_table(results)
    return results


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

    args = parser.parse_args()

    if args.detail:
        # Find and show detailed result
        results = load_all_results()
        found = [r for r in results if r.run_id == args.detail]
        if found:
            print_result(found[0])
        else:
            print(f"No result found with run ID: {args.detail}")
    else:
        # Show comparison table
        results = load_all_results()
        if args.strategy:
            results = [r for r in results if args.strategy.lower() in r.strategy.lower()]
        print_comparison_table(results, limit=args.limit)
