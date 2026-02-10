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
    leverage: float = 100.0    # 100x leverage (crypto perps)
    risk_per_trade_pct: float = 3.0  # Risk 3% of account at stop loss


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
    "rise_window": 80,
    "trailing_pct": 7.5,
    "volume_confirm": False,
    "risk_per_trade_pct": 3.0,
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
    "rise_window": 85,
    "trailing_pct": 9.5,
    "volume_confirm": False,
    "risk_per_trade_pct": 3.0,
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

# V11 - Combined Range + Trend Strategy (4H Based)
# Reduced trade frequency to minimize commission drag
V11_PARAMS = {
    # Trend detection (4H candles)
    "trend_lookback": 6,           # 4H candles to check for trend
    "min_trend_candles": 4,        # Minimum consecutive HH/HL or LH/LL for trend

    # Range Strategy parameters
    "range_approach_pct": 0.5,     # Entry threshold for range
    "range_min_range_pct": 5.0,    # Minimum 4H range (increased to filter noise)
    "range_buffer_pct": 3.0,       # Target buffer (reduced to let winners run)
    "range_rr_ratio": 3.0,         # R:R ratio (increased for better expectancy)
    "range_cooldown_bars": 96,     # 24 hours = 96 x 15m bars

    # Trend Strategy parameters
    "trend_approach_pct": 0.3,     # Entry threshold for trend (tighter)
    "trend_min_range_pct": 4.0,    # Minimum 4H range
    "trend_buffer_pct": 3.0,       # Target buffer
    "trend_rr_ratio": 3.5,         # R:R ratio
    "trend_cooldown_bars": 192,    # 48 hours = 192 x 15m bars

    # Risk-based position sizing
    "risk_per_trade_pct": 2.0,     # Risk 2% of equity per trade
    "max_position_pct": 30.0,      # Max 30% of equity in single position
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

# V12 - High Win Rate Trend Scalper
# Optimized for WIN RATE, not total return
# V14 - 4H EMA Trend with 15M Crossover Entries
# Simple: 4H trend alignment + 15M EMA crossover + volume + ATR TP/SL
V14_PARAMS = {
    # 4H Trend EMAs
    "ema_fast": 9,
    "ema_slow": 25,

    # 15M Entry EMAs
    "entry_ema_fast": 9,
    "entry_ema_slow": 25,

    # Volume confirmation
    "vol_sma_period": 20,
    "require_volume": True,

    # ATR-based stops (2:1 R:R)
    "atr_period": 14,
    "stop_multiplier": 1.5,
    "tp_multiplier": 3.0,

    # Trend reversal exit
    "exit_on_trend_reversal": True,

    # Position sizing
    "position_pct": 95.0,

    # Cooldown
    "cooldown_bars": 4,
}

# V15 - Zone Trader (1-2 Trades/Day for 20-Trade Exercise)
# 4H trend filter + 1H EMA crossover/pullback entries + risk-based sizing
V15_PARAMS = {
    # 4H Trend EMAs
    "ema_fast_4h_period": 9,
    "ema_slow_4h_period": 21,
    "trend_deadzone_pct": 0.1,

    # 1H Entry EMAs
    "ema_fast_1h_period": 9,
    "ema_slow_1h_period": 21,

    # Entry type toggles
    "enable_crossover_entry": True,
    "enable_pullback_entry": True,

    # Volume confirmation
    "vol_sma_period": 20,
    "require_volume": True,

    # ATR-based stops (2:1 R:R)
    "atr_period": 14,
    "stop_multiplier": 1.5,
    "tp_multiplier": 3.0,

    # Exit controls
    "exit_on_trend_reversal": True,
    "max_hold_bars": 48,

    # Risk-based position sizing (100X leverage)
    "risk_per_trade_pct": 1.0,

    # Cooldown (1H bars)
    "cooldown_bars": 6,
}

# V16 - Trend Exhaustion Catcher (Counter-Trend Complement to V15)
# Enters when 4H trend is losing momentum (convergence) or showing RSI divergence
# V17 - ATR Swing Scalper for Leveraged SOL Trading
# Combines v8_fast ATR exits + v11 risk-based sizing + swing structure entries
V17_PARAMS = {
    # 4H Trend EMAs (optimizable)
    "ema_fast_4h": 9,
    "ema_slow_4h": 21,
    "trend_threshold": 0.5,

    # 1H Swing detection (optimizable)
    "swing_lookback": 3,

    # ATR settings (fixed)
    "atr_period": 14,

    # Stop/TP multipliers (optimizable)
    "stop_mult": 1.5,
    "tp1_mult": 1.5,
    "tp2_mult": 3.0,

    # Risk management (optimizable)
    "risk_per_trade_pct": 0.5,

    # Entry tuning (optimizable)
    "wick_ratio": 0.45,
    "pullback_zone_mult": 1.5,
    "enable_pullback_entry": True,
    "ema_15m_period": 5,
    "ema_fast_1h": 9,

    # Fixed params
    "partial_ratio_1": 0.40,
    "partial_ratio_2": 0.30,
    "trail_mult": 2.0,
    "cooldown_bars": 4,
    "max_hold_bars": 24,
    "max_leverage": 10.0,
    "max_position_pct": 30.0,
    "volume_confirm": False,
}

# V18 - Donchian Channel Breakout (2 params only)
V18_PARAMS = {
    "channel_period": 90,      # 1H bars lookback (~3.75 days)
    "atr_trail_mult": 6.0,     # ATR trailing stop multiplier
    "atr_period": 14,          # ATR calc period on 1H (fixed)
    "risk_per_trade_pct": 3.0, # Risk 3% of account at stop loss
}

V16_PARAMS = {
    # 4H Trend EMAs
    "ema_fast_4h_period": 9,
    "ema_slow_4h_period": 21,
    "trend_deadzone_pct": 0.1,

    # 1H Entry EMAs
    "ema_fast_1h_period": 9,
    "ema_slow_1h_period": 21,

    # Convergence entry (Type A)
    "min_convergence_bars": 3,
    "max_gap_pct": 0.8,

    # RSI divergence entry (Type B)
    "rsi_period_4h": 14,
    "divergence_lookback": 5,
    "rejection_wick_ratio": 0.6,

    # Volume confirmation
    "vol_sma_period": 20,
    "vol_spike_mult": 1.0,

    # ATR-based stops
    "atr_period": 14,
    "stop_multiplier": 2.0,
    "tp_multiplier": 2.5,

    # Exit controls
    "trend_strengthen_exit_pct": 10.0,
    "max_hold_bars": 36,

    # Risk-based position sizing (100X leverage)
    "risk_per_trade_pct": 1.0,

    # Cooldown (1H bars)
    "cooldown_bars": 6,
}

# V15 SOL-optimized params (Trial #85 - 25.8% return, 61.8% win rate, 34 trades)
V15_SOL_PARAMS = {
    "ema_fast_4h_period": 13,
    "ema_slow_4h_period": 27,
    "trend_deadzone_pct": 0.05,
    "ema_fast_1h_period": 13,
    "ema_slow_1h_period": 29,
    "enable_crossover_entry": True,
    "enable_pullback_entry": False,
    "vol_sma_period": 30,
    "require_volume": True,
    "atr_period": 17,
    "stop_multiplier": 2.5,
    "tp_multiplier": 3.5,
    "exit_on_trend_reversal": False,
    "max_hold_bars": 48,
    "risk_per_trade_pct": 3.0,
    "cooldown_bars": 9,
}

# V15 BTC-optimized params (Trial #95 - 8.9% return, 42.4% win rate, 59 trades, 0.24 T/day)
V15_BTC_PARAMS = {
    "ema_fast_4h_period": 10,
    "ema_slow_4h_period": 25,
    "trend_deadzone_pct": 0.25,
    "ema_fast_1h_period": 7,
    "ema_slow_1h_period": 23,
    "enable_crossover_entry": True,
    "enable_pullback_entry": False,
    "vol_sma_period": 20,
    "require_volume": False,
    "atr_period": 20,
    "stop_multiplier": 1.75,
    "tp_multiplier": 4.5,
    "exit_on_trend_reversal": True,
    "max_hold_bars": 72,
    "risk_per_trade_pct": 3.0,
    "cooldown_bars": 11,
}

# V15 ETH-optimized params (Trial #81 - 132.6% return, 52.5% win rate, 139 trades, 0.56 T/day)
V15_ETH_PARAMS = {
    "ema_fast_4h_period": 9,
    "ema_slow_4h_period": 21,
    "trend_deadzone_pct": 0.45,
    "ema_fast_1h_period": 10,
    "ema_slow_1h_period": 22,
    "enable_crossover_entry": True,
    "enable_pullback_entry": True,
    "vol_sma_period": 15,
    "require_volume": True,
    "atr_period": 18,
    "stop_multiplier": 1.75,
    "tp_multiplier": 3.0,
    "exit_on_trend_reversal": False,
    "max_hold_bars": 36,
    "risk_per_trade_pct": 3.0,
    "cooldown_bars": 3,
}

# V13 - Trend Momentum Rider
# Designed to capture BIGGER moves with volume confirmation and ATR trailing stops
V13_PARAMS = {
    # Trend detection (4H)
    "ema_fast": 8,
    "ema_slow": 21,
    "trend_strength_min": 0.5,

    # Volume entry confirmation
    "vol_sma_period": 20,
    "vol_expansion_mult": 1.3,
    "require_volume_confirm": True,

    # OBV confirmation (disabled - was blocking entries)
    "use_obv_filter": False,
    "obv_ema_period": 10,

    # RSI (very lenient - just avoid extremes)
    "rsi_period": 14,
    "rsi_oversold": 30,
    "rsi_overbought": 70,

    # Pullback (disabled by default)
    "use_pullback_filter": False,
    "pullback_pct": 0.5,

    # ATR-based stops
    "atr_period": 14,
    "atr_trailing_mult": 2.5,
    "atr_initial_mult": 1.5,

    # Fallback fixed stops
    "trailing_pct": 4.0,
    "initial_stop_pct": 3.0,

    # Take profit (disabled - use trailing)
    "use_fixed_tp": False,
    "fixed_tp_pct": 8.0,

    # Partial profits
    "use_partial_profits": True,
    "partial_target_atr_mult": 3.0,
    "partial_sell_ratio": 0.33,

    # Volume exit
    "use_volume_exit": True,
    "vol_climax_mult": 2.5,
    "price_stall_pct": 0.3,

    # Position sizing
    "risk_pct": 2.0,
    "position_pct": 90.0,

    # Cooldown
    "cooldown_bars": 8,
}

# Map strategy names to their parameter sets
STRATEGY_PARAMS: Dict[str, Dict[str, Any]] = {
    "v18": V18_PARAMS,
    "v17": V17_PARAMS,
    "v16": V16_PARAMS,
    "v15": V15_SOL_PARAMS,  # Default to SOL-optimized
    "v15_baseline": V15_PARAMS,
    "v15_sol": V15_SOL_PARAMS,
    "v15_btc": V15_BTC_PARAMS,
    "v15_eth": V15_ETH_PARAMS,
    "v14": V14_PARAMS,
    "v13": V13_PARAMS,
    "v11": V11_PARAMS,
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
    from strategies.sol_strategy_v11 import SolStrategyV11
    from strategies.sol_strategy_v13 import SolStrategyV13
    from strategies.sol_strategy_v14 import SolStrategyV14
    from strategies.sol_strategy_v15 import SolStrategyV15
    from strategies.sol_strategy_v16 import SolStrategyV16
    from strategies.sol_strategy_v17 import SolStrategyV17
    from strategies.sol_strategy_v18 import SolStrategyV18

    STRATEGY_CLASSES.update({
        "v18": SolStrategyV18,
        "v17": SolStrategyV17,
        "v16": SolStrategyV16,
        "v15": SolStrategyV15,
        "v15_baseline": SolStrategyV15,
        "v15_sol": SolStrategyV15,
        "v15_btc": SolStrategyV15,
        "v15_eth": SolStrategyV15,
        "v14": SolStrategyV14,
        "v13": SolStrategyV13,
        "v11": SolStrategyV11,
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

    # ATR multiplier variations (affects 1R distance and runner trail)
    ("ATR trailing 2.5x", {**V8_FAST_OPTIMIZED_PARAMS, "atr_trailing_mult": 2.5}),
    ("ATR trailing 3.5x", {**V8_FAST_OPTIMIZED_PARAMS, "atr_trailing_mult": 3.5}),
    ("ATR trailing 4.0x", {**V8_FAST_OPTIMIZED_PARAMS, "atr_trailing_mult": 4.0}),
    ("ATR fixed 1.5x (tighter 1R)", {**V8_FAST_OPTIMIZED_PARAMS, "atr_fixed_mult": 1.5}),
    ("ATR fixed 2.5x", {**V8_FAST_OPTIMIZED_PARAMS, "atr_fixed_mult": 2.5}),

    # Entry variations
    ("Smaller drop (8%)", {**V8_FAST_OPTIMIZED_PARAMS, "min_drop_pct": 8.0}),
    ("Larger drop (12%)", {**V8_FAST_OPTIMIZED_PARAMS, "min_drop_pct": 12.0}),
    ("Shorter rise window (60)", {**V8_FAST_OPTIMIZED_PARAMS, "rise_window": 60}),
    ("Longer rise window (100)", {**V8_FAST_OPTIMIZED_PARAMS, "rise_window": 100}),
    ("Longer rise window (120)", {**V8_FAST_OPTIMIZED_PARAMS, "rise_window": 120}),
    ("Higher up ratio (50%)", {**V8_FAST_OPTIMIZED_PARAMS, "min_up_bars_ratio": 0.50}),

    # Risk variations
    ("Risk 2%", {**V8_FAST_OPTIMIZED_PARAMS, "risk_per_trade_pct": 2.0}),
    ("Risk 5%", {**V8_FAST_OPTIMIZED_PARAMS, "risk_per_trade_pct": 5.0}),

    # Combined variations
    ("Tighter 1R + tight trail", {
        **V8_FAST_OPTIMIZED_PARAMS,
        "atr_trailing_mult": 2.5,
        "atr_fixed_mult": 1.5,
    }),
    ("Wider 1R + wide trail", {
        **V8_FAST_OPTIMIZED_PARAMS,
        "atr_trailing_mult": 4.0,
        "atr_fixed_mult": 2.5,
    }),
    ("Aggressive entry + tight 1R", {
        **V8_FAST_OPTIMIZED_PARAMS,
        "min_drop_pct": 8.0,
        "rise_window": 60,
        "atr_fixed_mult": 1.5,
    }),
]
