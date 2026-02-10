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


def create_v8_fast_objective(metric: str = "final_value", start_date: str = None, end_date: str = None):
    """
    Create objective function for v8_fast optimization.

    Args:
        metric: What to optimize - "final_value", "sharpe", or "return"
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
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
                start_date=start_date,
                end_date=end_date,
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


def create_v8_objective(metric: str = "final_value", start_date: str = None, end_date: str = None):
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
                start_date=start_date,
                end_date=end_date,
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



def create_v9_objective(metric: str = "final_value", start_date: str = None, end_date: str = None):
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
                start_date=start_date,
                end_date=end_date,
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


def create_v11_objective(metric: str = "final_value"):
    """
    Create objective function for v11 (combined range + trend on 4H) optimization.
    Focus on reducing trade frequency and improving per-trade expectancy.
    """
    def objective(trial: optuna.Trial) -> float:
        params = {
            # Trend detection (4H candles)
            "trend_lookback": trial.suggest_int("trend_lookback", 4, 8),
            "min_trend_candles": trial.suggest_int("min_trend_candles", 3, 5),

            # Range Strategy parameters
            "range_approach_pct": trial.suggest_float("range_approach_pct", 0.2, 1.0, step=0.1),
            "range_min_range_pct": trial.suggest_float("range_min_range_pct", 4.0, 8.0, step=0.5),
            "range_buffer_pct": trial.suggest_float("range_buffer_pct", 2.0, 5.0, step=0.5),
            "range_rr_ratio": trial.suggest_float("range_rr_ratio", 2.5, 4.5, step=0.25),
            "range_cooldown_bars": trial.suggest_int("range_cooldown_bars", 48, 192, step=24),

            # Trend Strategy parameters
            "trend_approach_pct": trial.suggest_float("trend_approach_pct", 0.2, 0.8, step=0.1),
            "trend_min_range_pct": trial.suggest_float("trend_min_range_pct", 3.0, 7.0, step=0.5),
            "trend_buffer_pct": trial.suggest_float("trend_buffer_pct", 2.0, 5.0, step=0.5),
            "trend_rr_ratio": trial.suggest_float("trend_rr_ratio", 3.0, 5.0, step=0.25),
            "trend_cooldown_bars": trial.suggest_int("trend_cooldown_bars", 96, 384, step=48),

            # Risk-based position sizing
            "risk_per_trade_pct": trial.suggest_float("risk_per_trade_pct", 1.0, 3.0, step=0.5),
            "max_position_pct": trial.suggest_float("max_position_pct", 20.0, 50.0, step=5.0),
        }

        try:
            result = run_backtest(
                strategy_name="v11",
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



def create_v13_objective(metric: str = "final_value", start_date: str = None, end_date: str = None):
    """
    Create objective function for v13 (trend momentum rider).
    DEFAULT: Optimizes for FINAL VALUE (bigger moves, not win rate).
    """
    def objective(trial: optuna.Trial) -> float:
        params = {
            # Trend detection (4H)
            "ema_fast": trial.suggest_int("ema_fast", 5, 12),
            "ema_slow": trial.suggest_int("ema_slow", 15, 30),
            "trend_strength_min": trial.suggest_float("trend_strength_min", 0.3, 1.5, step=0.1),

            # Volume entry confirmation
            "vol_expansion_mult": trial.suggest_float("vol_expansion_mult", 1.1, 2.0, step=0.1),
            "require_volume_confirm": trial.suggest_categorical("require_volume_confirm", [True, False]),

            # OBV filter
            "use_obv_filter": trial.suggest_categorical("use_obv_filter", [True, False]),
            "obv_ema_period": trial.suggest_int("obv_ema_period", 5, 20),

            # RSI (lenient)
            "rsi_period": trial.suggest_int("rsi_period", 10, 21),
            "rsi_oversold": trial.suggest_int("rsi_oversold", 35, 50),
            "rsi_overbought": trial.suggest_int("rsi_overbought", 50, 65),

            # ATR-based stops
            "atr_period": trial.suggest_int("atr_period", 10, 20),
            "atr_trailing_mult": trial.suggest_float("atr_trailing_mult", 1.5, 4.0, step=0.25),
            "atr_initial_mult": trial.suggest_float("atr_initial_mult", 1.0, 2.5, step=0.25),

            # Partial profits
            "use_partial_profits": trial.suggest_categorical("use_partial_profits", [True, False]),
            "partial_target_atr_mult": trial.suggest_float("partial_target_atr_mult", 2.0, 5.0, step=0.5),
            "partial_sell_ratio": trial.suggest_float("partial_sell_ratio", 0.25, 0.50, step=0.05),

            # Volume exit
            "use_volume_exit": trial.suggest_categorical("use_volume_exit", [True, False]),
            "vol_climax_mult": trial.suggest_float("vol_climax_mult", 2.0, 4.0, step=0.5),

            # Cooldown
            "cooldown_bars": trial.suggest_int("cooldown_bars", 4, 24, step=4),

            # Position sizing
            "position_pct": trial.suggest_float("position_pct", 80.0, 95.0, step=5.0),
        }

        try:
            result = run_backtest(
                strategy_name="v13",
                params_override=params,
                save=False,
                verbose=False,
                start_date=start_date,
                end_date=end_date,
            )

            trial.set_user_attr("total_return_pct", result.total_return_pct)
            trial.set_user_attr("total_trades", result.total_trades)
            trial.set_user_attr("win_rate_pct", result.win_rate_pct or 0)
            trial.set_user_attr("max_drawdown_pct", result.max_drawdown_pct or 0)
            trial.set_user_attr("sharpe_ratio", result.sharpe_ratio or 0)

            # For V13, default to optimizing FINAL VALUE (bigger moves)
            if metric == "final_value":
                return result.final_value
            elif metric == "sharpe":
                return result.sharpe_ratio or -999
            elif metric == "return":
                return result.total_return_pct
            elif metric == "win_rate":
                if result.total_trades < 20:
                    return 0.0
                return result.win_rate_pct or 0.0
            else:
                return result.final_value

        except Exception as e:
            print(f"Trial failed: {e}")
            return 0.0

    return objective


def create_v14_objective(metric: str = "final_value", start_date: str = None, end_date: str = None):
    """
    Create objective function for v14 (4H EMA trend + 15M crossover + volume).
    Simple strategy with ATR-based TP/SL.
    """
    def objective(trial: optuna.Trial) -> float:
        params = {
            # 4H Trend EMAs
            "ema_fast": trial.suggest_int("ema_fast", 5, 15),
            "ema_slow": trial.suggest_int("ema_slow", 15, 35),

            # 15M Entry EMAs
            "entry_ema_fast": trial.suggest_int("entry_ema_fast", 5, 15),
            "entry_ema_slow": trial.suggest_int("entry_ema_slow", 15, 35),

            # Volume
            "vol_sma_period": trial.suggest_int("vol_sma_period", 10, 30, step=5),
            "require_volume": trial.suggest_categorical("require_volume", [True, False]),

            # ATR stops
            "atr_period": trial.suggest_int("atr_period", 10, 20),
            "stop_multiplier": trial.suggest_float("stop_multiplier", 1.0, 3.0, step=0.25),
            "tp_multiplier": trial.suggest_float("tp_multiplier", 2.0, 5.0, step=0.5),

            # Trend reversal exit
            "exit_on_trend_reversal": trial.suggest_categorical("exit_on_trend_reversal", [True, False]),

            # Cooldown
            "cooldown_bars": trial.suggest_int("cooldown_bars", 2, 12, step=2),

            # Position sizing
            "position_pct": trial.suggest_float("position_pct", 80.0, 98.0, step=2.0),
        }

        try:
            result = run_backtest(
                strategy_name="v14",
                params_override=params,
                save=False,
                verbose=False,
                start_date=start_date,
                end_date=end_date,
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
            elif metric == "win_rate":
                if result.total_trades < 20:
                    return 0.0
                return result.win_rate_pct or 0.0
            else:
                return result.final_value

        except Exception as e:
            print(f"Trial failed: {e}")
            return 0.0

    return objective


def create_v15_objective(metric: str = "expectancy", start_date: str = None, end_date: str = None):
    """
    Create objective function for v15 (Zone Trader).
    DEFAULT: Optimizes for EXPECTANCY - combines positive return with sufficient trade frequency.
    Penalizes strategies with < 0.3 trades/day.
    """
    def objective(trial: optuna.Trial) -> float:
        params = {
            # 4H Trend EMAs
            "ema_fast_4h_period": trial.suggest_int("ema_fast_4h_period", 5, 15),
            "ema_slow_4h_period": trial.suggest_int("ema_slow_4h_period", 15, 30),
            "trend_deadzone_pct": trial.suggest_float("trend_deadzone_pct", 0.0, 0.5, step=0.05),

            # 1H Entry EMAs
            "ema_fast_1h_period": trial.suggest_int("ema_fast_1h_period", 5, 15),
            "ema_slow_1h_period": trial.suggest_int("ema_slow_1h_period", 15, 30),

            # Entry type toggles
            "enable_crossover_entry": trial.suggest_categorical("enable_crossover_entry", [True]),
            "enable_pullback_entry": trial.suggest_categorical("enable_pullback_entry", [True, False]),

            # Volume
            "vol_sma_period": trial.suggest_int("vol_sma_period", 10, 30, step=5),
            "require_volume": trial.suggest_categorical("require_volume", [True, False]),

            # ATR stops
            "atr_period": trial.suggest_int("atr_period", 10, 20),
            "stop_multiplier": trial.suggest_float("stop_multiplier", 1.0, 2.5, step=0.25),
            "tp_multiplier": trial.suggest_float("tp_multiplier", 2.0, 5.0, step=0.5),

            # Exit controls
            "exit_on_trend_reversal": trial.suggest_categorical("exit_on_trend_reversal", [True, False]),
            "max_hold_bars": trial.suggest_int("max_hold_bars", 24, 72, step=12),

            # Risk-based sizing
            "risk_per_trade_pct": trial.suggest_float("risk_per_trade_pct", 0.5, 3.0, step=0.5),

            # Cooldown (1H bars)
            "cooldown_bars": trial.suggest_int("cooldown_bars", 3, 12),
        }

        try:
            result = run_backtest(
                strategy_name="v15",
                params_override=params,
                save=False,
                verbose=False,
                start_date=start_date,
                end_date=end_date,
            )

            trial.set_user_attr("final_value", result.final_value)
            trial.set_user_attr("total_return_pct", result.total_return_pct)
            trial.set_user_attr("total_trades", result.total_trades)
            trial.set_user_attr("win_rate_pct", result.win_rate_pct or 0)
            trial.set_user_attr("max_drawdown_pct", result.max_drawdown_pct or 0)
            trial.set_user_attr("sharpe_ratio", result.sharpe_ratio or 0)

            # Calculate trades per day
            if result.start_date and result.end_date:
                from datetime import datetime as dt_cls
                start = dt_cls.strptime(result.start_date, "%Y-%m-%d")
                end = dt_cls.strptime(result.end_date, "%Y-%m-%d")
                days = max((end - start).days, 1)
                trades_per_day = result.total_trades / days
            else:
                trades_per_day = 0
            trial.set_user_attr("trades_per_day", trades_per_day)

            if metric == "expectancy":
                # Expectancy metric: positive return * frequency factor
                # Penalize if < 0.3 trades/day, bonus if 0.5-1.5 trades/day
                if result.total_trades < 20:
                    return 0.0
                freq_factor = min(trades_per_day / 0.3, 1.0)  # 0-1 scale, 1.0 at 0.3+ trades/day
                # Use return as base, scaled by frequency
                return result.total_return_pct * freq_factor
            elif metric == "final_value":
                return result.final_value
            elif metric == "sharpe":
                return result.sharpe_ratio or -999
            elif metric == "return":
                return result.total_return_pct
            elif metric == "win_rate":
                if result.total_trades < 20:
                    return 0.0
                return result.win_rate_pct or 0.0
            else:
                return result.total_return_pct * min(trades_per_day / 0.3, 1.0)

        except Exception as e:
            print(f"Trial failed: {e}")
            return 0.0

    return objective


def create_v16_objective(metric: str = "expectancy", start_date: str = None, end_date: str = None):
    """
    Create objective function for v16 (Trend Exhaustion Catcher).
    DEFAULT: Optimizes for EXPECTANCY - combines positive return with sufficient trade frequency.
    """
    def objective(trial: optuna.Trial) -> float:
        params = {
            # 4H Trend EMAs
            "ema_fast_4h_period": trial.suggest_int("ema_fast_4h_period", 5, 15),
            "ema_slow_4h_period": trial.suggest_int("ema_slow_4h_period", 15, 30),
            "trend_deadzone_pct": trial.suggest_float("trend_deadzone_pct", 0.0, 0.5, step=0.05),

            # 1H Entry EMAs
            "ema_fast_1h_period": trial.suggest_int("ema_fast_1h_period", 5, 15),
            "ema_slow_1h_period": trial.suggest_int("ema_slow_1h_period", 15, 30),

            # Convergence entry (Type A)
            "min_convergence_bars": trial.suggest_int("min_convergence_bars", 2, 6),
            "max_gap_pct": trial.suggest_float("max_gap_pct", 0.3, 1.5, step=0.1),

            # RSI divergence entry (Type B)
            "rsi_period_4h": trial.suggest_int("rsi_period_4h", 10, 21),
            "divergence_lookback": trial.suggest_int("divergence_lookback", 3, 8),
            "rejection_wick_ratio": trial.suggest_float("rejection_wick_ratio", 0.5, 0.8, step=0.05),

            # Volume
            "vol_sma_period": trial.suggest_int("vol_sma_period", 10, 30, step=5),
            "vol_spike_mult": trial.suggest_float("vol_spike_mult", 0.8, 1.5, step=0.1),

            # ATR stops
            "atr_period": trial.suggest_int("atr_period", 10, 20),
            "stop_multiplier": trial.suggest_float("stop_multiplier", 1.5, 3.0, step=0.25),
            "tp_multiplier": trial.suggest_float("tp_multiplier", 1.5, 4.0, step=0.25),

            # Exit controls
            "trend_strengthen_exit_pct": trial.suggest_float("trend_strengthen_exit_pct", 5.0, 20.0, step=2.5),
            "max_hold_bars": trial.suggest_int("max_hold_bars", 24, 60, step=6),

            # Risk-based sizing
            "risk_per_trade_pct": trial.suggest_float("risk_per_trade_pct", 0.5, 3.0, step=0.5),

            # Cooldown (1H bars)
            "cooldown_bars": trial.suggest_int("cooldown_bars", 3, 12),
        }

        try:
            result = run_backtest(
                strategy_name="v16",
                params_override=params,
                save=False,
                verbose=False,
                start_date=start_date,
                end_date=end_date,
            )

            trial.set_user_attr("final_value", result.final_value)
            trial.set_user_attr("total_return_pct", result.total_return_pct)
            trial.set_user_attr("total_trades", result.total_trades)
            trial.set_user_attr("win_rate_pct", result.win_rate_pct or 0)
            trial.set_user_attr("max_drawdown_pct", result.max_drawdown_pct or 0)
            trial.set_user_attr("sharpe_ratio", result.sharpe_ratio or 0)

            # Calculate trades per day
            if result.start_date and result.end_date:
                from datetime import datetime as dt_cls
                start = dt_cls.strptime(result.start_date, "%Y-%m-%d")
                end = dt_cls.strptime(result.end_date, "%Y-%m-%d")
                days = max((end - start).days, 1)
                trades_per_day = result.total_trades / days
            else:
                trades_per_day = 0
            trial.set_user_attr("trades_per_day", trades_per_day)

            if metric == "expectancy":
                if result.total_trades < 15:
                    return 0.0
                freq_factor = min(trades_per_day / 0.3, 1.0)
                return result.total_return_pct * freq_factor
            elif metric == "final_value":
                return result.final_value
            elif metric == "sharpe":
                return result.sharpe_ratio or -999
            elif metric == "return":
                return result.total_return_pct
            elif metric == "win_rate":
                if result.total_trades < 15:
                    return 0.0
                return result.win_rate_pct or 0.0
            else:
                return result.total_return_pct * min(trades_per_day / 0.3, 1.0)

        except Exception as e:
            print(f"Trial failed: {e}")
            return 0.0

    return objective


def create_v17_objective(metric: str = "expectancy", start_date: str = None, end_date: str = None):
    """
    Create objective function for v17 (ATR Swing Scalper).
    DEFAULT: Optimizes for EXPECTANCY - positive return scaled by trade frequency.
    10 optimizable params, lean search space.
    """
    def objective(trial: optuna.Trial) -> float:
        params = {
            # 4H Trend EMAs
            "ema_fast_4h": trial.suggest_int("ema_fast_4h", 5, 15),
            "ema_slow_4h": trial.suggest_int("ema_slow_4h", 15, 30),
            "trend_threshold": trial.suggest_float("trend_threshold", 0.2, 1.0, step=0.1),

            # 1H Swing detection
            "swing_lookback": trial.suggest_int("swing_lookback", 2, 5),

            # Stop/TP multipliers
            "stop_mult": trial.suggest_float("stop_mult", 1.0, 2.5, step=0.25),
            "tp1_mult": trial.suggest_float("tp1_mult", 1.0, 2.5, step=0.25),
            "tp2_mult": trial.suggest_float("tp2_mult", 2.0, 5.0, step=0.5),

            # Risk management
            "risk_per_trade_pct": trial.suggest_float("risk_per_trade_pct", 0.25, 1.5, step=0.25),

            # Entry tuning
            "wick_ratio": trial.suggest_float("wick_ratio", 0.3, 0.7, step=0.05),
            "pullback_zone_mult": trial.suggest_float("pullback_zone_mult", 0.5, 2.5, step=0.25),
        }

        try:
            result = run_backtest(
                strategy_name="v17",
                params_override=params,
                save=False,
                verbose=False,
                start_date=start_date,
                end_date=end_date,
            )

            trial.set_user_attr("final_value", result.final_value)
            trial.set_user_attr("total_return_pct", result.total_return_pct)
            trial.set_user_attr("total_trades", result.total_trades)
            trial.set_user_attr("win_rate_pct", result.win_rate_pct or 0)
            trial.set_user_attr("max_drawdown_pct", result.max_drawdown_pct or 0)
            trial.set_user_attr("sharpe_ratio", result.sharpe_ratio or 0)

            # Calculate trades per day
            if result.start_date and result.end_date:
                from datetime import datetime as dt_cls
                start = dt_cls.strptime(result.start_date, "%Y-%m-%d")
                end = dt_cls.strptime(result.end_date, "%Y-%m-%d")
                days = max((end - start).days, 1)
                trades_per_day = result.total_trades / days
            else:
                trades_per_day = 0
            trial.set_user_attr("trades_per_day", trades_per_day)

            if metric == "expectancy":
                if result.total_trades < 20:
                    return -999.0
                freq_factor = min(trades_per_day / 0.5, 1.0)  # Target 0.5+ trades/day
                return result.total_return_pct * freq_factor
            elif metric == "final_value":
                return result.final_value
            elif metric == "sharpe":
                return result.sharpe_ratio or -999
            elif metric == "return":
                return result.total_return_pct
            elif metric == "win_rate":
                if result.total_trades < 20:
                    return -999.0
                return result.win_rate_pct or 0.0
            else:
                return result.total_return_pct * min(trades_per_day / 0.5, 1.0)

        except Exception as e:
            print(f"Trial failed: {e}")
            return -999.0

    return objective


def create_v18_objective(metric: str = "final_value", start_date: str = None, end_date: str = None):
    """
    Create objective function for v18 (Donchian Channel Breakout).
    Only 2 optimizable params — 405 total combinations.
    """
    def objective(trial: optuna.Trial) -> float:
        params = {
            "channel_period": trial.suggest_int("channel_period", 12, 96, step=6),
            "atr_trail_mult": trial.suggest_float("atr_trail_mult", 1.5, 8.0, step=0.25),
        }

        try:
            result = run_backtest(
                strategy_name="v18",
                params_override=params,
                save=False,
                verbose=False,
                start_date=start_date,
                end_date=end_date,
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
    start_date: str = None,
    end_date: str = None,
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
        objective = create_v8_fast_objective(metric, start_date=start_date, end_date=end_date)
    elif strategy == "v8":
        objective = create_v8_objective(metric, start_date=start_date, end_date=end_date)
    elif strategy == "v9":
        objective = create_v9_objective(metric, start_date=start_date, end_date=end_date)
    elif strategy == "v11":
        objective = create_v11_objective(metric)
    elif strategy == "v13":
        objective = create_v13_objective(metric, start_date=start_date, end_date=end_date)
    elif strategy == "v14":
        objective = create_v14_objective(metric, start_date=start_date, end_date=end_date)
    elif strategy == "v15":
        objective = create_v15_objective(metric, start_date=start_date, end_date=end_date)
    elif strategy == "v16":
        objective = create_v16_objective(metric, start_date=start_date, end_date=end_date)
    elif strategy == "v17":
        objective = create_v17_objective(metric, start_date=start_date, end_date=end_date)
    elif strategy == "v18":
        objective = create_v18_objective(metric, start_date=start_date, end_date=end_date)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    print(f"\nStarting optimization for {strategy}")
    print(f"Metric: {metric}")
    print(f"Trials: {n_trials}")
    print(f"Study: {study_name}")
    print("-" * 60)

    # Run optimization with progress callback
    def callback(study, trial):
        trades = trial.user_attrs.get('total_trades', 0)
        ret = trial.user_attrs.get('total_return_pct', 0)
        tpd = trial.user_attrs.get('trades_per_day', 0)
        if tpd and tpd > 0:
            print(f"Trial {trial.number}: Score={trial.value:,.2f} "
                  f"(Return: {ret:+.1f}%, "
                  f"Trades: {trades}, "
                  f"T/Day: {tpd:.2f}, "
                  f"Sharpe: {trial.user_attrs.get('sharpe_ratio', 0):.2f})")
        elif trial.value is not None:
            print(f"Trial {trial.number}: Score={trial.value:,.2f} "
                  f"(Return: {ret:+.1f}%, "
                  f"Trades: {trades}, "
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
    # Show actual final value from user_attrs if available, otherwise fall back to trial.value
    actual_final = best.user_attrs.get('final_value', None)
    if actual_final is not None:
        print(f"Final Value: ${actual_final:,.2f}")
    else:
        print(f"Final Value: ${best.value:,.2f}")
    print(f"Optimizer Score: {best.value:,.2f}")
    print(f"Total Return: {best.user_attrs.get('total_return_pct', 0):+.2f}%")
    print(f"Total Trades: {best.user_attrs.get('total_trades', 0)}")
    trades_per_day = best.user_attrs.get('trades_per_day', 0)
    if trades_per_day:
        print(f"Trades/Day: {trades_per_day:.2f}")
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
                "optimizer_score": best.value,
                "final_value": best.user_attrs.get("final_value", best.value),
                "total_return_pct": best.user_attrs.get("total_return_pct"),
                "total_trades": best.user_attrs.get("total_trades"),
                "trades_per_day": best.user_attrs.get("trades_per_day"),
                "win_rate_pct": best.user_attrs.get("win_rate_pct"),
                "max_drawdown_pct": best.user_attrs.get("max_drawdown_pct"),
                "sharpe_ratio": best.user_attrs.get("sharpe_ratio"),
            },
            "trial_number": best.number,
            "timestamp": datetime.now().isoformat(),
        }, f, indent=2)
    print(f"\nBest params saved to: {params_file}")

    # Check if a Pine template exists for this strategy
    template_path = Path(f"tradingview_{strategy}.pine.template")
    if template_path.exists():
        print(f"\nTip: Run `python generate_pine.py {strategy}` to update the TradingView Pine script.")

    # Print top 5 trials
    print("\nTop 5 Trials:")
    print("-" * 60)
    sorted_trials = sorted(study.trials, key=lambda t: t.value or 0, reverse=True)[:5]
    for i, trial in enumerate(sorted_trials, 1):
        t_final = trial.user_attrs.get('final_value', None)
        final_str = f"${t_final:,.2f}" if t_final else f"Score={trial.value:,.2f}"
        t_tpd = trial.user_attrs.get('trades_per_day', 0)
        tpd_str = f", T/Day: {t_tpd:.2f}" if t_tpd else ""
        print(f"{i}. Trial #{trial.number}: {final_str} "
              f"(Return: {trial.user_attrs.get('total_return_pct', 0):+.1f}%"
              f", Trades: {trial.user_attrs.get('total_trades', 0)}"
              f"{tpd_str})")

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


def analyze_importance(strategy: str):
    """
    Analyze parameter importance from existing Optuna studies.

    Uses fANOVA-based importance evaluation to rank which parameters
    have the most impact on the optimization objective.
    """
    storage = f"sqlite:///{RESULTS_DIR}/optuna_{strategy}.db"

    # Load all studies from the database
    try:
        study_summaries = optuna.study.get_all_study_summaries(storage=storage)
    except Exception as e:
        print(f"Error loading studies from {RESULTS_DIR}/optuna_{strategy}.db: {e}")
        print("Run optimization first to generate study data.")
        return

    if not study_summaries:
        print(f"No studies found in {RESULTS_DIR}/optuna_{strategy}.db")
        return

    # Use the study with the best non-zero value, falling back to most trials
    summaries_with_value = [s for s in study_summaries if s.best_trial and s.best_trial.value and s.best_trial.value > 0]
    if summaries_with_value:
        best_summary = max(summaries_with_value, key=lambda s: s.best_trial.value)
    else:
        best_summary = max(study_summaries, key=lambda s: s.n_trials)
    study = optuna.load_study(study_name=best_summary.study_name, storage=storage)

    completed_trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if len(completed_trials) < 3:
        print(f"Need at least 3 completed trials, found {len(completed_trials)}")
        return

    print(f"\nParameter Importance Analysis for {strategy}")
    print(f"Study: {best_summary.study_name}")
    print(f"Completed trials: {len(completed_trials)}")
    print(f"Best value: ${study.best_value:,.2f}")
    print("=" * 70)

    # Get parameter importances
    try:
        importances = optuna.importance.get_param_importances(study)
    except Exception as e:
        print(f"Error computing importances: {e}")
        print("This may happen if there are too few trials or insufficient parameter variation.")
        return

    # Get best params for reference
    best_params = study.best_trial.params

    # Print ranked table
    print(f"\n{'Rank':<6} {'Parameter':<25} {'Importance':>12} {'Best Value':>15}")
    print("-" * 62)

    for i, (param, importance) in enumerate(importances.items(), 1):
        best_val = best_params.get(param, "N/A")
        if isinstance(best_val, float):
            best_val_str = f"{best_val:.2f}"
        else:
            best_val_str = str(best_val)

        bar = "#" * int(importance * 40)
        print(f"  {i:<4} {param:<25} {importance:>11.1%} {best_val_str:>15}")
        print(f"       {bar}")

    print("-" * 62)

    # Summary
    top_params = list(importances.items())
    if len(top_params) >= 3:
        top3_importance = sum(v for _, v in top_params[:3])
        print(f"\nTop 3 params account for {top3_importance:.0%} of variance")
        print("Focus optimization and strategy design on these parameters.")

    # Show low-importance params that could be fixed
    low_importance = [(k, v) for k, v in importances.items() if v < 0.05]
    if low_importance:
        print(f"\nLow-importance params (<5%) that could be fixed to reduce search space:")
        for param, imp in low_importance:
            best_val = best_params.get(param, "N/A")
            print(f"  {param}: fix at {best_val} (importance: {imp:.1%})")


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
  python optimizer.py -s v8_fast --importance  # Analyze parameter importance
        """,
    )

    parser.add_argument(
        "--strategy", "-s",
        default="v8_fast",
        choices=["v8", "v8_fast", "v9", "v11", "v13", "v14", "v15", "v16", "v17", "v18"],
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
        choices=["final_value", "sharpe", "return", "win_rate", "expectancy"],
        help="Metric to optimize (default: final_value, v15: expectancy)"
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

    parser.add_argument(
        "--asset", "-a",
        default=None,
        help="Asset to optimize (e.g., SOL, BTC, ETH). Requires data file in data/ folder."
    )

    parser.add_argument(
        "--start-date",
        default=None,
        help="Start date for backtest data (YYYY-MM-DD), e.g., 2025-02-02 for last year"
    )

    parser.add_argument(
        "--end-date",
        default=None,
        help="End date for backtest data (YYYY-MM-DD)"
    )

    parser.add_argument(
        "--importance", "-i",
        action="store_true",
        help="Analyze parameter importance from existing study"
    )

    args = parser.parse_args()

    # Set active asset if specified
    if args.asset:
        import config
        config.ACTIVE_ASSET = args.asset.upper()
        print(f"Using asset: {config.ACTIVE_ASSET}/USD")

    # Handle importance analysis
    if args.importance:
        analyze_importance(args.strategy)
        return

    study = optimize(
        strategy=args.strategy,
        n_trials=args.trials,
        metric=args.metric,
        resume=args.resume,
        study_name=args.study,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    print_results(study, args.strategy)


if __name__ == "__main__":
    main()
