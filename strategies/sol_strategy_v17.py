# strategies/sol_strategy_v17.py
"""
SolStrategy v17 - ATR Swing Scalper for Leveraged SOL Trading
-------------------------------------------------------------
NOTE: FAILS walk-forward validation. IS: +16%, OOS: -15% (overfit).
501 IS trades / 228 OOS trades. Too many entry filters + params.
-------------------------------------------------------------
Combines proven elements from v8_fast (ATR exits, partial profits) and
v11 (risk-based sizing, regime adaptivity). All thresholds are ATR-relative
to avoid the fixed-% failure pattern that killed v9, v10, v14, v15, v16.

Core Concept:
- 4H trend filter: ATR-normalized EMA gap (regime-adaptive)
- 1H swing structure: Identifies swing highs/lows for pullback zones
- 15m wick rejection: Pattern-based entry (not indicator crossover)
- Multi-layer ATR exits: TP1 (40% partial) → breakeven → TP2 (30%) → trail

Data feeds (expected index order):
  0 -> 15m (base, entries + exit checking)
  1 -> 1h (swing levels, ATR)
  2 -> 4h (trend filter)
  3 -> weekly (unused)
  4 -> daily (unused)
"""

import backtrader as bt
import backtrader.indicators as btind


class SolStrategyV17(bt.Strategy):
    params = (
        # 4H Trend EMAs (optimizable)
        ('ema_fast_4h', 9),
        ('ema_slow_4h', 21),
        ('trend_threshold', 0.5),

        # 1H Swing detection (optimizable)
        ('swing_lookback', 3),

        # ATR settings (fixed)
        ('atr_period', 14),

        # Stop/TP multipliers (optimizable)
        ('stop_mult', 1.5),
        ('tp1_mult', 1.5),
        ('tp2_mult', 3.0),

        # Risk management (optimizable)
        ('risk_per_trade_pct', 0.5),

        # Entry tuning (optimizable)
        ('wick_ratio', 0.45),
        ('pullback_zone_mult', 1.5),
        ('enable_pullback_entry', True),
        ('ema_15m_period', 5),
        ('ema_fast_1h', 9),

        # Fixed params
        ('partial_ratio_1', 0.40),
        ('partial_ratio_2', 0.30),
        ('trail_mult', 2.0),
        ('cooldown_bars', 4),
        ('max_hold_bars', 24),
        ('max_leverage', 10.0),
        ('max_position_pct', 30.0),
        ('volume_confirm', False),
    )

    def __init__(self):
        # Data feeds
        self.data15 = self.datas[0]   # 15m: entries + exit checking
        self.data1h = self.datas[1]   # 1h: swing levels, ATR
        self.data4h = self.datas[2]   # 4h: trend filter

        # 4H Trend indicators
        self.ema_fast_4h = btind.EMA(self.data4h.close, period=self.p.ema_fast_4h)
        self.ema_slow_4h = btind.EMA(self.data4h.close, period=self.p.ema_slow_4h)
        self.atr_4h = btind.ATR(self.data4h, period=self.p.atr_period)

        # 1H ATR for exits and swing zones
        self.atr_1h = btind.ATR(self.data1h, period=self.p.atr_period)

        # 15M momentum filter
        self.ema_15m = btind.EMA(self.data15.close, period=self.p.ema_15m_period)

        # 1H EMA for pullback entry
        self.ema_fast_1h = btind.EMA(self.data1h.close, period=self.p.ema_fast_1h)

        # Position tracking
        self.entry_price = None
        self.position_type = None       # 'long' or 'short'
        self.entry_atr = None           # 1H ATR at entry (used for all exit calcs)
        self.stop_loss = None
        self.tp1_price = None
        self.tp2_price = None
        self.tp1_taken = False
        self.tp2_taken = False
        self.high_water_mark = None     # For trailing stop
        self.entry_bar_1h = None        # For max hold time
        self.original_size = None       # Track original position size

        # Swing level tracking
        self.swing_highs = []           # List of (bar_index, price)
        self.swing_lows = []            # List of (bar_index, price)

        # Bar tracking
        self.last_1h_len = 0
        self.last_15m_len = 0

        # Cooldown tracking (in 1H bars)
        self.last_trade_1h_bar = -999

    def next(self):
        # Need enough data on all timeframes
        min_4h_bars = max(self.p.ema_slow_4h, self.p.atr_period) + 1
        min_1h_bars = max(self.p.atr_period, self.p.swing_lookback * 2 + 1) + 1

        if len(self.data4h) < min_4h_bars:
            return
        if len(self.data1h) < min_1h_bars:
            return

        # Update swing levels on new 1H bar
        if len(self.data1h) != self.last_1h_len:
            self.last_1h_len = len(self.data1h)
            self._update_swing_levels()

        # Calculate trend score
        trend_score = self._get_trend_score()

        # If in position, check exits on every 15M bar
        if self.position:
            self._check_exits()
            return

        # Only check entries on new 15m bar
        if len(self.data15) == self.last_15m_len:
            return
        self.last_15m_len = len(self.data15)

        # Check cooldown (in 1H bars)
        if len(self.data1h) - self.last_trade_1h_bar < self.p.cooldown_bars:
            return

        # Check entry conditions
        self._check_entries(trend_score)

    def _get_trend_score(self):
        """Calculate ATR-normalized trend score from 4H EMAs."""
        ema_gap = self.ema_fast_4h[0] - self.ema_slow_4h[0]
        atr = self.atr_4h[0]
        if atr <= 0:
            return 0.0
        return ema_gap / atr

    def _update_swing_levels(self):
        """Identify swing highs and lows on 1H timeframe."""
        lb = self.p.swing_lookback

        # Need enough bars to look back
        if len(self.data1h) < lb * 2 + 1:
            return

        # Check for swing high: bar at -lb is higher than all surrounding bars
        is_swing_high = True
        candidate_high = self.data1h.high[-lb]
        for i in range(lb * 2 + 1):
            offset = -(lb * 2) + i
            if offset == -lb:
                continue
            if self.data1h.high[offset] >= candidate_high:
                is_swing_high = False
                break

        if is_swing_high:
            bar_idx = len(self.data1h) - lb
            # Avoid duplicates
            if not self.swing_highs or self.swing_highs[-1][0] != bar_idx:
                self.swing_highs.append((bar_idx, candidate_high))
                # Keep only recent swings
                if len(self.swing_highs) > 20:
                    self.swing_highs = self.swing_highs[-20:]

        # Check for swing low
        is_swing_low = True
        candidate_low = self.data1h.low[-lb]
        for i in range(lb * 2 + 1):
            offset = -(lb * 2) + i
            if offset == -lb:
                continue
            if self.data1h.low[offset] <= candidate_low:
                is_swing_low = False
                break

        if is_swing_low:
            bar_idx = len(self.data1h) - lb
            if not self.swing_lows or self.swing_lows[-1][0] != bar_idx:
                self.swing_lows.append((bar_idx, candidate_low))
                if len(self.swing_lows) > 20:
                    self.swing_lows = self.swing_lows[-20:]

    def _check_entries(self, trend_score):
        """Check for wick rejection and EMA pullback entries."""
        atr_1h = self.atr_1h[0]
        if atr_1h <= 0:
            return

        current_price = self.data15.close[0]
        bar_open = self.data15.open[0]
        bar_high = self.data15.high[0]
        bar_low = self.data15.low[0]
        bar_close = self.data15.close[0]
        bar_range = bar_high - bar_low

        ema_15m = self.ema_15m[0]
        pullback_zone = atr_1h * self.p.pullback_zone_mult

        # --- Entry Type A: Wick rejection near swing levels with 15m momentum ---
        if bar_range > 0:
            # Long entry: trend up, near swing low, bullish wick rejection, 15m momentum
            if trend_score > self.p.trend_threshold:
                nearest_low = self._find_nearest_swing_low(current_price, pullback_zone)
                if nearest_low is not None:
                    lower_wick = min(bar_open, bar_close) - bar_low
                    if (lower_wick / bar_range >= self.p.wick_ratio
                            and bar_close > bar_open
                            and bar_close > ema_15m):
                        self._enter_long(bar_close, atr_1h)
                        return

            # Short entry: trend down, near swing high, bearish wick rejection, 15m momentum
            if trend_score < -self.p.trend_threshold:
                nearest_high = self._find_nearest_swing_high(current_price, pullback_zone)
                if nearest_high is not None:
                    upper_wick = bar_high - max(bar_open, bar_close)
                    if (upper_wick / bar_range >= self.p.wick_ratio
                            and bar_close < bar_open
                            and bar_close < ema_15m):
                        self._enter_short(bar_close, atr_1h)
                        return

        # --- Entry Type B: EMA pullback on 1H aligned with 4H trend ---
        if self.p.enable_pullback_entry:
            self._check_pullback_entry(trend_score, atr_1h)

    def _check_pullback_entry(self, trend_score, atr_1h):
        """
        EMA pullback entry on 1H: price pulls back to touch 1H EMA fast,
        closes on the right side of it, aligned with 4H trend.
        """
        ema_fast = self.ema_fast_1h[0]
        bar_low = self.data1h.low[0]
        bar_high = self.data1h.high[0]
        bar_close = self.data1h.close[0]

        # Long pullback: 4H uptrend, 1H price dips to EMA fast then closes above
        if trend_score > self.p.trend_threshold:
            if bar_low <= ema_fast and bar_close > ema_fast:
                self._enter_long(bar_close, atr_1h)
                return

        # Short pullback: 4H downtrend, 1H price rallies to EMA fast then closes below
        if trend_score < -self.p.trend_threshold:
            if bar_high >= ema_fast and bar_close < ema_fast:
                self._enter_short(bar_close, atr_1h)
                return

    def _find_nearest_swing_low(self, price, zone):
        """Find nearest swing low within pullback zone of current price."""
        for _, level in reversed(self.swing_lows):
            if abs(price - level) <= zone:
                return level
        return None

    def _find_nearest_swing_high(self, price, zone):
        """Find nearest swing high within pullback zone of current price."""
        for _, level in reversed(self.swing_highs):
            if abs(price - level) <= zone:
                return level
        return None

    def _calculate_position_size(self, entry_price, stop_distance):
        """Risk-based position sizing with leverage caps."""
        equity = self.broker.getvalue()
        risk_amount = equity * (self.p.risk_per_trade_pct / 100)

        if stop_distance <= 0:
            return 0

        size = risk_amount / stop_distance

        # Leverage cap
        max_leverage_size = equity * self.p.max_leverage / entry_price
        size = min(size, max_leverage_size)

        # Position cap
        max_position_size = equity * (self.p.max_position_pct / 100) / entry_price
        size = min(size, max_position_size)

        # Cash cap
        cash = self.broker.get_cash()
        max_affordable = cash * 0.99 / entry_price
        size = min(size, max_affordable)

        return size

    def _enter_long(self, price, atr):
        """Enter long with multi-layer ATR exit setup."""
        stop_distance = atr * self.p.stop_mult
        self.stop_loss = price - stop_distance
        self.tp1_price = price + (atr * self.p.tp1_mult)
        self.tp2_price = price + (atr * self.p.tp2_mult)

        size = self._calculate_position_size(price, stop_distance)
        if size <= 0:
            return

        self.buy(size=size)
        self.entry_price = price
        self.position_type = 'long'
        self.entry_atr = atr
        self.tp1_taken = False
        self.tp2_taken = False
        self.high_water_mark = price
        self.entry_bar_1h = len(self.data1h)
        self.last_trade_1h_bar = len(self.data1h)
        self.original_size = size

        dt = self.data15.datetime.datetime(0)
        print(f"[{dt}] LONG @ {price:.2f} | SL: {self.stop_loss:.2f} | "
              f"TP1: {self.tp1_price:.2f} | TP2: {self.tp2_price:.2f} | "
              f"ATR: {atr:.2f} | Size: {size:.4f}")

    def _enter_short(self, price, atr):
        """Enter short with multi-layer ATR exit setup."""
        stop_distance = atr * self.p.stop_mult
        self.stop_loss = price + stop_distance
        self.tp1_price = price - (atr * self.p.tp1_mult)
        self.tp2_price = price - (atr * self.p.tp2_mult)

        size = self._calculate_position_size(price, stop_distance)
        if size <= 0:
            return

        self.sell(size=size)
        self.entry_price = price
        self.position_type = 'short'
        self.entry_atr = atr
        self.tp1_taken = False
        self.tp2_taken = False
        self.high_water_mark = price
        self.entry_bar_1h = len(self.data1h)
        self.last_trade_1h_bar = len(self.data1h)
        self.original_size = size

        dt = self.data15.datetime.datetime(0)
        print(f"[{dt}] SHORT @ {price:.2f} | SL: {self.stop_loss:.2f} | "
              f"TP1: {self.tp1_price:.2f} | TP2: {self.tp2_price:.2f} | "
              f"ATR: {atr:.2f} | Size: {size:.4f}")

    def _check_exits(self):
        """Multi-layer exit logic: SL, TP1 (partial + breakeven), TP2 (partial), trail, max hold."""
        if self.entry_price is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)
        current_size = abs(self.position.size)

        if self.position_type == 'long':
            # Update high water mark
            if current_price > self.high_water_mark:
                self.high_water_mark = current_price

            # 1. Stop loss (full exit)
            if current_price <= self.stop_loss:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                reason = "STOP LOSS" if not self.tp1_taken else "BREAKEVEN STOP"
                print(f"[{dt}] LONG {reason} @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

            # 2. TP1: partial close + move stop to breakeven
            if not self.tp1_taken and current_price >= self.tp1_price:
                partial_size = self.original_size * self.p.partial_ratio_1
                partial_size = min(partial_size, current_size * 0.95)  # Keep some position
                if partial_size > 0:
                    pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                    print(f"[{dt}] LONG TP1 @ {current_price:.2f} ({pnl_pct:+.2f}%) "
                          f"closing {self.p.partial_ratio_1:.0%}, stop → breakeven")
                    self.sell(size=partial_size)
                    self.stop_loss = self.entry_price  # Move stop to breakeven
                    self.tp1_taken = True
                    return

            # 3. TP2: partial close of remaining
            if self.tp1_taken and not self.tp2_taken and current_price >= self.tp2_price:
                partial_size = current_size * self.p.partial_ratio_2 / (1 - self.p.partial_ratio_1)
                partial_size = min(partial_size, current_size * 0.95)
                if partial_size > 0:
                    pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                    print(f"[{dt}] LONG TP2 @ {current_price:.2f} ({pnl_pct:+.2f}%) "
                          f"closing {self.p.partial_ratio_2:.0%} of original")
                    self.sell(size=partial_size)
                    self.tp2_taken = True
                    return

            # 4. Trailing stop (after TP1)
            if self.tp1_taken:
                trail_distance = self.entry_atr * self.p.trail_mult
                trail_stop = self.high_water_mark - trail_distance
                if trail_stop > self.stop_loss:
                    self.stop_loss = trail_stop

            # 5. Max hold time
            if self.entry_bar_1h is not None and (len(self.data1h) - self.entry_bar_1h) >= self.p.max_hold_bars:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                print(f"[{dt}] LONG MAX HOLD EXIT @ {current_price:.2f} ({pnl_pct:+.2f}%) "
                      f"after {self.p.max_hold_bars} 1H bars")
                self.close()
                self._reset()
                return

        elif self.position_type == 'short':
            # Update high water mark (low water mark for shorts)
            if current_price < self.high_water_mark:
                self.high_water_mark = current_price

            # 1. Stop loss (full exit)
            if current_price >= self.stop_loss:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                reason = "STOP LOSS" if not self.tp1_taken else "BREAKEVEN STOP"
                print(f"[{dt}] SHORT {reason} @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

            # 2. TP1: partial close + move stop to breakeven
            if not self.tp1_taken and current_price <= self.tp1_price:
                partial_size = self.original_size * self.p.partial_ratio_1
                partial_size = min(partial_size, current_size * 0.95)
                if partial_size > 0:
                    pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                    print(f"[{dt}] SHORT TP1 @ {current_price:.2f} ({pnl_pct:+.2f}%) "
                          f"closing {self.p.partial_ratio_1:.0%}, stop → breakeven")
                    self.buy(size=partial_size)
                    self.stop_loss = self.entry_price  # Move stop to breakeven
                    self.tp1_taken = True
                    return

            # 3. TP2: partial close of remaining
            if self.tp1_taken and not self.tp2_taken and current_price <= self.tp2_price:
                partial_size = current_size * self.p.partial_ratio_2 / (1 - self.p.partial_ratio_1)
                partial_size = min(partial_size, current_size * 0.95)
                if partial_size > 0:
                    pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                    print(f"[{dt}] SHORT TP2 @ {current_price:.2f} ({pnl_pct:+.2f}%) "
                          f"closing {self.p.partial_ratio_2:.0%} of original")
                    self.buy(size=partial_size)
                    self.tp2_taken = True
                    return

            # 4. Trailing stop (after TP1)
            if self.tp1_taken:
                trail_distance = self.entry_atr * self.p.trail_mult
                trail_stop = self.high_water_mark + trail_distance
                if trail_stop < self.stop_loss:
                    self.stop_loss = trail_stop

            # 5. Max hold time
            if self.entry_bar_1h is not None and (len(self.data1h) - self.entry_bar_1h) >= self.p.max_hold_bars:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                print(f"[{dt}] SHORT MAX HOLD EXIT @ {current_price:.2f} ({pnl_pct:+.2f}%) "
                      f"after {self.p.max_hold_bars} 1H bars")
                self.close()
                self._reset()
                return

    def _reset(self):
        """Reset position tracking."""
        self.entry_price = None
        self.position_type = None
        self.entry_atr = None
        self.stop_loss = None
        self.tp1_price = None
        self.tp2_price = None
        self.tp1_taken = False
        self.tp2_taken = False
        self.high_water_mark = None
        self.entry_bar_1h = None
        self.original_size = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = "BUY" if order.isbuy() else "SELL"
            print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}")
