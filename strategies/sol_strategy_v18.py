# strategies/sol_strategy_v18.py
"""
SolStrategy v18 - Donchian Channel Breakout (2 Params)
------------------------------------------------------
Radically simple: Donchian channel breakout on 1H with ATR trailing stop on 15m.
Only 2 optimizable params (285 combinations). Nearly impossible to overfit.

Core Concept:
- 1H: Donchian channel (N-bar highest high / lowest low) for entry signals
- 15m: ATR trailing stop for exits (checked every bar)
- Long: 1H close breaks above previous bar's channel high
- Short: 1H close breaks below previous bar's channel low
- Exit: Trailing stop hit (HWM/LWM - ATR * multiplier)

Data feeds (expected index order):
  0 -> 15m (base, exit checking every bar)
  1 -> 1h (entry signals, channel, ATR)
  2 -> 4h (unused)
  3 -> weekly (unused)
  4 -> daily (unused)
"""

import backtrader as bt
import backtrader.indicators as btind


class SolStrategyV18(bt.Strategy):
    params = (
        # Optimizable (2 only)
        ('channel_period', 78),    # 1H bars lookback (~3.25 days)
        ('atr_trail_mult', 6.25),  # ATR trailing stop multiplier
        # Fixed
        ('atr_period', 14),        # ATR calc period on 1H
    )

    def __init__(self):
        # Data feeds
        self.data15 = self.datas[0]   # 15m: exit checking every bar
        self.data1h = self.datas[1]   # 1h: entry signals, channel, ATR

        # 1H Indicators
        self.channel_high = btind.Highest(self.data1h.high, period=self.p.channel_period)
        self.channel_low = btind.Lowest(self.data1h.low, period=self.p.channel_period)
        self.atr_1h = btind.ATR(self.data1h, period=self.p.atr_period)

        # Position tracking
        self.entry_price = None
        self.position_type = None       # 'long' or 'short'
        self.entry_atr = None           # 1H ATR snapshot at entry (fixed for trade)
        self.high_water_mark = None     # For long trailing stop
        self.low_water_mark = None      # For short trailing stop

        # Bar tracking for new 1H bar detection
        self.last_1h_len = 0

    def next(self):
        # Need enough data for channel and ATR
        min_bars = max(self.p.channel_period, self.p.atr_period) + 2
        if len(self.data1h) < min_bars:
            return

        # If in position, check exits on every 15m bar
        if self.position:
            self._check_exits()

        # Only check entries on new 1H bar
        if len(self.data1h) == self.last_1h_len:
            return
        self.last_1h_len = len(self.data1h)

        self._check_entries()

    def _check_entries(self):
        """Check for Donchian channel breakout on 1H."""
        close_1h = self.data1h.close[0]
        prev_channel_high = self.channel_high[-1]
        prev_channel_low = self.channel_low[-1]
        atr = self.atr_1h[0]

        if atr <= 0:
            return

        # Long breakout: 1H close > previous bar's channel high
        if close_1h > prev_channel_high:
            if self.position_type == 'short':
                # Close short, enter long
                self._close_position("REVERSAL TO LONG")
            if not self.position:
                self._enter_long(close_1h, atr)
            return

        # Short breakout: 1H close < previous bar's channel low
        if close_1h < prev_channel_low:
            if self.position_type == 'long':
                # Close long, enter short
                self._close_position("REVERSAL TO SHORT")
            if not self.position:
                self._enter_short(close_1h, atr)
            return

    def _enter_long(self, price, atr):
        """Enter long position."""
        cash = self.broker.get_cash()
        size = (cash * 0.98) / price
        if size <= 0:
            return

        self.buy(size=size)
        self.entry_price = price
        self.position_type = 'long'
        self.entry_atr = atr
        self.high_water_mark = price
        self.low_water_mark = None

        trail_stop = price - (atr * self.p.atr_trail_mult)
        dt = self.data15.datetime.datetime(0)
        print(f"[{dt}] LONG @ {price:.2f} | "
              f"Trail: {trail_stop:.2f} | ATR: {atr:.2f} | Size: {size:.4f}")

        # Snapshot market context for trade journal
        ch_width = self.channel_high[0] - self.channel_low[0]
        ch_width_pct = (ch_width / price * 100) if price > 0 else 0
        self._entry_context = {
            "atr": round(atr, 4),
            "channel_width_pct": round(ch_width_pct, 2),
            "direction": "long",
        }

    def _enter_short(self, price, atr):
        """Enter short position."""
        cash = self.broker.get_cash()
        size = (cash * 0.98) / price
        if size <= 0:
            return

        self.sell(size=size)
        self.entry_price = price
        self.position_type = 'short'
        self.entry_atr = atr
        self.low_water_mark = price
        self.high_water_mark = None

        trail_stop = price + (atr * self.p.atr_trail_mult)
        dt = self.data15.datetime.datetime(0)
        print(f"[{dt}] SHORT @ {price:.2f} | "
              f"Trail: {trail_stop:.2f} | ATR: {atr:.2f} | Size: {size:.4f}")

        # Snapshot market context for trade journal
        ch_width = self.channel_high[0] - self.channel_low[0]
        ch_width_pct = (ch_width / price * 100) if price > 0 else 0
        self._entry_context = {
            "atr": round(atr, 4),
            "channel_width_pct": round(ch_width_pct, 2),
            "direction": "short",
        }

    def _check_exits(self):
        """Check ATR trailing stop on every 15m bar."""
        if self.entry_price is None or self.entry_atr is None:
            return

        current_price = self.data15.close[0]
        trail_distance = self.entry_atr * self.p.atr_trail_mult

        if self.position_type == 'long':
            # Update high water mark
            if current_price > self.high_water_mark:
                self.high_water_mark = current_price

            # Trailing stop
            stop_price = self.high_water_mark - trail_distance
            if current_price <= stop_price:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                dt = self.data15.datetime.datetime(0)
                print(f"[{dt}] LONG TRAIL STOP @ {current_price:.2f} ({pnl_pct:+.2f}%) | "
                      f"HWM: {self.high_water_mark:.2f} | Stop: {stop_price:.2f}")
                self.close()
                self._reset()

        elif self.position_type == 'short':
            # Update low water mark
            if current_price < self.low_water_mark:
                self.low_water_mark = current_price

            # Trailing stop
            stop_price = self.low_water_mark + trail_distance
            if current_price >= stop_price:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                dt = self.data15.datetime.datetime(0)
                print(f"[{dt}] SHORT TRAIL STOP @ {current_price:.2f} ({pnl_pct:+.2f}%) | "
                      f"LWM: {self.low_water_mark:.2f} | Stop: {stop_price:.2f}")
                self.close()
                self._reset()

    def _close_position(self, reason):
        """Close current position with logging."""
        if self.entry_price is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        if self.position_type == 'long':
            pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
            print(f"[{dt}] LONG {reason} @ {current_price:.2f} ({pnl_pct:+.2f}%)")
        elif self.position_type == 'short':
            pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
            print(f"[{dt}] SHORT {reason} @ {current_price:.2f} ({pnl_pct:+.2f}%)")

        self.close()
        self._reset()

    def _reset(self):
        """Reset position tracking."""
        self.entry_price = None
        self.position_type = None
        self.entry_atr = None
        self.high_water_mark = None
        self.low_water_mark = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = "BUY" if order.isbuy() else "SELL"
            print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}")
