#!/usr/bin/env python3
# optimizer.py
"""
Automated parameter optimization using Optuna.

Usage:
    python optimizer.py                      # Optimize v8_fast with 50 trials
    python optimizer.py --trials 100         # Run 100 trials
    python optimizer.py --strategy v8        # Optimize v8 instead
    python optimizer.py --resume             # Resume previous study
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import optuna
from optuna.samplers import TPESampler

from backtest import run_backtest
from config import V8_FAST_OPTIMIZED_PARAMS, V8_PARAMS

RESULTS_DIR = Path("results")


def create_v8_fast_objective(metric: str = "final_value"):
    """
    Create objective function for v8_fast optimization.

    Args:
        metric: What to optimize - "final_value", "sharpe", or "return"
    """
    def objective(trial: optuna.Trial) -> float:
        # Narrowed ranges based on Trial #13 best values:
        # drop_window=110, min_drop_pct=12, rise_window=80, min_up_bars_ratio=0.3
        # atr_trailing_mult=4.5, atr_fixed_mult=2.5, atr_period=20
        # partial_target_mult=5.5, use_partial_profits=False
        params = {
            # Drop detection (best: 110, 12.0)
            "drop_window": trial.suggest_int("drop_window", 90, 120, step=5),
            "min_drop_pct": trial.suggest_float("min_drop_pct", 10.0, 14.0, step=0.5),

            # Rise requirements (best: 80, 0.3, 11.0, -6.0, 3.5)
            "rise_window": trial.suggest_int("rise_window", 60, 100, step=5),
            "min_up_bars_ratio": trial.suggest_float("min_up_bars_ratio", 0.25, 0.40, step=0.05),
            "max_single_up_bar": trial.suggest_float("max_single_up_bar", 9.0, 13.0, step=0.5),
            "max_single_down_bar": trial.suggest_float("max_single_down_bar", -8.0, -4.0, step=0.5),
            "min_rise_pct": trial.suggest_float("min_rise_pct", 2.5, 4.5, step=0.25),

            # Volume confirmation (best: False)
            "volume_confirm": trial.suggest_categorical("volume_confirm", [False]),

            # Daily confirmation (best: 5)
            "daily_ema_period": trial.suggest_int("daily_ema_period", 3, 7),

            # ATR-based stops (best: 20, 4.5, 2.5)
            "atr_period": trial.suggest_int("atr_period", 16, 24, step=2),
            "atr_trailing_mult": trial.suggest_float("atr_trailing_mult", 4.0, 5.0, step=0.1),
            "atr_fixed_mult": trial.suggest_float("atr_fixed_mult", 2.0, 3.0, step=0.1),

            # Fallback stops (best: 8.0, 5.0)
            "trailing_pct": trial.suggest_float("trailing_pct", 6.0, 10.0, step=0.5),
            "fixed_stop_pct": trial.suggest_float("fixed_stop_pct", 4.0, 6.0, step=0.5),

            # Partial profit-taking (best: 5.5, 0.5, False)
            "partial_target_mult": trial.suggest_float("partial_target_mult", 4.5, 6.5, step=0.25),
            "partial_sell_ratio": trial.suggest_float("partial_sell_ratio", 0.4, 0.6, step=0.05),
            "use_partial_profits": trial.suggest_categorical("use_partial_profits", [True, False]),
        }

        try:
            result = run_backtest(
                strategy_name="v8_fast",
                params_override=params,
                save=False,
                verbose=False,
            )

            # Store additional metrics as user attributes
            trial.set_user_attr("total_return_pct", result.total_return_pct)
            trial.set_user_attr("total_trades", result.total_trades)
            trial.set_user_attr("win_rate_pct", result.win_rate_pct or 0)
            trial.set_user_attr("max_drawdown_pct", result.max_drawdown_pct or 0)
            trial.set_user_attr("sharpe_ratio", result.sharpe_ratio or 0)

            if metric == "final_value":
                return result.final_value
            elif metric == "sharpe":
                return result.sharpe_ratio or -999
            elif metric == "return":
                return result.total_return_pct
            else:
                return result.final_value

        except Exception as e:
            print(f"Trial failed: {e}")
            return 0.0

    return objective


def create_v8_objective(metric: str = "final_value"):
    """
    Create objective function for v8 (daily) optimization.
    """
    def objective(trial: optuna.Trial) -> float:
        params = {
            # Drop detection
            "drop_window": trial.suggest_int("drop_window", 10, 25, step=5),
            "min_drop_pct": trial.suggest_float("min_drop_pct", 10.0, 30.0, step=2.5),

            # Rise requirements
            "rise_window": trial.suggest_int("rise_window", 10, 30, step=5),
            "min_up_days_ratio": trial.suggest_float("min_up_days_ratio", 0.35, 0.55, step=0.05),
            "max_single_up_day": trial.suggest_float("max_single_up_day", 15.0, 35.0, step=5.0),
            "max_single_down_day": trial.suggest_float("max_single_down_day", -25.0, -8.0, step=2.0),
            "min_rise_pct": trial.suggest_float("min_rise_pct", 3.0, 10.0, step=1.0),

            # Volume confirmation
            "volume_confirm": trial.suggest_categorical("volume_confirm", [True, False]),

            # Weekly confirmation
            "weekly_ema_period": trial.suggest_int("weekly_ema_period", 3, 10),

            # Risk management
            "trailing_pct": trial.suggest_float("trailing_pct", 6.0, 25.0, step=1.0),
            "fixed_stop_pct": trial.suggest_float("fixed_stop_pct", 4.0, 15.0, step=1.0),
        }

        try:
            result = run_backtest(
                strategy_name="v8",
                params_override=params,
                save=False,
                verbose=False,
            )

            trial.set_user_attr("total_return_pct", result.total_return_pct)
            trial.set_user_attr("total_trades", result.total_trades)
            trial.set_user_attr("win_rate_pct", result.win_rate_pct or 0)
            trial.set_user_attr("max_drawdown_pct", result.max_drawdown_pct or 0)
            trial.set_user_attr("sharpe_ratio", result.sharpe_ratio or 0)

            if metric == "final_value":
                return result.final_value
            elif metric == "sharpe":
                return result.sharpe_ratio or -999
            elif metric == "return":
                return result.total_return_pct
            else:
                return result.final_value

        except Exception as e:
            print(f"Trial failed: {e}")
            return 0.0

    return objective


def create_v10_objective(metric: str = "final_value"):
    """
    Create objective function for v10 (trend trading with pullbacks) optimization.
    """
    def objective(trial: optuna.Trial) -> float:
        params = {
            # Trend detection
            "trend_lookback": trial.suggest_int("trend_lookback", 2, 6),

            # Entry threshold - how close to prev day high/low for pullback
            "approach_pct": trial.suggest_float("approach_pct", 0.25, 3.0, step=0.25),

            # Target buffer - % short of exact high/low
            "target_buffer_pct": trial.suggest_float("target_buffer_pct", 0.5, 5.0, step=0.5),

            # Risk/Reward ratio
            "rr_ratio": trial.suggest_float("rr_ratio", 1.5, 5.0, step=0.5),

            # Minimum range filter - skip small range days
            "min_range_pct": trial.suggest_float("min_range_pct", 0.5, 5.0, step=0.5),

            # Trade cooldown - prevent overtrading
            "cooldown_bars": trial.suggest_int("cooldown_bars", 1, 12),

            # Position sizing
            "position_pct": trial.suggest_float("position_pct", 0.5, 0.98, step=0.04),
        }

        try:
            result = run_backtest(
                strategy_name="v10",
                params_override=params,
                save=False,
                verbose=False,
            )

            trial.set_user_attr("total_return_pct", result.total_return_pct)
            trial.set_user_attr("total_trades", result.total_trades)
            trial.set_user_attr("win_rate_pct", result.win_rate_pct or 0)
            trial.set_user_attr("max_drawdown_pct", result.max_drawdown_pct or 0)
            trial.set_user_attr("sharpe_ratio", result.sharpe_ratio or 0)

            if metric == "final_value":
                return result.final_value
            elif metric == "sharpe":
                return result.sharpe_ratio or -999
            elif metric == "return":
                return result.total_return_pct
            else:
                return result.final_value

        except Exception as e:
            print(f"Trial failed: {e}")
            return 0.0

    return objective


def create_v9_objective(metric: str = "final_value"):
    """
    Create objective function for v9 (range trading) optimization.
    """
    def objective(trial: optuna.Trial) -> float:
        params = {
            # Range detection
            "trend_lookback": trial.suggest_int("trend_lookback", 2, 6),

            # Entry threshold - how close to prev day high/low
            "approach_pct": trial.suggest_float("approach_pct", 0.25, 3.0, step=0.25),

            # Target buffer - % short of exact high/low
            "target_buffer_pct": trial.suggest_float("target_buffer_pct", 0.5, 5.0, step=0.5),

            # Risk/Reward ratio
            "rr_ratio": trial.suggest_float("rr_ratio", 1.5, 5.0, step=0.5),

            # Minimum range filter - skip small range days
            "min_range_pct": trial.suggest_float("min_range_pct", 0.5, 5.0, step=0.5),

            # Trade cooldown - prevent overtrading
            "cooldown_bars": trial.suggest_int("cooldown_bars", 1, 12),

            # Position sizing
            "position_pct": trial.suggest_float("position_pct", 0.5, 0.98, step=0.04),
        }

        try:
            result = run_backtest(
                strategy_name="v9",
                params_override=params,
                save=False,
                verbose=False,
            )

            trial.set_user_attr("total_return_pct", result.total_return_pct)
            trial.set_user_attr("total_trades", result.total_trades)
            trial.set_user_attr("win_rate_pct", result.win_rate_pct or 0)
            trial.set_user_attr("max_drawdown_pct", result.max_drawdown_pct or 0)
            trial.set_user_attr("sharpe_ratio", result.sharpe_ratio or 0)

            if metric == "final_value":
                return result.final_value
            elif metric == "sharpe":
                return result.sharpe_ratio or -999
            elif metric == "return":
                return result.total_return_pct
            else:
                return result.final_value

        except Exception as e:
            print(f"Trial failed: {e}")
            return 0.0

    return objective


def optimize(
    strategy: str = "v8_fast",
    n_trials: int = 50,
    metric: str = "final_value",
    resume: bool = False,
    study_name: str = None,
):
    """
    Run optimization study.

    Args:
        strategy: Strategy to optimize ("v8" or "v8_fast")
        n_trials: Number of optimization trials
        metric: Metric to optimize ("final_value", "sharpe", "return")
        resume: Whether to resume a previous study
        study_name: Name for the study (auto-generated if None)

    Returns:
        optuna.Study object with results
    """
    RESULTS_DIR.mkdir(exist_ok=True)

    if study_name is None:
        study_name = f"optimize_{strategy}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    storage = f"sqlite:///{RESULTS_DIR}/optuna_{strategy}.db"

    # Create or load study
    if resume:
        try:
            study = optuna.load_study(
                study_name=study_name,
                storage=storage,
            )
            print(f"Resuming study '{study_name}' with {len(study.trials)} existing trials")
        except KeyError:
            print(f"No existing study found, creating new study")
            study = optuna.create_study(
                study_name=study_name,
                storage=storage,
                direction="maximize",
                sampler=TPESampler(seed=42),
            )
    else:
        study = optuna.create_study(
            study_name=study_name,
            storage=storage,
            direction="maximize",
            sampler=TPESampler(seed=42),
            load_if_exists=True,
        )

    # Select objective function
    if strategy == "v8_fast":
        objective = create_v8_fast_objective(metric)
    elif strategy == "v8":
        objective = create_v8_objective(metric)
    elif strategy == "v9":
        objective = create_v9_objective(metric)
    elif strategy == "v10":
        objective = create_v10_objective(metric)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    print(f"\nStarting optimization for {strategy}")
    print(f"Metric: {metric}")
    print(f"Trials: {n_trials}")
    print(f"Study: {study_name}")
    print("-" * 60)

    # Run optimization with progress callback
    def callback(study, trial):
        if trial.value and trial.value > 0:
            print(f"Trial {trial.number}: ${trial.value:,.2f} "
                  f"(Return: {trial.user_attrs.get('total_return_pct', 0):+.1f}%, "
                  f"Trades: {trial.user_attrs.get('total_trades', 0)}, "
                  f"Sharpe: {trial.user_attrs.get('sharpe_ratio', 0):.2f})")

    study.optimize(objective, n_trials=n_trials, callbacks=[callback])

    return study


def print_results(study: optuna.Study, strategy: str):
    """Print optimization results."""
    print("\n" + "=" * 60)
    print("OPTIMIZATION RESULTS")
    print("=" * 60)

    best = study.best_trial

    print(f"\nBest Trial: #{best.number}")
    print(f"Final Value: ${best.value:,.2f}")
    print(f"Total Return: {best.user_attrs.get('total_return_pct', 0):+.2f}%")
    print(f"Total Trades: {best.user_attrs.get('total_trades', 0)}")
    print(f"Win Rate: {best.user_attrs.get('win_rate_pct', 0):.1f}%")
    print(f"Max Drawdown: {best.user_attrs.get('max_drawdown_pct', 0):.2f}%")
    print(f"Sharpe Ratio: {best.user_attrs.get('sharpe_ratio', 0):.2f}")

    print("\nBest Parameters:")
    print("-" * 40)
    for key, value in sorted(best.params.items()):
        print(f"  {key}: {value}")

    # Save best params to file
    RESULTS_DIR.mkdir(exist_ok=True)
    params_file = RESULTS_DIR / f"best_params_{strategy}.json"
    with open(params_file, "w") as f:
        json.dump({
            "params": best.params,
            "metrics": {
                "final_value": best.value,
                "total_return_pct": best.user_attrs.get("total_return_pct"),
                "total_trades": best.user_attrs.get("total_trades"),
                "win_rate_pct": best.user_attrs.get("win_rate_pct"),
                "max_drawdown_pct": best.user_attrs.get("max_drawdown_pct"),
                "sharpe_ratio": best.user_attrs.get("sharpe_ratio"),
            },
            "trial_number": best.number,
            "timestamp": datetime.now().isoformat(),
        }, f, indent=2)
    print(f"\nBest params saved to: {params_file}")

    # Print top 5 trials
    print("\nTop 5 Trials:")
    print("-" * 60)
    sorted_trials = sorted(study.trials, key=lambda t: t.value or 0, reverse=True)[:5]
    for i, trial in enumerate(sorted_trials, 1):
        print(f"{i}. Trial #{trial.number}: ${trial.value:,.2f} "
              f"(Return: {trial.user_attrs.get('total_return_pct', 0):+.1f}%)")

    # Generate config snippet
    print("\n" + "=" * 60)
    print("Copy this to config.py to use optimized params:")
    print("=" * 60)
    print(f"\n# Optimized {strategy.upper()} params (Trial #{best.number})")
    print(f"{strategy.upper()}_OPTIMIZED_PARAMS = {{")
    for key, value in sorted(best.params.items()):
        if isinstance(value, str):
            print(f'    "{key}": "{value}",')
        elif isinstance(value, bool):
            print(f'    "{key}": {value},')
        elif isinstance(value, float):
            print(f'    "{key}": {value},')
        else:
            print(f'    "{key}": {value},')
    print("}")


def main():
    parser = argparse.ArgumentParser(
        description="Optimize strategy parameters using Optuna",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python optimizer.py                          # Optimize v8_fast, 50 trials
  python optimizer.py --trials 100             # Run 100 trials
  python optimizer.py --strategy v8            # Optimize v8 instead
  python optimizer.py --metric sharpe          # Optimize for Sharpe ratio
  python optimizer.py --resume --study my_study  # Resume previous study
        """,
    )

    parser.add_argument(
        "--strategy", "-s",
        default="v8_fast",
        choices=["v8", "v8_fast", "v9", "v10"],
        help="Strategy to optimize (default: v8_fast)"
    )

    parser.add_argument(
        "--trials", "-n",
        type=int,
        default=50,
        help="Number of optimization trials (default: 50)"
    )

    parser.add_argument(
        "--metric", "-m",
        default="final_value",
        choices=["final_value", "sharpe", "return"],
        help="Metric to optimize (default: final_value)"
    )

    parser.add_argument(
        "--resume", "-r",
        action="store_true",
        help="Resume a previous optimization study"
    )

    parser.add_argument(
        "--study",
        default=None,
        help="Study name (for resuming or naming)"
    )

    args = parser.parse_args()

    study = optimize(
        strategy=args.strategy,
        n_trials=args.trials,
        metric=args.metric,
        resume=args.resume,
        study_name=args.study,
    )

    print_results(study, args.strategy)


if __name__ == "__main__":
    main()
