# config.py
"""
Centralized configuration for the backtesting framework.
All tunable parameters, broker settings, and data sources are defined here.
"""

from dataclasses import dataclass
from typing import Dict, Any


# ============================================================================
# BROKER SETTINGS
# ============================================================================

@dataclass
class BrokerConfig:
    """Broker configuration for backtests."""
    cash: float = 10000.0
    commission: float = 0.001  # 0.1% per trade (typical crypto)
    position_size_pct: float = 0.01  # Use 98% of available cash per entry


BROKER = BrokerConfig()


# ============================================================================
# DATA SOURCES
# ============================================================================

# Active asset - change this to switch between assets
# Options: "SOL", "SUI", "VET", "BTC", etc.
ACTIVE_ASSET = "SOL"

@dataclass
class DataConfig:
    """Data source configuration."""
    # Default data source: "binance" or "yfinance"
    default_source: str = "binance"

    # Timestamp column names
    binance_timestamp_col: str = "timestamp"
    yfinance_timestamp_col: str = "Datetime"
    daily_timestamp_col: str = "Date"

    # Legacy paths (for backwards compatibility)
    yfinance_15m: str = "data/sol_usd_15m.csv"
    daily: str = "data/sol_usdt_1d.csv"

    @property
    def binance_15m(self) -> str:
        """Get data file path based on active asset."""
        return f"data/{ACTIVE_ASSET.lower()}_usd_15m_binance.csv"


DATA = DataConfig()


# ============================================================================
# STRATEGY PARAMETERS
# ============================================================================

# V8 - Rounded Bottom Catcher (current main strategy)
V8_PARAMS = {
    # Drop detection
    "drop_window": 15,           # Max days to detect drop
    "min_drop_pct": 15.0,        # Minimum drop percentage to trigger

    # Rise (recovery) requirements
    "rise_window": 20,           # Days to evaluate recovery
    "min_up_days_ratio": 0.40,   # At least 40% up days in window
    "max_single_up_day": 30.0,   # No explosive +30%+ days (disqualifies)
    "max_single_down_day": -20.0, # No panic -20% days (disqualifies)
    "min_rise_pct": 5.0,         # Total rise during window

    # Volume confirmation
    "volume_confirm": False,     # Require volume confirmation

    # Weekly confirmation
    "weekly_ema_period": 5,      # Period for weekly EMA filter

    # Risk management
    "trailing_pct": 20.0,        # Trailing stop percentage from HWM
    "fixed_stop_pct": 10.0,      # Fixed stop loss percentage
}

# ============================================================================
# ASSET-SPECIFIC OPTIMIZED PARAMS FOR V8_FAST
# ============================================================================

# SOL-optimized params
V8_FAST_SOL_PARAMS = {
    "atr_fixed_mult": 2.7,
    "atr_period": 16,
    "atr_trailing_mult": 4.3,
    "daily_ema_period": 7,
    "drop_window": 115,
    "fixed_stop_pct": 5.5,
    "max_single_down_bar": -6.0,
    "max_single_up_bar": 11.5,
    "min_drop_pct": 11.0,
    "min_rise_pct": 4.25,
    "min_up_bars_ratio": 0.4,
    "partial_sell_ratio": 0.55,
    "partial_target_mult": 6.0,
    "rise_window": 80,
    "trailing_pct": 7.5,
    "use_partial_profits": False,
    "volume_confirm": False,
}

# VET-optimized params (Trial #46)
V8_FAST_VET_PARAMS = {
    "atr_fixed_mult": 2.9,
    "atr_period": 22,
    "atr_trailing_mult": 5.0,
    "daily_ema_period": 4,
    "drop_window": 90,
    "fixed_stop_pct": 6.0,
    "max_single_down_bar": -5.0,
    "max_single_up_bar": 12.0,
    "min_drop_pct": 12.5,
    "min_rise_pct": 2.5,
    "min_up_bars_ratio": 0.3,
    "partial_sell_ratio": 0.5,
    "partial_target_mult": 5.75,
    "rise_window": 85,
    "trailing_pct": 9.5,
    "use_partial_profits": False,
    "volume_confirm": False,
}

# Default V8_FAST params (currently using SOL-optimized)
V8_FAST_OPTIMIZED_PARAMS = V8_FAST_SOL_PARAMS

# V8 baseline (original conservative params for comparison)
V8_BASELINE_PARAMS = {
    "drop_window": 15,
    "min_drop_pct": 25.0,
    "rise_window": 20,
    "min_up_days_ratio": 0.50,
    "max_single_up_day": 20.0,
    "max_single_down_day": -10.0,
    "min_rise_pct": 5.0,
    "volume_confirm": True,
    "weekly_ema_period": 5,
    "trailing_pct": 8.0,
    "fixed_stop_pct": 5.0,
}

# V7 - Multi-TF with trailing stops
V7_PARAMS = {
    # Entry
    "ema_short": 9,
    "ema_long": 26,
    "rsi_period": 14,
    "rsi_pullback_1h": 57,
    "min_avg_volume": 1,

    # Exit / Risk
    "initial_stop_pct": 7,
    "trailing_pct": 14.0,
    "rsi_exit_1h": 76,
    "partial_target_pct": 24.0,
    "partial_sell_ratio": 0.45,
    "use_4h_death_cross_exit": True,
}

# V9 - Range Trading with Previous Day High/Low (baseline)
V9_PARAMS = {
    "trend_lookback": 3,         # Days to check for trend pattern
    "approach_pct": 0.5,         # % within prev day high/low to trigger entry
    "target_buffer_pct": 1.0,    # % buffer from exact high/low (99% of range)
    "rr_ratio": 3.0,             # Risk:Reward ratio
    "min_range_pct": 1.0,        # Minimum prev day range as % of price
    "cooldown_bars": 4,          # Minimum hourly bars between trades
    "position_pct": 0.98,        # % of cash to use per trade
}

# V9 SOL-optimized params (Trial #46 - 168.5% return, 64.9% win rate)
V9_SOL_PARAMS = {
    "approach_pct": 0.75,
    "cooldown_bars": 1,
    "min_range_pct": 4.0,
    "position_pct": 0.9,
    "rr_ratio": 2.0,
    "target_buffer_pct": 4.5,
    "trend_lookback": 3,
}

# V9 VET-optimized params (Trial #71 - 154.9% return, 46.3% win rate)
V9_VET_PARAMS = {
    "approach_pct": 3.0,
    "cooldown_bars": 10,
    "min_range_pct": 3.5,
    "position_pct": 0.94,
    "rr_ratio": 3.0,
    "target_buffer_pct": 4.0,
    "trend_lookback": 2,
}

# V9 Universal params (middle ground for cross-asset use)
V9_UNIVERSAL_PARAMS = {
    "trend_lookback": 3,
    "approach_pct": 1.5,
    "target_buffer_pct": 4.0,
    "min_range_pct": 3.5,
    "rr_ratio": 2.5,
    "cooldown_bars": 6,
    "position_pct": 0.92,
}

# Default V9 to universal params
V9_OPTIMIZED_PARAMS = V9_UNIVERSAL_PARAMS

# V10 - Trend Trading with Pullbacks (baseline)
V10_PARAMS = {
    "trend_lookback": 3,         # Days to confirm trend
    "approach_pct": 0.5,         # % within prev day high/low to trigger entry
    "target_buffer_pct": 1.0,    # % buffer from exact high/low
    "rr_ratio": 3.0,             # Risk:Reward ratio
    "min_range_pct": 1.0,        # Minimum prev day range as % of price
    "cooldown_bars": 4,          # Minimum hourly bars between trades
    "position_pct": 0.98,        # % of cash to use per trade
}

# V10 SOL-optimized params (Trial #79 - 150% return, 63.8% win rate, 14.7% max DD)
V10_SOL_PARAMS = {
    "approach_pct": 0.5,
    "cooldown_bars": 11,
    "min_range_pct": 1.5,
    "position_pct": 0.94,
    "rr_ratio": 2.5,
    "target_buffer_pct": 5.0,
    "trend_lookback": 2,
}


# V6 - Multi-TF with bracket orders
V6_PARAMS = {
    "ema_short": 9,
    "ema_long": 26,
    "rsi_period": 14,
    "rsi_low": 55,
    "stop_loss_pct": 3.0,
    "take_profit_pct": 7.0,
    "min_avg_volume": 1,
}

# V3 - Single-TF with trailing stops
V3_PARAMS = {
    "decline_pct": 4.0,
    "decline_window": 5,
    "rise_pct_max": None,
    "rise_window_min": 3,
    "ema_short": 9,
    "ema_long": 26,
    "ema_support1": 21,
    "ema_support2": 100,
    "rsi_period": 14,
    "rsi_low": 40,
    "chandemo_period": 14,
    "chandemo_threshold": -50,
    "volume_increase_pct": 10.0,
    "rsi_exit": 70,
    "stop_loss_pct": 5.0,
    "min_avg_volume": 1000000,
    "scale_in_amount": 0.5,
    "trailing_pct": 8.0,
    "target_pct": 15.0,
}


# ============================================================================
# STRATEGY REGISTRY
# ============================================================================

# Map strategy names to their parameter sets
STRATEGY_PARAMS: Dict[str, Dict[str, Any]] = {
    "v10": V10_SOL_PARAMS,  # Default to optimized
    "v10_baseline": V10_PARAMS,
    "v10_sol": V10_SOL_PARAMS,
    "v9": V9_UNIVERSAL_PARAMS,  # Default to universal
    "v9_baseline": V9_PARAMS,
    "v9_universal": V9_UNIVERSAL_PARAMS,
    "v9_sol": V9_SOL_PARAMS,
    "v9_vet": V9_VET_PARAMS,
    "v8": V8_PARAMS,
    "v8_fast": V8_FAST_OPTIMIZED_PARAMS,
    "v8_fast_sol": V8_FAST_SOL_PARAMS,
    "v8_fast_vet": V8_FAST_VET_PARAMS,
    "v8_baseline": V8_BASELINE_PARAMS,
    "v7": V7_PARAMS,
    "v6": V6_PARAMS,
    "v3": V3_PARAMS,
}

# Map strategy names to their classes (populated at runtime to avoid circular imports)
STRATEGY_CLASSES: Dict[str, Any] = {}


def register_strategies():
    """
    Register strategy classes. Call this after imports are available.
    Returns the STRATEGY_CLASSES dict.
    """
    from strategies.sol_strategy_v3 import SolStrategyV3
    from strategies.sol_strategy_v6 import SolStrategyV6
    from strategies.sol_strategy_v7 import SolStrategyV7
    from strategies.sol_strategy_v8 import SolStrategyV8
    from strategies.sol_strategy_v8_fast import SolStrategyV8Fast
    from strategies.sol_strategy_v9 import SolStrategyV9
    from strategies.sol_strategy_v10 import SolStrategyV10

    STRATEGY_CLASSES.update({
        "v10": SolStrategyV10,
        "v10_baseline": SolStrategyV10,
        "v10_sol": SolStrategyV10,
        "v9": SolStrategyV9,
        "v9_baseline": SolStrategyV9,
        "v9_universal": SolStrategyV9,
        "v9_sol": SolStrategyV9,
        "v9_vet": SolStrategyV9,
        "v3": SolStrategyV3,
        "v6": SolStrategyV6,
        "v7": SolStrategyV7,
        "v8": SolStrategyV8,
        "v8_fast": SolStrategyV8Fast,
        "v8_fast_sol": SolStrategyV8Fast,  # Same class, SOL-optimized params
        "v8_fast_vet": SolStrategyV8Fast,  # Same class, VET-optimized params
        "v8_baseline": SolStrategyV8,
    })
    return STRATEGY_CLASSES


def get_strategy(name: str):
    """Get strategy class by name."""
    if not STRATEGY_CLASSES:
        register_strategies()
    if name not in STRATEGY_CLASSES:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGY_CLASSES.keys())}")
    return STRATEGY_CLASSES[name]


def get_params(name: str) -> Dict[str, Any]:
    """Get strategy parameters by name."""
    if name not in STRATEGY_PARAMS:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGY_PARAMS.keys())}")
    return STRATEGY_PARAMS[name].copy()


# ============================================================================
# TUNING PARAMETER VARIATIONS
# ============================================================================

# Pre-defined parameter variations for tuning V8
V8_TUNE_VARIATIONS = [
    ("Baseline", V8_BASELINE_PARAMS),
    ("Wider trailing (12%)", {**V8_BASELINE_PARAMS, "trailing_pct": 12.0}),
    ("Wider trailing (15%)", {**V8_BASELINE_PARAMS, "trailing_pct": 15.0}),
    ("Wider trailing (20%)", {**V8_BASELINE_PARAMS, "trailing_pct": 20.0}),
    ("Looser entry (20% drop)", {**V8_BASELINE_PARAMS, "min_drop_pct": 20.0}),
    ("Looser entry (15% drop)", {**V8_BASELINE_PARAMS, "min_drop_pct": 15.0}),
    ("Looser single day limits", {**V8_BASELINE_PARAMS, "max_single_up_day": 25.0, "max_single_down_day": -15.0}),
    ("No volume confirm", {**V8_BASELINE_PARAMS, "volume_confirm": False}),
    ("Lower up days ratio (40%)", {**V8_BASELINE_PARAMS, "min_up_days_ratio": 0.40}),
    ("Wider fixed stop (8%)", {**V8_BASELINE_PARAMS, "fixed_stop_pct": 8.0}),
    ("Combined: wider stops", {**V8_BASELINE_PARAMS, "trailing_pct": 15.0, "fixed_stop_pct": 8.0}),
    ("Combined: looser entry + wider stops", {
        **V8_BASELINE_PARAMS,
        "min_drop_pct": 20.0,
        "max_single_up_day": 25.0,
        "max_single_down_day": -15.0,
        "trailing_pct": 15.0,
        "fixed_stop_pct": 8.0,
    }),
    ("Aggressive: very loose", V8_PARAMS),  # Current tuned params
]

# Pre-defined parameter variations for tuning V8 Fast
V8_FAST_TUNE_VARIATIONS = [
    # Baseline
    ("Fast Baseline", V8_FAST_OPTIMIZED_PARAMS),

    # ATR multiplier variations
    ("ATR trailing 2.5x", {**V8_FAST_OPTIMIZED_PARAMS, "atr_trailing_mult": 2.5}),
    ("ATR trailing 3.5x", {**V8_FAST_OPTIMIZED_PARAMS, "atr_trailing_mult": 3.5}),
    ("ATR trailing 4.0x", {**V8_FAST_OPTIMIZED_PARAMS, "atr_trailing_mult": 4.0}),
    ("ATR fixed 1.5x", {**V8_FAST_OPTIMIZED_PARAMS, "atr_fixed_mult": 1.5}),
    ("ATR fixed 2.5x", {**V8_FAST_OPTIMIZED_PARAMS, "atr_fixed_mult": 2.5}),

    # Partial profit variations
    ("Partial at 3x ATR", {**V8_FAST_OPTIMIZED_PARAMS, "partial_target_mult": 3.0}),
    ("Partial at 5x ATR", {**V8_FAST_OPTIMIZED_PARAMS, "partial_target_mult": 5.0}),
    ("Partial 30%", {**V8_FAST_OPTIMIZED_PARAMS, "partial_sell_ratio": 0.3}),
    ("Partial 70%", {**V8_FAST_OPTIMIZED_PARAMS, "partial_sell_ratio": 0.7}),
    ("No partial profits", {**V8_FAST_OPTIMIZED_PARAMS, "use_partial_profits": False}),

    # Entry variations
    ("Smaller drop (8%)", {**V8_FAST_OPTIMIZED_PARAMS, "min_drop_pct": 8.0}),
    ("Larger drop (12%)", {**V8_FAST_OPTIMIZED_PARAMS, "min_drop_pct": 12.0}),
    ("Shorter rise window (60)", {**V8_FAST_OPTIMIZED_PARAMS, "rise_window": 60}),
    ("Longer rise window (100)", {**V8_FAST_OPTIMIZED_PARAMS, "rise_window": 100}),
    ("Longer rise window (120)", {**V8_FAST_OPTIMIZED_PARAMS, "rise_window": 120}),
    ("Higher up ratio (50%)", {**V8_FAST_OPTIMIZED_PARAMS, "min_up_bars_ratio": 0.50}),

    # Combined variations
    ("Tighter stops + early partial", {
        **V8_FAST_OPTIMIZED_PARAMS,
        "atr_trailing_mult": 2.5,
        "atr_fixed_mult": 1.5,
        "partial_target_mult": 3.0,
    }),
    ("Wider stops + late partial", {
        **V8_FAST_OPTIMIZED_PARAMS,
        "atr_trailing_mult": 4.0,
        "atr_fixed_mult": 2.5,
        "partial_target_mult": 5.0,
    }),
    ("Aggressive entry + tight risk", {
        **V8_FAST_OPTIMIZED_PARAMS,
        "min_drop_pct": 8.0,
        "rise_window": 60,
        "atr_trailing_mult": 2.5,
        "partial_sell_ratio": 0.7,
    }),
]
