# strategies/sol_strategy_v12.py
"""
SolStrategy v12 - High Win Rate Trend Scalper
----------------------------------------------
Optimized for WIN RATE, not total return.

Core Concept:
- Only trade WITH the 4H trend (no counter-trend trades)
- Take quick profits (tight TP)
- Give trades room with wider stops
- Use momentum confirmation (RSI)

The math for high win rate:
- Tight TP = more likely to hit before reversal
- Wide SL = less likely to get stopped out on noise
- Trading with trend = higher base probability

Data feeds (expected index order):
  0 → 15m (base, entries and exits)
  1 → 1h (unused)
  2 → 4h (trend detection)
  3 → weekly (unused)
  4 → daily (unused)
"""

import backtrader as bt
import backtrader.indicators as btind


class SolStrategyV12(bt.Strategy):
    params = (
        # Trend detection (4H)
        # Optimized via Optuna (26 trials, best value: 86.73)
        ('ema_fast', 9),              # Fast EMA for trend
        ('ema_slow', 25),             # Slow EMA for trend
        ('trend_strength', 1.2),      # Min % difference between EMAs for valid trend

        # Entry conditions (15m)
        ('rsi_period', 11),           # RSI period
        ('rsi_oversold', 29),         # RSI level for long entry (buy dips in uptrend)
        ('rsi_overbought', 72),       # RSI level for short entry (sell rallies in downtrend)
        ('pullback_pct', 1.25),       # Price pullback % from recent high/low

        # Take profit / Stop loss
        ('tp_pct', 0.5),              # Take profit % (tight for high win rate)
        ('sl_pct', 6.0),              # Stop loss % (wide to avoid noise)

        # Position sizing
        ('risk_pct', 2.0),            # Risk % per trade
        ('position_pct', 90.0),       # Max position as % of equity

        # Cooldown
        ('cooldown_bars', 7),         # 15m bars between trades (~1.75 hours)
    )

    def __init__(self):
        # Data feeds
        self.data15 = self.datas[0]   # 15m
        self.data4h = self.datas[2]   # 4h

        # 4H Trend indicators
        self.ema_fast_4h = btind.EMA(self.data4h.close, period=self.p.ema_fast)
        self.ema_slow_4h = btind.EMA(self.data4h.close, period=self.p.ema_slow)

        # 15m Entry indicators
        self.rsi_15m = btind.RSI(self.data15.close, period=self.p.rsi_period)

        # Track recent high/low for pullback detection
        self.recent_high = btind.Highest(self.data15.high, period=12)  # 3 hour high
        self.recent_low = btind.Lowest(self.data15.low, period=12)     # 3 hour low

        # Position tracking
        self.entry_price = None
        self.position_type = None
        self.stop_loss = None
        self.take_profit = None

        # Bar tracking
        self.last_trade_bar = -999
        self.last_15m_len = 0

    def next(self):
        # Need enough data for indicators
        if len(self.data4h) < self.p.ema_slow + 1:
            return
        if len(self.data15) < self.p.rsi_period + 12:
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

        # Calculate trend strength as % difference
        if ema_slow == 0:
            return None

        diff_pct = ((ema_fast - ema_slow) / ema_slow) * 100

        if diff_pct > self.p.trend_strength:
            return 'up'
        elif diff_pct < -self.p.trend_strength:
            return 'down'

        return None

    def _check_entry(self, trend):
        """Check for entry signals based on trend and pullback."""
        current_price = self.data15.close[0]
        rsi = self.rsi_15m[0]

        if trend == 'up':
            # UPTREND: Look for pullback (RSI dip) to go long
            # Price should have pulled back from recent high
            pullback_threshold = self.recent_high[0] * (1 - self.p.pullback_pct / 100)

            if current_price <= pullback_threshold and rsi <= self.p.rsi_oversold:
                self._enter_long(current_price)

        elif trend == 'down':
            # DOWNTREND: Look for rally (RSI spike) to go short
            # Price should have rallied from recent low
            rally_threshold = self.recent_low[0] * (1 + self.p.pullback_pct / 100)

            if current_price >= rally_threshold and rsi >= self.p.rsi_overbought:
                self._enter_short(current_price)

    def _enter_long(self, price):
        """Enter long position."""
        self.take_profit = price * (1 + self.p.tp_pct / 100)
        self.stop_loss = price * (1 - self.p.sl_pct / 100)

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
        self.last_trade_bar = len(self.data15)

        dt = self.data15.datetime.datetime(0)
        print(f"[{dt}] LONG @ {price:.2f} | TP: {self.take_profit:.2f} (+{self.p.tp_pct}%) | "
              f"SL: {self.stop_loss:.2f} (-{self.p.sl_pct}%) | RSI: {self.rsi_15m[0]:.1f}")

    def _enter_short(self, price):
        """Enter short position."""
        self.take_profit = price * (1 - self.p.tp_pct / 100)
        self.stop_loss = price * (1 + self.p.sl_pct / 100)

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
        self.last_trade_bar = len(self.data15)

        dt = self.data15.datetime.datetime(0)
        print(f"[{dt}] SHORT @ {price:.2f} | TP: {self.take_profit:.2f} (-{self.p.tp_pct}%) | "
              f"SL: {self.stop_loss:.2f} (+{self.p.sl_pct}%) | RSI: {self.rsi_15m[0]:.1f}")

    def _check_exits(self):
        """Check for TP/SL exits."""
        if self.entry_price is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        if self.position_type == 'long':
            # Check TP first (we want wins)
            if current_price >= self.take_profit:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                print(f"[{dt}] LONG TP HIT @ {current_price:.2f} ({pnl_pct:+.2f}%) ✓")
                self.close()
                self._reset()
                return

            if current_price <= self.stop_loss:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                print(f"[{dt}] LONG SL HIT @ {current_price:.2f} ({pnl_pct:+.2f}%) ✗")
                self.close()
                self._reset()
                return

        elif self.position_type == 'short':
            # Check TP first
            if current_price <= self.take_profit:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                print(f"[{dt}] SHORT TP HIT @ {current_price:.2f} ({pnl_pct:+.2f}%) ✓")
                self.close()
                self._reset()
                return

            if current_price >= self.stop_loss:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                print(f"[{dt}] SHORT SL HIT @ {current_price:.2f} ({pnl_pct:+.2f}%) ✗")
                self.close()
                self._reset()
                return

    def _reset(self):
        """Reset position tracking."""
        self.entry_price = None
        self.position_type = None
        self.stop_loss = None
        self.take_profit = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = "BUY" if order.isbuy() else "SELL"
            print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: {trade.pnlcomm:.2f}")
