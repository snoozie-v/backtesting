# strategies/sol_strategy_v13.py
"""
SolStrategy v13 - Trend Momentum Rider
--------------------------------------
Designed to capture BIGGER trend moves (unlike V12's tight 0.5% TP).

Core Concept:
- Trade WITH the 4H trend (EMA crossover)
- Use VOLUME as primary entry filter (not extreme RSI)
- ATR-based trailing stops to let winners run
- OBV confirmation for trend strength
- Partial profit taking at key levels

Key Differences from V12:
- V12: 0.5% TP, 6% SL, RSI 29/72 (extreme) -> High win rate, small gains
- V13: ATR trailing stop, RSI 45/55 (lenient), volume filter -> Lower win rate, bigger gains

Data feeds (expected index order):
  0 -> 15m (base, entries and exits)
  1 -> 1h (unused)
  2 -> 4h (trend detection, ATR, OBV)
  3 -> weekly (unused)
  4 -> daily (unused)
"""

import backtrader as bt
import backtrader.indicators as btind


class OBV(bt.Indicator):
    """On-Balance Volume indicator (custom implementation)."""
    lines = ('obv',)
    params = ()

    def __init__(self):
        self.addminperiod(2)

    def next(self):
        if len(self) == 1:
            self.lines.obv[0] = self.data.volume[0]
        else:
            if self.data.close[0] > self.data.close[-1]:
                self.lines.obv[0] = self.lines.obv[-1] + self.data.volume[0]
            elif self.data.close[0] < self.data.close[-1]:
                self.lines.obv[0] = self.lines.obv[-1] - self.data.volume[0]
            else:
                self.lines.obv[0] = self.lines.obv[-1]


class SolStrategyV13(bt.Strategy):
    params = (
        # Trend detection (4H)
        ('ema_fast', 8),              # Fast EMA for trend
        ('ema_slow', 21),             # Slow EMA for trend
        ('trend_strength_min', 0.5),  # Min % difference between EMAs (lowered for more signals)

        # Volume entry confirmation
        ('vol_sma_period', 20),       # Period for volume SMA
        ('vol_expansion_mult', 1.3),  # Entry requires volume > 1.3x average
        ('require_volume_confirm', True),

        # OBV confirmation
        ('use_obv_filter', False),    # Disabled - was blocking long entries
        ('obv_ema_period', 10),       # EMA period for OBV

        # RSI (very lenient - just avoid extremes)
        ('rsi_period', 14),
        ('rsi_oversold', 30),         # Allow longs unless deeply oversold
        ('rsi_overbought', 70),       # Allow shorts unless deeply overbought

        # Pullback (optional, disabled by default)
        ('use_pullback_filter', False),
        ('pullback_pct', 0.5),        # Only 0.5% if enabled (V12: 1.25%)

        # ATR-based stops (let winners run)
        ('atr_period', 14),
        ('atr_trailing_mult', 2.5),   # Trailing stop = HWM +/- (ATR * mult)
        ('atr_initial_mult', 1.5),    # Initial stop = entry +/- (ATR * mult)

        # Fallback fixed stops (if ATR unavailable)
        ('trailing_pct', 4.0),
        ('initial_stop_pct', 3.0),

        # Take profit (disabled by default - use trailing)
        ('use_fixed_tp', False),
        ('fixed_tp_pct', 8.0),

        # Partial profit taking
        ('use_partial_profits', True),
        ('partial_target_atr_mult', 3.0),  # Take partial at 3x ATR gain
        ('partial_sell_ratio', 0.33),      # Sell 33% at partial target

        # Volume-based exit
        ('use_volume_exit', True),
        ('vol_climax_mult', 2.5),     # Volume spike threshold
        ('price_stall_pct', 0.3),     # Price stall threshold

        # Position sizing
        ('risk_pct', 2.0),
        ('position_pct', 90.0),

        # Cooldown
        ('cooldown_bars', 8),         # 15m bars between trades
    )

    def __init__(self):
        # Data feeds
        self.data15 = self.datas[0]   # 15m
        self.data4h = self.datas[2]   # 4h

        # 4H Trend indicators
        self.ema_fast_4h = btind.EMA(self.data4h.close, period=self.p.ema_fast)
        self.ema_slow_4h = btind.EMA(self.data4h.close, period=self.p.ema_slow)

        # Volume indicators
        self.vol_sma_15m = btind.SMA(self.data15.volume, period=self.p.vol_sma_period)
        self.vol_sma_4h = btind.SMA(self.data4h.volume, period=self.p.vol_sma_period)

        # OBV indicator (custom implementation)
        self.obv_4h = OBV(self.data4h)
        self.obv_ema = btind.EMA(self.obv_4h.obv, period=self.p.obv_ema_period)

        # ATR for dynamic stops
        self.atr_4h = btind.ATR(self.data4h, period=self.p.atr_period)

        # RSI (lenient filter)
        self.rsi_15m = btind.RSI(self.data15.close, period=self.p.rsi_period)

        # Track recent high/low for optional pullback detection
        self.recent_high = btind.Highest(self.data15.high, period=12)
        self.recent_low = btind.Lowest(self.data15.low, period=12)

        # Position tracking
        self.entry_price = None
        self.position_type = None
        self.entry_atr = None
        self.initial_stop = None
        self.high_water_mark = None
        self.low_water_mark = None
        self.partial_taken = False
        self.position_size = None

        # Bar tracking
        self.last_trade_bar = -999
        self.last_15m_len = 0

    def next(self):
        # Need enough data for indicators
        if len(self.data4h) < max(self.p.ema_slow, self.p.atr_period, self.p.obv_ema_period) + 1:
            return
        if len(self.data15) < max(self.p.rsi_period, self.p.vol_sma_period) + 12:
            return

        # If in position, check exits
        if self.position and self.position_type is not None:
            self._check_exits()
            return

        # Only check entries on new 15m bar
        if len(self.data15) == self.last_15m_len:
            return
        self.last_15m_len = len(self.data15)

        # Check cooldown
        if len(self.data15) - self.last_trade_bar < self.p.cooldown_bars:
            return

        # Determine 4H trend
        trend = self._get_trend()
        if trend is None:
            return

        # Check entry conditions
        self._check_entry(trend)

    def _get_trend(self):
        """
        Determine 4H trend based on EMA crossover and strength.
        Returns 'up', 'down', or None.
        """
        ema_fast = self.ema_fast_4h[0]
        ema_slow = self.ema_slow_4h[0]

        if ema_slow == 0:
            return None

        diff_pct = ((ema_fast - ema_slow) / ema_slow) * 100

        if diff_pct > self.p.trend_strength_min:
            return 'up'
        elif diff_pct < -self.p.trend_strength_min:
            return 'down'

        return None

    def _volume_confirms_entry(self):
        """Check if volume confirms the entry."""
        if not self.p.require_volume_confirm:
            return True

        current_vol = self.data15.volume[0]
        avg_vol = self.vol_sma_15m[0]

        if avg_vol == 0:
            return True

        return current_vol >= avg_vol * self.p.vol_expansion_mult

    def _obv_confirms_trend(self, direction):
        """Check if OBV confirms trend direction."""
        if not self.p.use_obv_filter:
            return True

        obv_above_ema = self.obv_4h.obv[0] > self.obv_ema[0]

        if direction == 'up':
            return obv_above_ema
        else:
            return not obv_above_ema

    def _price_pulled_back(self, trend, current_price):
        """Check if price has pulled back (optional filter)."""
        if not self.p.use_pullback_filter:
            return True

        if trend == 'up':
            pullback_threshold = self.recent_high[0] * (1 - self.p.pullback_pct / 100)
            return current_price <= pullback_threshold
        else:
            rally_threshold = self.recent_low[0] * (1 + self.p.pullback_pct / 100)
            return current_price >= rally_threshold

    def _check_entry(self, trend):
        """Check for entry signals - less restrictive than V12."""
        current_price = self.data15.close[0]
        rsi = self.rsi_15m[0]

        # 1. RSI filter (lenient - just avoid extremes against trend)
        if trend == 'up' and rsi > self.p.rsi_overbought:
            return  # Don't buy when already overbought
        if trend == 'down' and rsi < self.p.rsi_oversold:
            return  # Don't short when already oversold

        # 2. Optional pullback filter
        if not self._price_pulled_back(trend, current_price):
            return

        # 3. Volume confirmation (THE KEY FILTER)
        if not self._volume_confirms_entry():
            return

        # 4. OBV trend confirmation
        if not self._obv_confirms_trend(trend):
            return

        # 5. Execute entry
        if trend == 'up':
            self._enter_long(current_price)
        else:
            self._enter_short(current_price)

    def _enter_long(self, price):
        """Enter long position with ATR-based stops."""
        # Get ATR for stop calculation
        self.entry_atr = self.atr_4h[0] if self.atr_4h[0] > 0 else None

        # Calculate initial stop
        if self.entry_atr:
            self.initial_stop = price - (self.entry_atr * self.p.atr_initial_mult)
        else:
            self.initial_stop = price * (1 - self.p.initial_stop_pct / 100)

        # Position sizing
        equity = self.broker.getvalue()
        cash = self.broker.get_cash()
        size = min(
            (equity * self.p.position_pct / 100) / price,
            cash * 0.99 / price
        )

        if size <= 0:
            return

        self.buy(size=size)
        self.entry_price = price
        self.position_type = 'long'
        self.high_water_mark = price
        self.partial_taken = False
        self.position_size = size
        self.last_trade_bar = len(self.data15)

        # Calculate display values
        vol_ratio = self.data15.volume[0] / self.vol_sma_15m[0] if self.vol_sma_15m[0] > 0 else 0
        obv_status = "BULL" if self.obv_4h.obv[0] > self.obv_ema[0] else "BEAR"

        dt = self.data15.datetime.datetime(0)
        atr_str = f"{self.entry_atr:.2f}" if self.entry_atr else "N/A"
        print(f"[{dt}] LONG @ {price:.2f} | "
              f"ATR: {atr_str} | "
              f"Init SL: {self.initial_stop:.2f} | "
              f"Vol: {vol_ratio:.1f}x | OBV: {obv_status} | RSI: {self.rsi_15m[0]:.1f}")

    def _enter_short(self, price):
        """Enter short position with ATR-based stops."""
        # Get ATR for stop calculation
        self.entry_atr = self.atr_4h[0] if self.atr_4h[0] > 0 else None

        # Calculate initial stop
        if self.entry_atr:
            self.initial_stop = price + (self.entry_atr * self.p.atr_initial_mult)
        else:
            self.initial_stop = price * (1 + self.p.initial_stop_pct / 100)

        # Position sizing
        equity = self.broker.getvalue()
        cash = self.broker.get_cash()
        size = min(
            (equity * self.p.position_pct / 100) / price,
            cash * 0.99 / price
        )

        if size <= 0:
            return

        self.sell(size=size)
        self.entry_price = price
        self.position_type = 'short'
        self.low_water_mark = price
        self.partial_taken = False
        self.position_size = size
        self.last_trade_bar = len(self.data15)

        # Calculate display values
        vol_ratio = self.data15.volume[0] / self.vol_sma_15m[0] if self.vol_sma_15m[0] > 0 else 0
        obv_status = "BULL" if self.obv_4h.obv[0] > self.obv_ema[0] else "BEAR"

        dt = self.data15.datetime.datetime(0)
        atr_str = f"{self.entry_atr:.2f}" if self.entry_atr else "N/A"
        print(f"[{dt}] SHORT @ {price:.2f} | "
              f"ATR: {atr_str} | "
              f"Init SL: {self.initial_stop:.2f} | "
              f"Vol: {vol_ratio:.1f}x | OBV: {obv_status} | RSI: {self.rsi_15m[0]:.1f}")

    def _check_exits(self):
        """Check all exit conditions with ATR trailing stops."""
        if self.entry_price is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        # Update high/low water marks
        if self.position_type == 'long':
            self.high_water_mark = max(self.high_water_mark, current_price)
        else:
            self.low_water_mark = min(self.low_water_mark, current_price)

        # Calculate ATR-based trailing stop
        if self.entry_atr and self.entry_atr > 0:
            trailing_distance = self.entry_atr * self.p.atr_trailing_mult
        else:
            trailing_distance = self.entry_price * self.p.trailing_pct / 100

        # Calculate active stop level
        if self.position_type == 'long':
            trailing_stop = self.high_water_mark - trailing_distance
            active_stop = max(trailing_stop, self.initial_stop)

            # Check fixed TP if enabled
            if self.p.use_fixed_tp:
                tp_price = self.entry_price * (1 + self.p.fixed_tp_pct / 100)
                if current_price >= tp_price:
                    pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                    print(f"[{dt}] LONG TP HIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                    self.close()
                    self._reset()
                    return

            # Check partial profit
            if self.p.use_partial_profits and not self.partial_taken:
                if self.entry_atr:
                    partial_target = self.entry_price + (self.entry_atr * self.p.partial_target_atr_mult)
                else:
                    partial_target = self.entry_price * (1 + self.p.fixed_tp_pct / 200)  # Half of full TP

                if current_price >= partial_target:
                    self._take_partial_profit(current_price, 'long')
                    # Move stop to breakeven after partial
                    self.initial_stop = max(self.initial_stop, self.entry_price)
                    active_stop = max(active_stop, self.entry_price)

            # Check volume climax exit
            if self.p.use_volume_exit and self._volume_climax_detected():
                # Tighten stop significantly
                active_stop = max(active_stop, current_price * 0.99)

            # Check stop hit
            if current_price <= active_stop:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                exit_type = "TRAILING STOP" if active_stop > self.initial_stop else "INITIAL STOP"
                print(f"[{dt}] LONG {exit_type} @ {current_price:.2f} ({pnl_pct:+.2f}%) | "
                      f"HWM: {self.high_water_mark:.2f}")
                self.close()
                self._reset()
                return

        elif self.position_type == 'short':
            trailing_stop = self.low_water_mark + trailing_distance
            active_stop = min(trailing_stop, self.initial_stop)

            # Check fixed TP if enabled
            if self.p.use_fixed_tp:
                tp_price = self.entry_price * (1 - self.p.fixed_tp_pct / 100)
                if current_price <= tp_price:
                    pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                    print(f"[{dt}] SHORT TP HIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                    self.close()
                    self._reset()
                    return

            # Check partial profit
            if self.p.use_partial_profits and not self.partial_taken:
                if self.entry_atr:
                    partial_target = self.entry_price - (self.entry_atr * self.p.partial_target_atr_mult)
                else:
                    partial_target = self.entry_price * (1 - self.p.fixed_tp_pct / 200)

                if current_price <= partial_target:
                    self._take_partial_profit(current_price, 'short')
                    # Move stop to breakeven after partial
                    self.initial_stop = min(self.initial_stop, self.entry_price)
                    active_stop = min(active_stop, self.entry_price)

            # Check volume climax exit
            if self.p.use_volume_exit and self._volume_climax_detected():
                # Tighten stop significantly
                active_stop = min(active_stop, current_price * 1.01)

            # Check stop hit
            if current_price >= active_stop:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                exit_type = "TRAILING STOP" if active_stop < self.initial_stop else "INITIAL STOP"
                print(f"[{dt}] SHORT {exit_type} @ {current_price:.2f} ({pnl_pct:+.2f}%) | "
                      f"LWM: {self.low_water_mark:.2f}")
                self.close()
                self._reset()
                return

    def _volume_climax_detected(self):
        """Detect volume climax that may signal reversal."""
        if not self.p.use_volume_exit:
            return False

        current_vol = self.data15.volume[0]
        avg_vol = self.vol_sma_15m[0]

        if avg_vol == 0:
            return False

        # Check for volume spike
        if current_vol > avg_vol * self.p.vol_climax_mult:
            # Check if price stalled despite big volume
            if len(self.data15) > 1:
                price_change_pct = abs(
                    (self.data15.close[0] - self.data15.close[-1]) / self.data15.close[-1] * 100
                )
                if price_change_pct < self.p.price_stall_pct:
                    return True

        return False

    def _take_partial_profit(self, current_price, direction):
        """Take partial profit."""
        if self.partial_taken or self.position_size is None:
            return

        partial_size = self.position_size * self.p.partial_sell_ratio

        if direction == 'long':
            self.sell(size=partial_size)
            pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
        else:
            self.buy(size=partial_size)
            pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100

        self.partial_taken = True
        self.position_size = self.position_size - partial_size

        dt = self.data15.datetime.datetime(0)
        print(f"[{dt}] PARTIAL PROFIT ({self.p.partial_sell_ratio*100:.0f}%) @ {current_price:.2f} "
              f"({pnl_pct:+.2f}%)")

    def _reset(self):
        """Reset position tracking."""
        self.entry_price = None
        self.position_type = None
        self.entry_atr = None
        self.initial_stop = None
        self.high_water_mark = None
        self.low_water_mark = None
        self.partial_taken = False
        self.position_size = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = "BUY" if order.isbuy() else "SELL"
            print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: {trade.pnlcomm:.2f}")
