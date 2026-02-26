# strategies/sol_strategy_v8_fast.py
"""
SolStrategy v8 Fast - Rounded Bottom/Top Catcher (4H/15M Version)
------------------------------------------------------------------
Trades both directions using mirrored pattern detection.

LONG entry (drop → recovery):
- Detect FAST DROP: ≥min_drop_pct% decline over drop_window 4H bars
- Then SLOW/CONTROLLED RISE: majority up bars, no explosive moves, total rise ≥min_rise_pct%
- MTF filter: 4H close > daily EMA (bullish)

SHORT entry (pump → decline):
- Detect FAST PUMP: ≥min_drop_pct% rise over drop_window 4H bars
- Then SLOW/CONTROLLED DECLINE: majority down bars, no explosive moves, total decline ≥min_rise_pct%
- MTF filter: 4H close < daily EMA (bearish)

Same parameters control both directions — no additional optimizer dimensions.

Exits (both directions):
- R-based partials: 30% at 1R, 30% at 2R, 30% at 3R, 10% runner
- Stop ratchets: breakeven at 1R, +1R at 2R, +2R at 3R
- Runner: ATR trailing stop after all 3 partials taken

Risk Model:
- Position sized so stop loss (-1R) = risk_per_trade_pct of account
- 1R = ATR * atr_fixed_mult

Data feeds (expected index order):
  0 → 15m (base for entry/exit prices)
  1 → 1h (unused)
  2 → 4h (main logic: drop/rise detection)
  3 → weekly (unused)
  4 → daily (for MTF EMA filter)
"""

import backtrader as bt
import backtrader.indicators as btind
from risk_manager import RiskManager


class SolStrategyV8Fast(bt.Strategy):
    params = (
        # Drop/pump detection (in 4H bars)
        ('drop_window', 90),          # ~15 days of 4H bars (6 bars/day)
        ('min_drop_pct', 10.0),       # Min % move to trigger (drop or pump)

        # Rise/decline requirements (in 4H bars)
        ('rise_window', 120),         # ~20 days of 4H bars
        ('min_up_bars_ratio', 0.40),  # at least 40% directional bars
        ('max_single_up_bar', 8.0),   # no explosive +8%+ 4H bars
        ('max_single_down_bar', -6.0),# no big panic -6% 4H bars
        ('min_rise_pct', 3.0),        # total move during window

        # Volume confirmation during rise/decline
        ('volume_confirm', False),

        # Daily confirmation
        ('daily_ema_period', 5),

        # ATR-based stops (defines 1R)
        ('atr_period', 14),           # ATR calculation period (on 4H)
        ('atr_trailing_mult', 3.0),   # ATR trailing stop for runner
        ('atr_fixed_mult', 2.0),      # Fixed stop = 1R = ATR * this

        # Fallback fixed stops (used if ATR not available)
        ('trailing_pct', 6.0),
        ('fixed_stop_pct', 4.0),

        # Risk management
        ('risk_per_trade_pct', 3.0),  # Risk 3% of account at stop loss
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

        # Risk manager
        self.risk_mgr = RiskManager(risk_pct=self.p.risk_per_trade_pct)

        # State tracking — shared
        self.position_type = None     # 'long' or 'short'
        self.entry_price = None
        self.entry_atr = None
        self.stop_distance = None     # 1R distance
        self.r_targets = {}           # {1: price, 2: price, 3: price}
        self.current_stop = None      # Current stop price (ratchets)
        self.partials_taken = 0       # How many R-level partials taken
        self.initial_size = 0         # Original position size

        # Long-specific state
        self.drop_detected = False
        self.high_water_mark = None
        self.rise_window_data = []

        # Short-specific state
        self.pump_detected = False
        self.low_water_mark = None
        self.decline_window_data = []

        # To run main logic only on new 4H bars
        self.last_4h_len = 0

    def next(self):
        # Exit checks: run on every 15m bar if in position
        if self.position:
            self._check_exits()
            if not self.position:
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

        closes = self.data4h.close.get(size=self.p.drop_window)
        if len(closes) < self.p.drop_window:
            return

        peak = max(closes)
        trough = min(closes)

        # ── 1a. Detect Fast Drop (for longs) ────────────────────────────
        if not self.drop_detected and not self.position:
            drop_pct = (trough - peak) / peak * 100

            if drop_pct <= -self.p.min_drop_pct:
                print(f"[{dt}] FAST DROP DETECTED: {-drop_pct:.1f}% over <={self.p.drop_window} 4H bars")
                self.drop_detected = True
                self.rise_window_data = []

        # ── 1b. Detect Fast Pump (for shorts) ───────────────────────────
        if not self.pump_detected and not self.position:
            rise_pct = (peak - trough) / trough * 100

            if rise_pct >= self.p.min_drop_pct:
                print(f"[{dt}] FAST PUMP DETECTED: {rise_pct:.1f}% over <={self.p.drop_window} 4H bars")
                self.pump_detected = True
                self.decline_window_data = []

        # Bar change for sliding windows
        bar_change_pct = 0.0
        if len(self.data4h) >= 2:
            bar_change_pct = (self.data4h.close[0] - self.data4h.close[-1]) / self.data4h.close[-1] * 100

        # ── 2a. Monitor slow rise after drop (sliding window for longs) ──
        if self.drop_detected and not self.position:
            if bar_change_pct > self.p.max_single_up_bar:
                pass  # Skip explosive bar, don't add to window
            elif bar_change_pct < self.p.max_single_down_bar:
                pass  # Skip panic bar
            else:
                self.rise_window_data.append({
                    'close': self.data4h.close[0],
                    'volume': self.data4h.volume[0],
                    'bar_change_pct': bar_change_pct,
                })

                while len(self.rise_window_data) > self.p.rise_window:
                    self.rise_window_data.pop(0)

                if len(self.rise_window_data) >= self.p.rise_window // 2:
                    if self._evaluate_rise_window(dt):
                        self._enter_long_position(dt)
                        return

        # ── 2b. Monitor slow decline after pump (sliding window for shorts) ──
        if self.pump_detected and not self.position:
            if bar_change_pct > self.p.max_single_up_bar:
                pass  # Skip explosive bar
            elif bar_change_pct < self.p.max_single_down_bar:
                pass  # Skip panic bar
            else:
                self.decline_window_data.append({
                    'close': self.data4h.close[0],
                    'volume': self.data4h.volume[0],
                    'bar_change_pct': bar_change_pct,
                })

                while len(self.decline_window_data) > self.p.rise_window:
                    self.decline_window_data.pop(0)

                if len(self.decline_window_data) >= self.p.rise_window // 2:
                    if self._evaluate_decline_window(dt):
                        self._enter_short_position(dt)
                        return

    def _evaluate_rise_window(self, dt) -> bool:
        """Evaluate if current sliding window meets long entry conditions."""
        if len(self.rise_window_data) < 2:
            return False

        window = self.rise_window_data

        start_price = window[0]['close']
        end_price = window[-1]['close']
        total_rise_pct = (end_price - start_price) / start_price * 100

        up_bars = sum(1 for d in window if d['bar_change_pct'] > 0)
        up_ratio = up_bars / len(window)

        volume_ok = True
        if self.p.volume_confirm:
            avg_rise_vol = sum(d['volume'] for d in window) / len(window)
            current_avg_vol = self.avg_volume[0]
            volume_ok = avg_rise_vol >= current_avg_vol

        mtf_ok = self.data4h.close[0] > self.daily_ema[0]

        conditions_met = (
            up_ratio >= self.p.min_up_bars_ratio and
            total_rise_pct >= self.p.min_rise_pct and
            volume_ok and
            mtf_ok
        )

        if conditions_met:
            print(f"[{dt}] LONG ENTRY CONDITIONS MET! "
                  f"Rise: {total_rise_pct:.1f}%, Up bars: {up_ratio:.2%}, "
                  f"Vol ok: {volume_ok}, Daily EMA ok: {mtf_ok}")
            return True

        return False

    def _evaluate_decline_window(self, dt) -> bool:
        """Evaluate if current sliding window meets short entry conditions."""
        if len(self.decline_window_data) < 2:
            return False

        window = self.decline_window_data

        start_price = window[0]['close']
        end_price = window[-1]['close']
        total_decline_pct = (start_price - end_price) / start_price * 100  # Positive = price fell

        down_bars = sum(1 for d in window if d['bar_change_pct'] < 0)
        down_ratio = down_bars / len(window)

        volume_ok = True
        if self.p.volume_confirm:
            avg_decline_vol = sum(d['volume'] for d in window) / len(window)
            current_avg_vol = self.avg_volume[0]
            volume_ok = avg_decline_vol >= current_avg_vol

        mtf_ok = self.data4h.close[0] < self.daily_ema[0]  # Bearish: below EMA

        conditions_met = (
            down_ratio >= self.p.min_up_bars_ratio and
            total_decline_pct >= self.p.min_rise_pct and
            volume_ok and
            mtf_ok
        )

        if conditions_met:
            print(f"[{dt}] SHORT ENTRY CONDITIONS MET! "
                  f"Decline: {total_decline_pct:.1f}%, Down bars: {down_ratio:.2%}, "
                  f"Vol ok: {volume_ok}, Daily EMA ok: {mtf_ok}")
            return True

        return False

    def _enter_long_position(self, dt):
        """Execute long entry with R-based position sizing."""
        price = self.data15.close[0]
        equity = self.broker.getvalue()
        atr = self.atr[0] if self.atr[0] > 0 else None

        if not atr:
            self.stop_distance = price * (self.p.fixed_stop_pct / 100)
        else:
            self.stop_distance = atr * self.p.atr_fixed_mult

        size = self.risk_mgr.calculate_position_size(equity, self.stop_distance)
        if size <= 0:
            return

        max_size = (equity * 100) / price
        size = min(size, max_size * 0.95)

        self.buy(size=size)
        self.position_type = 'long'
        self.entry_price = price
        self.high_water_mark = price
        self.entry_atr = atr
        self.initial_size = size
        self.partials_taken = 0

        self.r_targets = self.risk_mgr.calculate_r_targets(price, self.stop_distance, 'long')
        self.current_stop = self.r_targets[-1]

        risk_amt = equity * self.risk_mgr.risk_pct
        print(f"[{dt}] LONG ENTRY @ {price:.4f} | "
              f"Size: {size:.4f} | Risk: ${risk_amt:.0f} ({self.p.risk_per_trade_pct}%) | "
              f"Stop: {self.current_stop:.4f} (-1R) | "
              f"1R: {self.r_targets.get(1.0, 0):.4f} | "
              f"2R: {self.r_targets.get(2.0, 0):.4f} | "
              f"3R: {self.r_targets.get(3.0, 0):.4f}")

        rise_pct = 0.0
        if len(self.rise_window_data) >= 2:
            rise_pct = (self.rise_window_data[-1]['close'] - self.rise_window_data[0]['close']) / self.rise_window_data[0]['close'] * 100
        daily_ema_val = self.daily_ema[0] if len(self.daily_ema) > 0 else 0
        ema_dist_pct = ((self.entry_price - daily_ema_val) / daily_ema_val * 100) if daily_ema_val > 0 else 0
        self._entry_context = {
            "direction": "long",
            "atr": round(self.entry_atr, 4) if self.entry_atr else 0,
            "daily_ema_dist_pct": round(ema_dist_pct, 2),
            "rise_pct": round(rise_pct, 2),
            "window_bars": len(self.rise_window_data),
            "stop_distance": round(self.stop_distance, 4),
            "risk_pct": self.p.risk_per_trade_pct,
            "position_size": round(size, 4),
        }

        self.drop_detected = False
        self.rise_window_data = []

    def _enter_short_position(self, dt):
        """Execute short entry with R-based position sizing."""
        price = self.data15.close[0]
        equity = self.broker.getvalue()
        atr = self.atr[0] if self.atr[0] > 0 else None

        if not atr:
            self.stop_distance = price * (self.p.fixed_stop_pct / 100)
        else:
            self.stop_distance = atr * self.p.atr_fixed_mult

        size = self.risk_mgr.calculate_position_size(equity, self.stop_distance)
        if size <= 0:
            return

        max_size = (equity * 100) / price
        size = min(size, max_size * 0.95)

        self.sell(size=size)
        self.position_type = 'short'
        self.entry_price = price
        self.low_water_mark = price
        self.entry_atr = atr
        self.initial_size = size
        self.partials_taken = 0

        self.r_targets = self.risk_mgr.calculate_r_targets(price, self.stop_distance, 'short')
        self.current_stop = self.r_targets[-1]

        risk_amt = equity * self.risk_mgr.risk_pct
        print(f"[{dt}] SHORT ENTRY @ {price:.4f} | "
              f"Size: {size:.4f} | Risk: ${risk_amt:.0f} ({self.p.risk_per_trade_pct}%) | "
              f"Stop: {self.current_stop:.4f} (-1R) | "
              f"1R: {self.r_targets.get(1.0, 0):.4f} | "
              f"2R: {self.r_targets.get(2.0, 0):.4f} | "
              f"3R: {self.r_targets.get(3.0, 0):.4f}")

        decline_pct = 0.0
        if len(self.decline_window_data) >= 2:
            decline_pct = (self.decline_window_data[0]['close'] - self.decline_window_data[-1]['close']) / self.decline_window_data[0]['close'] * 100
        daily_ema_val = self.daily_ema[0] if len(self.daily_ema) > 0 else 0
        ema_dist_pct = ((self.entry_price - daily_ema_val) / daily_ema_val * 100) if daily_ema_val > 0 else 0
        self._entry_context = {
            "direction": "short",
            "atr": round(self.entry_atr, 4) if self.entry_atr else 0,
            "daily_ema_dist_pct": round(ema_dist_pct, 2),
            "decline_pct": round(decline_pct, 2),
            "window_bars": len(self.decline_window_data),
            "stop_distance": round(self.stop_distance, 4),
            "risk_pct": self.p.risk_per_trade_pct,
            "position_size": round(size, 4),
        }

        self.pump_detected = False
        self.decline_window_data = []

    def _check_exits(self):
        """Check R-based exits on every 15m bar."""
        if self.entry_price is None or self.stop_distance is None:
            return

        if self.position_type == 'long':
            self._check_long_exits()
        elif self.position_type == 'short':
            self._check_short_exits()

    def _check_long_exits(self):
        """Check exits for long position."""
        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        self.high_water_mark = max(self.high_water_mark, current_price)

        # Check R-target partials (in order: 1R, 2R, 3R)
        for i, (r_mult, fraction) in enumerate(self.risk_mgr.partial_schedule):
            if self.partials_taken > i:
                continue
            target_price = self.r_targets.get(r_mult)
            if target_price and current_price >= target_price:
                partial_size = self.initial_size * fraction
                if partial_size > abs(self.position.size):
                    partial_size = abs(self.position.size)
                if partial_size > 0:
                    self.partials_taken = i + 1
                    self.current_stop = self.risk_mgr.get_stop_for_level(
                        self.entry_price, self.stop_distance, self.partials_taken, 'long')
                    print(f"[{dt}] LONG PARTIAL {self.partials_taken}/3 @ {current_price:.4f} "
                          f"(+{r_mult:.0f}R, selling {fraction:.0%}) | "
                          f"New stop: {self.current_stop:.4f}")
                    self.sell(size=partial_size)
                    return

        # Check stop loss (ratcheted)
        if current_price <= self.current_stop:
            pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
            r_mult = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'long')
            reason = "LONG STOP" if self.partials_taken == 0 else f"LONG RATCHET STOP (after {self.partials_taken}R)"
            print(f"[{dt}] {reason} @ {current_price:.4f} ({pnl_pct:+.1f}%, {r_mult:+.1f}R)")
            self.sell(size=self.position.size)
            self._reset_state()
            return

        # Runner trailing stop (only after all 3 partials taken)
        if self.partials_taken >= 3:
            if self.entry_atr and self.entry_atr > 0:
                trail_distance = self.entry_atr * self.p.atr_trailing_mult
            else:
                trail_distance = self.entry_price * (self.p.trailing_pct / 100)
            trail_stop = self.high_water_mark - trail_distance
            effective_stop = max(self.current_stop, trail_stop)
            if current_price <= effective_stop:
                pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
                r_mult = self.risk_mgr.calculate_r_multiple(
                    self.entry_price, current_price, self.stop_distance, 'long')
                print(f"[{dt}] LONG RUNNER TRAIL @ {current_price:.4f} "
                      f"({pnl_pct:+.1f}%, {r_mult:+.1f}R) | HWM: {self.high_water_mark:.4f}")
                self.sell(size=self.position.size)
                self._reset_state()

    def _check_short_exits(self):
        """Check exits for short position."""
        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        self.low_water_mark = min(self.low_water_mark, current_price)

        # Check R-target partials (for shorts, target is BELOW entry)
        for i, (r_mult, fraction) in enumerate(self.risk_mgr.partial_schedule):
            if self.partials_taken > i:
                continue
            target_price = self.r_targets.get(r_mult)
            if target_price and current_price <= target_price:
                partial_size = self.initial_size * fraction
                if partial_size > abs(self.position.size):
                    partial_size = abs(self.position.size)
                if partial_size > 0:
                    self.partials_taken = i + 1
                    self.current_stop = self.risk_mgr.get_stop_for_level(
                        self.entry_price, self.stop_distance, self.partials_taken, 'short')
                    print(f"[{dt}] SHORT PARTIAL {self.partials_taken}/3 @ {current_price:.4f} "
                          f"(+{r_mult:.0f}R, buying {fraction:.0%}) | "
                          f"New stop: {self.current_stop:.4f}")
                    self.buy(size=partial_size)
                    return

        # Check stop loss (ratcheted) — for shorts, stop is ABOVE entry
        if current_price >= self.current_stop:
            pnl_pct = (self.entry_price - current_price) / self.entry_price * 100
            r_mult = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'short')
            reason = "SHORT STOP" if self.partials_taken == 0 else f"SHORT RATCHET STOP (after {self.partials_taken}R)"
            print(f"[{dt}] {reason} @ {current_price:.4f} ({pnl_pct:+.1f}%, {r_mult:+.1f}R)")
            self.buy(size=abs(self.position.size))
            self._reset_state()
            return

        # Runner trailing stop (only after all 3 partials taken)
        if self.partials_taken >= 3:
            if self.entry_atr and self.entry_atr > 0:
                trail_distance = self.entry_atr * self.p.atr_trailing_mult
            else:
                trail_distance = self.entry_price * (self.p.trailing_pct / 100)
            trail_stop = self.low_water_mark + trail_distance
            # Use the lower of ratchet stop and trail stop (for shorts, lower = tighter)
            effective_stop = min(self.current_stop, trail_stop)
            if current_price >= effective_stop:
                pnl_pct = (self.entry_price - current_price) / self.entry_price * 100
                r_mult = self.risk_mgr.calculate_r_multiple(
                    self.entry_price, current_price, self.stop_distance, 'short')
                print(f"[{dt}] SHORT RUNNER TRAIL @ {current_price:.4f} "
                      f"({pnl_pct:+.1f}%, {r_mult:+.1f}R) | LWM: {self.low_water_mark:.4f}")
                self.buy(size=abs(self.position.size))
                self._reset_state()

    def _reset_state(self):
        """Reset all state after exit."""
        self.position_type = None
        self.drop_detected = False
        self.pump_detected = False
        self.rise_window_data = []
        self.decline_window_data = []
        self.high_water_mark = None
        self.low_water_mark = None
        self.entry_price = None
        self.entry_atr = None
        self.stop_distance = None
        self.r_targets = {}
        self.current_stop = None
        self.partials_taken = 0
        self.initial_size = 0
