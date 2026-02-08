# strategies/sol_strategy_v15.py
"""
SolStrategy v15 - Zone Trader (1-2 Trades/Day for 20-Trade Exercise)
--------------------------------------------------------------------
NOTE: FAILS walk-forward validation. IS: +137%, OOS: -53% (overfit).
Top params by importance: ema_slow_1h_period (41%), trend_deadzone_pct (19%), cooldown_bars (8%).
--------------------------------------------------------------------
Designed for the Mark Douglas "Trading in the Zone" 20-trade exercise.
Targets 0.5-1 trade/day per pair with positive expectancy.

Core Concept:
- 4H trend filter: EMA9/21 with deadzone to avoid choppy markets
- 1H entries: Two entry types (crossover + pullback) for sufficient frequency
- 15M exit checking: TP/SL/trend reversal/time exit checked every 15M bar
- Risk-based position sizing: 1-2% capital risk per trade on 100X leverage

Entry Type A - EMA Crossover (1H):
  Long: 1H EMA9 crosses above EMA21 + 4H uptrend + volume
  Short: 1H EMA9 crosses below EMA21 + 4H downtrend + volume

Entry Type B - EMA Pullback (1H):
  Long: Bar low touches/crosses below EMA9, closes above it, EMA9 > EMA21
  Short: Bar high touches/crosses above EMA9, closes below it, EMA9 < EMA21

Exit Rules (checked every 15M):
  1. Take Profit: ATR(14) on 1H * tp_multiplier
  2. Stop Loss: ATR(14) on 1H * stop_multiplier
  3. Trend Reversal: 4H trend flips against position
  4. Time Exit: max_hold_bars 1H bars elapsed

Data feeds (expected index order):
  0 -> 15m (base, exit checking)
  1 -> 1h (entries, indicators)
  2 -> 4h (trend detection)
  3 -> weekly (unused)
  4 -> daily (unused)
"""

import backtrader as bt
import backtrader.indicators as btind


class SolStrategyV15(bt.Strategy):
    params = (
        # 4H Trend EMAs
        ('ema_fast_4h_period', 9),
        ('ema_slow_4h_period', 21),
        ('trend_deadzone_pct', 0.1),

        # 1H Entry EMAs
        ('ema_fast_1h_period', 9),
        ('ema_slow_1h_period', 21),

        # Entry type toggles
        ('enable_crossover_entry', True),
        ('enable_pullback_entry', True),

        # Volume confirmation
        ('vol_sma_period', 20),
        ('require_volume', True),

        # ATR-based stops (on 1H)
        ('atr_period', 14),
        ('stop_multiplier', 1.5),
        ('tp_multiplier', 3.0),

        # Exit controls
        ('exit_on_trend_reversal', True),
        ('max_hold_bars', 48),

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
        self.entry_type = None      # 'crossover' or 'pullback'
        self.stop_loss = None
        self.take_profit = None
        self.entry_bar_1h = None    # 1H bar count at entry (for time exit)

        # Bar tracking for new-bar detection
        self.last_1h_len = 0
        self.last_15m_len = 0

        # Cooldown tracking (in 1H bars)
        self.last_trade_1h_bar = -999

    def next(self):
        # Need enough data on all timeframes
        if len(self.data4h) < self.p.ema_slow_4h_period + 1:
            return
        if len(self.data1h) < max(self.p.ema_slow_1h_period, self.p.atr_period, self.p.vol_sma_period) + 1:
            return

        # Determine 4H trend with deadzone
        ema_fast_val = self.ema_fast_4h[0]
        ema_slow_val = self.ema_slow_4h[0]
        deadzone = ema_slow_val * (self.p.trend_deadzone_pct / 100)

        uptrend_4h = ema_fast_val > (ema_slow_val + deadzone)
        downtrend_4h = ema_fast_val < (ema_slow_val - deadzone)

        # If in position, check exits on every 15M bar
        if self.position:
            self._check_exits(uptrend_4h, downtrend_4h)
            return

        # Only check entries on new 1H bar
        if len(self.data1h) == self.last_1h_len:
            return
        self.last_1h_len = len(self.data1h)

        # Check cooldown (in 1H bars)
        if len(self.data1h) - self.last_trade_1h_bar < self.p.cooldown_bars:
            return

        # Check entry conditions
        self._check_entries(uptrend_4h, downtrend_4h)

    def _check_entries(self, uptrend_4h, downtrend_4h):
        """Check for crossover and pullback entry signals on 1H."""
        # Volume confirmation
        high_volume = True
        if self.p.require_volume:
            if self.vol_sma_1h[0] > 0:
                high_volume = self.data1h.volume[0] > self.vol_sma_1h[0]
            else:
                high_volume = False

        if not high_volume:
            return

        atr = self.atr_1h[0]
        if atr <= 0:
            return

        # Entry Type A: EMA Crossover
        if self.p.enable_crossover_entry:
            if self._check_crossover_entry(uptrend_4h, downtrend_4h, atr):
                return

        # Entry Type B: EMA Pullback
        if self.p.enable_pullback_entry:
            self._check_pullback_entry(uptrend_4h, downtrend_4h, atr)

    def _check_crossover_entry(self, uptrend_4h, downtrend_4h, atr):
        """
        Entry Type A: 1H EMA crossover aligned with 4H trend.
        Returns True if an entry was made.
        """
        # Long: 1H bullish crossover + 4H uptrend
        if self.crossover_1h[0] > 0 and uptrend_4h:
            self._enter_long(self.data1h.close[0], atr, 'crossover')
            return True

        # Short: 1H bearish crossunder + 4H downtrend
        if self.crossover_1h[0] < 0 and downtrend_4h:
            self._enter_short(self.data1h.close[0], atr, 'crossover')
            return True

        return False

    def _check_pullback_entry(self, uptrend_4h, downtrend_4h, atr):
        """
        Entry Type B: 1H price pulls back to touch fast EMA then closes on the right side.
        Long: bar low <= EMA9, close > EMA9, EMA9 > EMA21 on 1H, 4H uptrend
        Short: bar high >= EMA9, close < EMA9, EMA9 < EMA21 on 1H, 4H downtrend
        """
        ema_fast = self.ema_fast_1h[0]
        ema_slow = self.ema_slow_1h[0]
        bar_low = self.data1h.low[0]
        bar_high = self.data1h.high[0]
        bar_close = self.data1h.close[0]

        # Long pullback: in uptrend, price dips to EMA9 then closes above it
        if uptrend_4h and ema_fast > ema_slow:
            if bar_low <= ema_fast and bar_close > ema_fast:
                self._enter_long(bar_close, atr, 'pullback')
                return True

        # Short pullback: in downtrend, price rallies to EMA9 then closes below it
        if downtrend_4h and ema_fast < ema_slow:
            if bar_high >= ema_fast and bar_close < ema_fast:
                self._enter_short(bar_close, atr, 'pullback')
                return True

        return False

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

    def _enter_long(self, price, atr, entry_type):
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

        dt = self.data1h.datetime.datetime(0)
        vol_ratio = self.data1h.volume[0] / self.vol_sma_1h[0] if self.vol_sma_1h[0] > 0 else 0
        print(f"[{dt}] LONG ({entry_type.upper()}) @ {price:.2f} | "
              f"SL: {self.stop_loss:.2f} | TP: {self.take_profit:.2f} | "
              f"ATR: {atr:.2f} | Vol: {vol_ratio:.1f}x | Size: {size:.4f}")

    def _enter_short(self, price, atr, entry_type):
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

        dt = self.data1h.datetime.datetime(0)
        vol_ratio = self.data1h.volume[0] / self.vol_sma_1h[0] if self.vol_sma_1h[0] > 0 else 0
        print(f"[{dt}] SHORT ({entry_type.upper()}) @ {price:.2f} | "
              f"SL: {self.stop_loss:.2f} | TP: {self.take_profit:.2f} | "
              f"ATR: {atr:.2f} | Vol: {vol_ratio:.1f}x | Size: {size:.4f}")

    def _check_exits(self, uptrend_4h, downtrend_4h):
        """Check TP/SL, trend reversal, and time exits on every 15M bar."""
        if self.entry_price is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        if self.position_type == 'long':
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
                print(f"[{dt}] LONG SL HIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

            # Trend reversal
            if self.p.exit_on_trend_reversal and downtrend_4h:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                print(f"[{dt}] LONG TREND REVERSAL EXIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
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
                print(f"[{dt}] SHORT SL HIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

            # Trend reversal
            if self.p.exit_on_trend_reversal and uptrend_4h:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                print(f"[{dt}] SHORT TREND REVERSAL EXIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
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

    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = "BUY" if order.isbuy() else "SELL"
            print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}")
