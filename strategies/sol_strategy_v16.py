# strategies/sol_strategy_v16.py
"""
SolStrategy v16 - Trend Exhaustion Catcher (Counter-Trend Complement to V15)
-----------------------------------------------------------------------------
V16 enters BEFORE the 4H trend flips by detecting exhaustion signals.
Where V15 goes quiet (deadzone/flat), V16 activates.

Core Concept:
- Detects when a 4H trend is losing momentum (EMAs converging)
- Enters early — trading INTO the flat zone — confirmed by 1H counter-trend signal

Entry Type A - Convergence + 1H Counter-Cross (Primary):
  Long: 4H downtrend + EMAs narrowing >= 3 bars + gap <= 0.8% + 1H bullish cross + volume
  Short: 4H uptrend + EMAs narrowing >= 3 bars + gap <= 0.8% + 1H bearish cross + volume

Entry Type B - RSI Divergence + Rejection Candle (Secondary):
  Long: 4H downtrend/flat + bullish RSI divergence + 1H bullish rejection candle + volume
  Short: 4H uptrend/flat + bearish RSI divergence + 1H bearish rejection candle + volume

Exit Rules (checked every 15M):
  1. Take Profit: ATR(14) on 1H * tp_multiplier (default 2.5)
  2. Stop Loss: ATR(14) on 1H * stop_multiplier (default 2.0)
  3. Breakeven: Move SL to entry at +1R
  4. Trailing: Move SL to +1R at +2R
  5. Trend Re-Strengthening: 4H gap widens 10%+ after entry
  6. Time Exit: 36 bars (1H)
  7. Daily Loss Limit (same as V15)

Data feeds (expected index order):
  0 -> 15m (base, exit checking)
  1 -> 1h (entries, indicators)
  2 -> 4h (trend detection)
  3 -> weekly (unused)
  4 -> daily (unused)
"""

import backtrader as bt
import backtrader.indicators as btind


class SolStrategyV16(bt.Strategy):
    params = (
        # 4H Trend EMAs
        ('ema_fast_4h_period', 9),
        ('ema_slow_4h_period', 21),
        ('trend_deadzone_pct', 0.1),

        # 1H Entry EMAs
        ('ema_fast_1h_period', 9),
        ('ema_slow_1h_period', 21),

        # Convergence entry params (Type A)
        ('min_convergence_bars', 3),
        ('max_gap_pct', 0.8),

        # RSI divergence entry params (Type B)
        ('rsi_period_4h', 14),
        ('divergence_lookback', 5),
        ('rejection_wick_ratio', 0.6),

        # Volume confirmation
        ('vol_sma_period', 20),
        ('vol_spike_mult', 1.0),

        # ATR-based stops (on 1H)
        ('atr_period', 14),
        ('stop_multiplier', 2.0),
        ('tp_multiplier', 2.5),

        # Exit controls
        ('trend_strengthen_exit_pct', 10.0),
        ('max_hold_bars', 36),

        # Risk-based position sizing
        ('risk_per_trade_pct', 1.0),

        # Cooldown (in 1H bars)
        ('cooldown_bars', 6),
    )

    def __init__(self):
        # Data feeds
        self.data15 = self.datas[0]   # 15m: exit checking
        self.data1h = self.datas[1]   # 1h: entry signals
        self.data4h = self.datas[2]   # 4h: trend detection

        # 4H Trend EMAs
        self.ema_fast_4h = btind.EMA(self.data4h.close, period=self.p.ema_fast_4h_period)
        self.ema_slow_4h = btind.EMA(self.data4h.close, period=self.p.ema_slow_4h_period)

        # 4H RSI for divergence detection
        self.rsi_4h = btind.RSI(self.data4h.close, period=self.p.rsi_period_4h)

        # 1H Entry EMAs
        self.ema_fast_1h = btind.EMA(self.data1h.close, period=self.p.ema_fast_1h_period)
        self.ema_slow_1h = btind.EMA(self.data1h.close, period=self.p.ema_slow_1h_period)

        # 1H Crossover signal
        self.crossover_1h = btind.CrossOver(self.ema_fast_1h, self.ema_slow_1h)

        # 1H Volume
        self.vol_sma_1h = btind.SMA(self.data1h.volume, period=self.p.vol_sma_period)

        # 1H ATR for stops
        self.atr_1h = btind.ATR(self.data1h, period=self.p.atr_period)

        # Position tracking
        self.entry_price = None
        self.position_type = None   # 'long' or 'short'
        self.entry_type = None      # 'convergence' or 'divergence'
        self.stop_loss = None
        self.take_profit = None
        self.entry_bar_1h = None    # 1H bar count at entry (for time exit)
        self.entry_gap_pct = None   # 4H EMA gap % at entry (for trend-strengthening exit)
        self.breakeven_triggered = False
        self.trailing_triggered = False

        # Bar tracking for new-bar detection
        self.last_1h_len = 0
        self.last_4h_len = 0

        # Convergence streak tracking
        self.prev_gap = None
        self.convergence_streak = 0

        # Cooldown tracking (in 1H bars)
        self.last_trade_1h_bar = -999

    def next(self):
        # Need enough data on all timeframes
        min_4h_bars = max(self.p.ema_slow_4h_period, self.p.rsi_period_4h, self.p.divergence_lookback) + 2
        if len(self.data4h) < min_4h_bars:
            return
        if len(self.data1h) < max(self.p.ema_slow_1h_period, self.p.atr_period, self.p.vol_sma_period) + 1:
            return

        # Update convergence streak on new 4H bar
        if len(self.data4h) != self.last_4h_len:
            self.last_4h_len = len(self.data4h)
            self._update_convergence_streak()

        # Determine 4H trend with deadzone
        ema_fast_val = self.ema_fast_4h[0]
        ema_slow_val = self.ema_slow_4h[0]
        deadzone = ema_slow_val * (self.p.trend_deadzone_pct / 100)

        uptrend_4h = ema_fast_val > (ema_slow_val + deadzone)
        downtrend_4h = ema_fast_val < (ema_slow_val - deadzone)

        # Current gap %
        current_gap_pct = abs(ema_fast_val - ema_slow_val) / ema_slow_val * 100 if ema_slow_val > 0 else 999

        # If in position, check exits on every 15M bar
        if self.position:
            self._check_exits(uptrend_4h, downtrend_4h, current_gap_pct)
            return

        # Only check entries on new 1H bar
        if len(self.data1h) == self.last_1h_len:
            return
        self.last_1h_len = len(self.data1h)

        # Check cooldown (in 1H bars)
        if len(self.data1h) - self.last_trade_1h_bar < self.p.cooldown_bars:
            return

        # Check entry conditions
        self._check_entries(uptrend_4h, downtrend_4h, current_gap_pct)

    def _update_convergence_streak(self):
        """Update the count of consecutive 4H bars where EMA gap has been narrowing."""
        ema_fast_val = self.ema_fast_4h[0]
        ema_slow_val = self.ema_slow_4h[0]
        current_gap = abs(ema_fast_val - ema_slow_val)

        if self.prev_gap is not None:
            if current_gap < self.prev_gap:
                self.convergence_streak += 1
            else:
                self.convergence_streak = 0
        self.prev_gap = current_gap

    def _check_entries(self, uptrend_4h, downtrend_4h, current_gap_pct):
        """Check for convergence and divergence entry signals on 1H."""
        # Volume confirmation
        high_volume = True
        if self.vol_sma_1h[0] > 0:
            high_volume = self.data1h.volume[0] >= self.vol_sma_1h[0] * self.p.vol_spike_mult
        else:
            high_volume = False

        if not high_volume:
            return

        atr = self.atr_1h[0]
        if atr <= 0:
            return

        # Entry Type A: Convergence + 1H Counter-Cross (priority)
        if self._check_convergence_entry(uptrend_4h, downtrend_4h, current_gap_pct, atr):
            return

        # Entry Type B: RSI Divergence + Rejection Candle
        self._check_divergence_entry(uptrend_4h, downtrend_4h, atr)

    def _check_convergence_entry(self, uptrend_4h, downtrend_4h, current_gap_pct, atr):
        """
        Entry Type A: EMAs converging + 1H counter-trend cross.
        Long: 4H downtrend + narrowing EMAs + gap small enough + 1H bullish cross
        Short: 4H uptrend + narrowing EMAs + gap small enough + 1H bearish cross
        Returns True if an entry was made.
        """
        # Check convergence conditions
        converging = (self.convergence_streak >= self.p.min_convergence_bars and
                      current_gap_pct <= self.p.max_gap_pct)

        if not converging:
            return False

        # Long reversal: 4H downtrend exhausting + 1H bullish cross (counter-trend)
        if self.crossover_1h[0] > 0 and downtrend_4h:
            self._enter_long(self.data1h.close[0], atr, 'convergence', current_gap_pct)
            return True

        # Short reversal: 4H uptrend exhausting + 1H bearish cross (counter-trend)
        if self.crossover_1h[0] < 0 and uptrend_4h:
            self._enter_short(self.data1h.close[0], atr, 'convergence', current_gap_pct)
            return True

        return False

    def _check_divergence_entry(self, uptrend_4h, downtrend_4h, atr):
        """
        Entry Type B: RSI divergence on 4H + rejection candle on 1H.
        Long: 4H downtrend/flat + bullish RSI divergence + bullish rejection candle
        Short: 4H uptrend/flat + bearish RSI divergence + bearish rejection candle
        """
        lookback = self.p.divergence_lookback

        # Need enough bars for divergence lookback
        if len(self.data4h) < lookback + 1:
            return False

        # Check for bullish divergence: price lower low, RSI higher low
        # Long reversal (bearish exhaustion)
        if downtrend_4h or (not uptrend_4h and not downtrend_4h):
            if self._bullish_rsi_divergence(lookback):
                if self._bullish_rejection_candle():
                    self._enter_long(self.data1h.close[0], atr, 'divergence', None)
                    return True

        # Check for bearish divergence: price higher high, RSI lower high
        # Short reversal (bullish exhaustion)
        if uptrend_4h or (not uptrend_4h and not downtrend_4h):
            if self._bearish_rsi_divergence(lookback):
                if self._bearish_rejection_candle():
                    self._enter_short(self.data1h.close[0], atr, 'divergence', None)
                    return True

        return False

    def _bullish_rsi_divergence(self, lookback):
        """
        Bullish RSI divergence on 4H: price making lower low, RSI making higher low.
        Compare current bar vs lookback bars ago.
        """
        try:
            current_price_low = self.data4h.low[0]
            past_price_low = self.data4h.low[-lookback]
            current_rsi = self.rsi_4h[0]
            past_rsi = self.rsi_4h[-lookback]

            # Price lower low but RSI higher low
            return current_price_low < past_price_low and current_rsi > past_rsi
        except (IndexError, KeyError):
            return False

    def _bearish_rsi_divergence(self, lookback):
        """
        Bearish RSI divergence on 4H: price making higher high, RSI making lower high.
        Compare current bar vs lookback bars ago.
        """
        try:
            current_price_high = self.data4h.high[0]
            past_price_high = self.data4h.high[-lookback]
            current_rsi = self.rsi_4h[0]
            past_rsi = self.rsi_4h[-lookback]

            # Price higher high but RSI lower high
            return current_price_high > past_price_high and current_rsi < past_rsi
        except (IndexError, KeyError):
            return False

    def _bullish_rejection_candle(self):
        """
        Bullish rejection candle on 1H: lower wick >= rejection_wick_ratio of bar range.
        """
        bar_range = self.data1h.high[0] - self.data1h.low[0]
        if bar_range <= 0:
            return False
        lower_wick = min(self.data1h.open[0], self.data1h.close[0]) - self.data1h.low[0]
        return (lower_wick / bar_range) >= self.p.rejection_wick_ratio

    def _bearish_rejection_candle(self):
        """
        Bearish rejection candle on 1H: upper wick >= rejection_wick_ratio of bar range.
        """
        bar_range = self.data1h.high[0] - self.data1h.low[0]
        if bar_range <= 0:
            return False
        upper_wick = self.data1h.high[0] - max(self.data1h.open[0], self.data1h.close[0])
        return (upper_wick / bar_range) >= self.p.rejection_wick_ratio

    def _calculate_position_size(self, entry_price, stop_loss):
        """
        Risk-based position sizing for 100X leverage.
        Risk X% of capital per trade. Position size = risk_amount / stop_distance.
        """
        equity = self.broker.getvalue()
        risk_amount = equity * (self.p.risk_per_trade_pct / 100)
        stop_distance = abs(entry_price - stop_loss)

        if stop_distance <= 0:
            return 0

        size = risk_amount / stop_distance

        # Ensure we have enough cash (margin for leveraged position)
        cash = self.broker.get_cash()
        max_affordable = cash * 0.99 / entry_price
        size = min(size, max_affordable)

        return size

    def _enter_long(self, price, atr, entry_type, gap_pct):
        """Enter long position with ATR-based TP/SL and risk-based sizing."""
        self.stop_loss = price - (atr * self.p.stop_multiplier)
        self.take_profit = price + (atr * self.p.tp_multiplier)

        size = self._calculate_position_size(price, self.stop_loss)
        if size <= 0:
            return

        self.buy(size=size)
        self.entry_price = price
        self.position_type = 'long'
        self.entry_type = entry_type
        self.entry_bar_1h = len(self.data1h)
        self.last_trade_1h_bar = len(self.data1h)
        self.entry_gap_pct = gap_pct
        self.breakeven_triggered = False
        self.trailing_triggered = False

        dt = self.data1h.datetime.datetime(0)
        vol_ratio = self.data1h.volume[0] / self.vol_sma_1h[0] if self.vol_sma_1h[0] > 0 else 0
        gap_str = f" | Gap: {gap_pct:.2f}%" if gap_pct is not None else ""
        streak_str = f" | Streak: {self.convergence_streak}" if entry_type == 'convergence' else ""
        print(f"[{dt}] LONG ({entry_type.upper()}) @ {price:.2f} | "
              f"SL: {self.stop_loss:.2f} | TP: {self.take_profit:.2f} | "
              f"ATR: {atr:.2f} | Vol: {vol_ratio:.1f}x{gap_str}{streak_str} | Size: {size:.4f}")

    def _enter_short(self, price, atr, entry_type, gap_pct):
        """Enter short position with ATR-based TP/SL and risk-based sizing."""
        self.stop_loss = price + (atr * self.p.stop_multiplier)
        self.take_profit = price - (atr * self.p.tp_multiplier)

        size = self._calculate_position_size(price, self.stop_loss)
        if size <= 0:
            return

        self.sell(size=size)
        self.entry_price = price
        self.position_type = 'short'
        self.entry_type = entry_type
        self.entry_bar_1h = len(self.data1h)
        self.last_trade_1h_bar = len(self.data1h)
        self.entry_gap_pct = gap_pct
        self.breakeven_triggered = False
        self.trailing_triggered = False

        dt = self.data1h.datetime.datetime(0)
        vol_ratio = self.data1h.volume[0] / self.vol_sma_1h[0] if self.vol_sma_1h[0] > 0 else 0
        gap_str = f" | Gap: {gap_pct:.2f}%" if gap_pct is not None else ""
        streak_str = f" | Streak: {self.convergence_streak}" if entry_type == 'convergence' else ""
        print(f"[{dt}] SHORT ({entry_type.upper()}) @ {price:.2f} | "
              f"SL: {self.stop_loss:.2f} | TP: {self.take_profit:.2f} | "
              f"ATR: {atr:.2f} | Vol: {vol_ratio:.1f}x{gap_str}{streak_str} | Size: {size:.4f}")

    def _check_exits(self, uptrend_4h, downtrend_4h, current_gap_pct):
        """Check TP/SL, breakeven, trailing, trend strengthening, and time exits on every 15M bar."""
        if self.entry_price is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)
        atr = self.atr_1h[0]

        # Calculate R distances
        risk_dist = abs(self.entry_price - (self.entry_price - atr * self.p.stop_multiplier)) if self.position_type == 'long' else abs(self.entry_price - (self.entry_price + atr * self.p.stop_multiplier))

        if self.position_type == 'long':
            # Breakeven: move SL to entry at +1R
            one_r = self.entry_price + risk_dist
            two_r = self.entry_price + risk_dist * 2
            if not self.breakeven_triggered and current_price >= one_r:
                self.stop_loss = max(self.stop_loss, self.entry_price)
                self.breakeven_triggered = True
            # Trailing: move SL to +1R at +2R
            if not self.trailing_triggered and current_price >= two_r:
                self.stop_loss = max(self.stop_loss, self.entry_price + risk_dist)
                self.trailing_triggered = True

            # TP
            if current_price >= self.take_profit:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                print(f"[{dt}] LONG TP HIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

            # SL
            if current_price <= self.stop_loss:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                sl_type = "TRAILING SL" if self.trailing_triggered else ("BE SL" if self.breakeven_triggered else "SL")
                print(f"[{dt}] LONG {sl_type} HIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

            # Trend re-strengthening exit (4H gap widening after entry)
            if self.entry_gap_pct is not None and self.entry_gap_pct > 0:
                gap_change_pct = ((current_gap_pct - self.entry_gap_pct) / self.entry_gap_pct) * 100
                if gap_change_pct >= self.p.trend_strengthen_exit_pct and downtrend_4h:
                    pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                    print(f"[{dt}] LONG TREND RE-STRENGTHEN EXIT @ {current_price:.2f} ({pnl_pct:+.2f}%) gap widened {gap_change_pct:.1f}%")
                    self.close()
                    self._reset()
                    return

            # Time exit
            if self.entry_bar_1h is not None and (len(self.data1h) - self.entry_bar_1h) >= self.p.max_hold_bars:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                print(f"[{dt}] LONG TIME EXIT @ {current_price:.2f} ({pnl_pct:+.2f}%) after {self.p.max_hold_bars} bars")
                self.close()
                self._reset()
                return

        elif self.position_type == 'short':
            # Breakeven: move SL to entry at +1R
            one_r = self.entry_price - risk_dist
            two_r = self.entry_price - risk_dist * 2
            if not self.breakeven_triggered and current_price <= one_r:
                self.stop_loss = min(self.stop_loss, self.entry_price)
                self.breakeven_triggered = True
            # Trailing: move SL to +1R at +2R
            if not self.trailing_triggered and current_price <= two_r:
                self.stop_loss = min(self.stop_loss, self.entry_price - risk_dist)
                self.trailing_triggered = True

            # TP
            if current_price <= self.take_profit:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                print(f"[{dt}] SHORT TP HIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

            # SL
            if current_price >= self.stop_loss:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                sl_type = "TRAILING SL" if self.trailing_triggered else ("BE SL" if self.breakeven_triggered else "SL")
                print(f"[{dt}] SHORT {sl_type} HIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

            # Trend re-strengthening exit (4H gap widening after entry)
            if self.entry_gap_pct is not None and self.entry_gap_pct > 0:
                gap_change_pct = ((current_gap_pct - self.entry_gap_pct) / self.entry_gap_pct) * 100
                if gap_change_pct >= self.p.trend_strengthen_exit_pct and uptrend_4h:
                    pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                    print(f"[{dt}] SHORT TREND RE-STRENGTHEN EXIT @ {current_price:.2f} ({pnl_pct:+.2f}%) gap widened {gap_change_pct:.1f}%")
                    self.close()
                    self._reset()
                    return

            # Time exit
            if self.entry_bar_1h is not None and (len(self.data1h) - self.entry_bar_1h) >= self.p.max_hold_bars:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                print(f"[{dt}] SHORT TIME EXIT @ {current_price:.2f} ({pnl_pct:+.2f}%) after {self.p.max_hold_bars} bars")
                self.close()
                self._reset()
                return

    def _reset(self):
        """Reset position tracking."""
        self.entry_price = None
        self.position_type = None
        self.entry_type = None
        self.stop_loss = None
        self.take_profit = None
        self.entry_bar_1h = None
        self.entry_gap_pct = None
        self.breakeven_triggered = False
        self.trailing_triggered = False

    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = "BUY" if order.isbuy() else "SELL"
            print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}")
