#!/usr/bin/env python3
# regime.py
"""
Market regime classification for backtrader strategies.

Classifies each bar into a regime combining trend direction and volatility level.
Injected via StrategyWrapper so all strategies get regime labels automatically.

Trend classification (daily EMA slope):
  - uptrend: EMA slope positive over N bars AND price above EMA
  - downtrend: EMA slope negative over N bars AND price below EMA
  - ranging: neither

Volatility classification (4H ATR percentile):
  - high_vol: current ATR > 75th percentile of trailing window
  - low_vol: current ATR < 25th percentile
  - normal_vol: between 25th and 75th
"""

import backtrader as bt
import backtrader.indicators as btind


class MarketRegime:
    """
    Classifies market regime using daily and 4H data feeds.

    Usage inside a backtrader Strategy:
        self.regime = MarketRegime(self.datas[4], self.datas[2])  # daily, 4H
        # In next():
        regime_info = self.regime.classify()
    """

    def __init__(self, daily_data, data_4h, ema_period=21, slope_lookback=5, atr_period=14, vol_window=90):
        """
        Args:
            daily_data: backtrader daily data feed (self.datas[4])
            data_4h: backtrader 4H data feed (self.datas[2])
            ema_period: EMA period on daily for trend detection
            slope_lookback: number of bars to measure EMA slope over
            atr_period: ATR period on 4H for volatility
            vol_window: trailing window (in 4H bars) for ATR percentile calc
        """
        self.daily_data = daily_data
        self.data_4h = data_4h
        self.slope_lookback = slope_lookback
        self.vol_window = vol_window

        # Daily EMA for trend
        self.daily_ema = btind.EMA(daily_data.close, period=ema_period)

        # 4H ATR for volatility
        self.atr_4h = btind.ATR(data_4h, period=atr_period)

        # Store ATR history for percentile calculation
        self._atr_history = []

    def classify(self):
        """
        Classify the current bar's market regime.

        Returns:
            dict with keys: trend, volatility, regime, ema_slope, atr_percentile
        """
        # --- Trend classification (daily) ---
        trend = "ranging"
        ema_slope = 0.0

        try:
            current_ema = self.daily_ema[0]
            past_ema = self.daily_ema[-self.slope_lookback]
            current_price = self.daily_data.close[0]

            if current_ema > 0 and past_ema > 0:
                ema_slope = (current_ema - past_ema) / past_ema * 100

                if ema_slope > 0 and current_price > current_ema:
                    trend = "uptrend"
                elif ema_slope < 0 and current_price < current_ema:
                    trend = "downtrend"
        except (IndexError, ZeroDivisionError):
            pass

        # --- Volatility classification (4H ATR percentile) ---
        volatility = "normal_vol"
        atr_percentile = 50.0

        try:
            current_atr = self.atr_4h[0]
            if current_atr > 0:
                self._atr_history.append(current_atr)
                # Keep only the trailing window
                if len(self._atr_history) > self.vol_window:
                    self._atr_history = self._atr_history[-self.vol_window:]

                if len(self._atr_history) >= 20:  # Need minimum history
                    sorted_atr = sorted(self._atr_history)
                    rank = sum(1 for x in sorted_atr if x <= current_atr)
                    atr_percentile = (rank / len(sorted_atr)) * 100

                    if atr_percentile > 75:
                        volatility = "high_vol"
                    elif atr_percentile < 25:
                        volatility = "low_vol"
        except (IndexError, ZeroDivisionError):
            pass

        regime = f"{trend}_{volatility}"

        return {
            "trend": trend,
            "volatility": volatility,
            "regime": regime,
            "ema_slope": round(ema_slope, 3),
            "atr_percentile": round(atr_percentile, 1),
        }
