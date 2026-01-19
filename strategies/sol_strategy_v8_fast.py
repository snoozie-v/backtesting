# strategies/sol_strategy_v8_fast.py
"""
SolStrategy v8 Fast - Rounded Bottom Catcher (4H/15M Version)
--------------------------------------------------------------
Adapted from V8 to use shorter timeframes for more frequent trades.

Improvements over base V8:
- Sliding window: Continues looking for valid patterns instead of hard reset
- ATR-based stops: Dynamic stops based on volatility instead of fixed percentages
- Partial profit-taking: Takes partial profits at target, lets rest ride

Logic:
- Detect FAST DROP: ≥10% decline over max 90 4H-bars (~15 days) on 4H timeframe
- Then look for SLOW/CONTROLLED RISE using sliding window on 4H:
  - ≥40% up bars in the window
  - No single 4H bar > +8% or < -6%
  - Total rise ≥3% during the window
- Multi-timeframe filter: 4H close > 5-period EMA on DAILY chart
- Entry: on the 4H bar that meets conditions, using current 15m close price
- Exits: ATR-based trailing stop, partial profit at target

Data feeds (expected index order):
  0 → 15m (base for entry/exit prices)
  1 → 1h (unused)
  2 → 4h (main logic: drop/rise detection)
  3 → weekly (unused)
  4 → daily (for MTF EMA filter)
"""

import backtrader as bt
import backtrader.indicators as btind


class SolStrategyV8Fast(bt.Strategy):
    params = (
        # Drop detection (in 4H bars)
        ('drop_window', 90),          # ~15 days of 4H bars (6 bars/day)
        ('min_drop_pct', 10.0),       # Smaller drop threshold for 4H

        # Rise (recovery) requirements (in 4H bars)
        ('rise_window', 120),         # ~20 days of 4H bars
        ('min_up_bars_ratio', 0.40),  # at least 40% up bars
        ('max_single_up_bar', 8.0),   # no explosive +8%+ 4H bars
        ('max_single_down_bar', -6.0),# no big panic -6% 4H bars
        ('min_rise_pct', 3.0),        # total rise during window

        # Volume confirmation during rise
        ('volume_confirm', False),

        # Daily confirmation
        ('daily_ema_period', 5),

        # ATR-based stops
        ('atr_period', 14),           # ATR calculation period (on 4H)
        ('atr_trailing_mult', 3.0),   # Trailing stop = ATR * multiplier
        ('atr_fixed_mult', 2.0),      # Fixed stop = ATR * multiplier

        # Fallback fixed stops (used if ATR not available)
        ('trailing_pct', 6.0),
        ('fixed_stop_pct', 4.0),

        # Partial profit-taking
        ('partial_target_mult', 4.0), # Take partial at ATR * multiplier gain
        ('partial_sell_ratio', 0.5),  # Sell this fraction at target
        ('use_partial_profits', True),
    )

    def __init__(self):
        # Data feeds
        self.data15 = self.datas[0]  # 15m: for precise entry/exit prices
        self.data4h = self.datas[2]  # 4H: for drop/rise logic
        self.daily = self.datas[4]   # Daily: for MTF filter

        # Indicators on 4H
        self.avg_volume = btind.SMA(self.data4h.volume, period=120)
        self.atr = btind.ATR(self.data4h, period=self.p.atr_period)

        # Daily EMA for MTF filter
        self.daily_ema = btind.EMA(self.daily.close, period=self.p.daily_ema_period)

        # State tracking
        self.drop_detected = False
        self.high_water_mark = None
        self.entry_price = None
        self.entry_atr = None  # ATR at entry for stop calculation
        self.partial_taken = False  # Track if partial profit was taken

        # Sliding window for rise analysis
        self.rise_window_data = []  # List of (close, volume, bar_change_pct)

        # To run main logic only on new 4H bars
        self.last_4h_len = 0

    def next(self):
        # Exit checks: run on every 15m bar if in position
        if self.position:
            self._check_exits()
            if not self.position:  # Exit occurred
                return

        # Safety: need enough data on 4H and daily
        if len(self.data4h) < max(self.p.drop_window + 1, self.p.rise_window + 1, 150):
            return

        if len(self.daily) < self.p.daily_ema_period + 1:
            return

        # Run detection/entry logic only on new 4H bar
        if len(self.data4h) == self.last_4h_len:
            return

        self.last_4h_len = len(self.data4h)

        # Use 4H datetime for prints
        dt = self.data4h.datetime.datetime(0)

        # ── 1. Detect Fast Drop ───────────────────────────────────────
        if not self.drop_detected and not self.position:
            closes = self.data4h.close.get(size=self.p.drop_window)

            if len(closes) < self.p.drop_window:
                return

            peak = max(closes)
            trough = min(closes)
            drop_pct = (trough - peak) / peak * 100

            if drop_pct <= -self.p.min_drop_pct:
                print(f"[{dt}] FAST DROP DETECTED: {-drop_pct:.1f}% over <={self.p.drop_window} 4H bars")
                self.drop_detected = True
                self.rise_window_data = []  # Reset sliding window

        # ── 2. Monitor potential slow rise after drop (sliding window) ──
        if self.drop_detected and not self.position:
            # Calculate current bar change
            bar_change_pct = 0.0
            if len(self.data4h) >= 2:
                bar_change_pct = (self.data4h.close[0] - self.data4h.close[-1]) / self.data4h.close[-1] * 100

            # Check for disqualifying bars - but with sliding window, just skip this bar
            if bar_change_pct > self.p.max_single_up_bar:
                print(f"[{dt}] Sliding window: skipping explosive bar +{bar_change_pct:.1f}%")
                # Don't reset completely - just don't add this bar
                return

            if bar_change_pct < self.p.max_single_down_bar:
                print(f"[{dt}] Sliding window: skipping panic bar {bar_change_pct:.1f}%")
                # Don't reset completely - just don't add this bar
                return

            # Add current bar to sliding window
            self.rise_window_data.append({
                'close': self.data4h.close[0],
                'volume': self.data4h.volume[0],
                'bar_change_pct': bar_change_pct,
            })

            # Keep window at max size by removing oldest
            while len(self.rise_window_data) > self.p.rise_window:
                self.rise_window_data.pop(0)

            # Need minimum bars to evaluate
            if len(self.rise_window_data) < self.p.rise_window // 2:
                return

            # Evaluate current window
            if self._evaluate_rise_window(dt):
                # Entry triggered
                self._enter_position(dt)

    def _evaluate_rise_window(self, dt) -> bool:
        """Evaluate if current sliding window meets entry conditions."""
        if len(self.rise_window_data) < 2:
            return False

        window = self.rise_window_data

        # Calculate total rise in window
        start_price = window[0]['close']
        end_price = window[-1]['close']
        total_rise_pct = (end_price - start_price) / start_price * 100

        # Count up bars (bars where close > previous close)
        up_bars = sum(1 for d in window if d['bar_change_pct'] > 0)
        up_ratio = up_bars / len(window)

        # Volume confirmation
        volume_ok = True
        if self.p.volume_confirm:
            avg_rise_vol = sum(d['volume'] for d in window) / len(window)
            current_avg_vol = self.avg_volume[0]
            volume_ok = avg_rise_vol >= current_avg_vol

        # MTF filter: 4H close above daily EMA
        mtf_ok = self.data4h.close[0] > self.daily_ema[0]

        conditions_met = (
            up_ratio >= self.p.min_up_bars_ratio and
            total_rise_pct >= self.p.min_rise_pct and
            volume_ok and
            mtf_ok
        )

        if conditions_met:
            print(f"[{dt}] ENTRY CONDITIONS MET! "
                  f"Rise: {total_rise_pct:.1f}%, Up bars: {up_ratio:.2%}, "
                  f"Vol ok: {volume_ok}, Daily EMA ok: {mtf_ok}")
            return True

        return False

    def _enter_position(self, dt):
        """Execute entry with position tracking."""
        size = self.broker.get_cash() / self.data15.close[0] * 0.98
        self.buy(size=size)
        self.entry_price = self.data15.close[0]
        self.high_water_mark = self.data15.close[0]
        self.entry_atr = self.atr[0] if self.atr[0] > 0 else None
        self.partial_taken = False

        atr_info = f", ATR: {self.entry_atr:.4f}" if self.entry_atr else ""
        print(f"[{dt}] ENTRY @ {self.entry_price:.4f}{atr_info}")

        # Reset state
        self.drop_detected = False
        self.rise_window_data = []

    def _check_exits(self):
        """Check all exit conditions on every 15m bar."""
        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        # Update high water mark
        self.high_water_mark = max(self.high_water_mark, current_price)

        # Calculate stops based on ATR or fallback to fixed percentages
        if self.entry_atr and self.entry_atr > 0:
            # ATR-based stops
            trailing_distance = self.entry_atr * self.p.atr_trailing_mult
            fixed_distance = self.entry_atr * self.p.atr_fixed_mult

            trailing_stop = self.high_water_mark - trailing_distance
            fixed_stop = self.entry_price - fixed_distance
        else:
            # Fallback to percentage-based stops
            trailing_stop = self.high_water_mark * (1 - self.p.trailing_pct / 100)
            fixed_stop = self.entry_price * (1 - self.p.fixed_stop_pct / 100)

        # Check partial profit target (before stop checks)
        if self.p.use_partial_profits and not self.partial_taken:
            if self.entry_atr and self.entry_atr > 0:
                target_price = self.entry_price + (self.entry_atr * self.p.partial_target_mult)
            else:
                # Fallback: use 2x the trailing stop distance as target
                target_price = self.entry_price * (1 + self.p.trailing_pct * 2 / 100)

            if current_price >= target_price:
                partial_size = self.position.size * self.p.partial_sell_ratio
                gain_pct = (current_price - self.entry_price) / self.entry_price * 100
                print(f"[{dt}] PARTIAL PROFIT @ {current_price:.4f} "
                      f"(+{gain_pct:.1f}%, selling {self.p.partial_sell_ratio:.0%})")
                self.sell(size=partial_size)
                self.partial_taken = True
                return  # Don't check stops on same bar as partial

        # Check stop losses
        effective_stop = max(trailing_stop, fixed_stop)

        if current_price <= effective_stop:
            reason = "TRAILING" if current_price <= trailing_stop else "FIXED"
            pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
            print(f"[{dt}] EXIT ({reason} STOP) @ {current_price:.4f} | "
                  f"HWM: {self.high_water_mark:.4f} | PnL: {pnl_pct:+.1f}%")
            self.sell(size=self.position.size)
            self._reset_state()

    def _reset_state(self):
        """Reset all state after exit."""
        self.drop_detected = False
        self.rise_window_data = []
        self.high_water_mark = None
        self.entry_price = None
        self.entry_atr = None
        self.partial_taken = False
