# strategies/sol_strategy_v18.py
"""
SolStrategy v18 - Donchian Channel Breakout (2 Params)
------------------------------------------------------
Radically simple: Donchian channel breakout on 1H with ATR trailing stop on 15m.
Only 2 optimizable params (285 combinations). Nearly impossible to overfit.

Core Concept:
- 1H: Donchian channel (N-bar highest high / lowest low) for entry signals
- 15m: R-based partial exits + ATR trailing stop on runner
- Long: 1H close breaks above previous bar's channel high
- Short: 1H close breaks below previous bar's channel low
- Exit: 30% at 1R, 30% at 2R, 30% at 3R, trail 10% runner

Risk Model:
- Position sized so stop loss (-1R) = risk_per_trade_pct of account
- 1R = ATR * atr_trail_mult (initial trailing distance)
- Stop ratchets: breakeven at 1R, +1R at 2R, +2R at 3R

Data feeds (expected index order):
  0 -> 15m (base, exit checking every bar)
  1 -> 1h (entry signals, channel, ATR)
  2 -> 4h (unused)
  3 -> weekly (unused)
  4 -> daily (unused)
"""

import backtrader as bt
import backtrader.indicators as btind
from risk_manager import RiskManager


class SolStrategyV18(bt.Strategy):
    params = (
        # Optimizable (2 only)
        ('channel_period', 78),    # 1H bars lookback (~3.25 days)
        ('atr_trail_mult', 6.25),  # ATR trailing stop multiplier (defines 1R)
        # Fixed
        ('atr_period', 14),        # ATR calc period on 1H
        # Risk management
        ('risk_per_trade_pct', 3.0),  # Risk 3% of account at stop loss
    )

    def __init__(self):
        # Data feeds
        self.data15 = self.datas[0]   # 15m: exit checking every bar
        self.data1h = self.datas[1]   # 1h: entry signals, channel, ATR

        # 1H Indicators
        self.channel_high = btind.Highest(self.data1h.high, period=self.p.channel_period)
        self.channel_low = btind.Lowest(self.data1h.low, period=self.p.channel_period)
        self.atr_1h = btind.ATR(self.data1h, period=self.p.atr_period)

        # Risk manager
        self.risk_mgr = RiskManager(risk_pct=self.p.risk_per_trade_pct)

        # Position tracking
        self.entry_price = None
        self.position_type = None       # 'long' or 'short'
        self.entry_atr = None           # 1H ATR snapshot at entry
        self.stop_distance = None       # 1R distance
        self.r_targets = {}             # {-1: stop, 1: 1R, 2: 2R, 3: 3R}
        self.current_stop = None        # Ratcheted stop price
        self.partials_taken = 0         # 0, 1, 2, or 3
        self.initial_size = 0           # Original position size
        self.high_water_mark = None     # For long runner trailing
        self.low_water_mark = None      # For short runner trailing

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
                self._close_position("REVERSAL TO LONG")
            if not self.position:
                self._enter_long(close_1h, atr)
            return

        # Short breakout: 1H close < previous bar's channel low
        if close_1h < prev_channel_low:
            if self.position_type == 'long':
                self._close_position("REVERSAL TO SHORT")
            if not self.position:
                self._enter_short(close_1h, atr)
            return

    def _enter_long(self, price, atr):
        """Enter long position with R-based sizing."""
        equity = self.broker.getvalue()
        self.stop_distance = atr * self.p.atr_trail_mult

        size = self.risk_mgr.calculate_position_size(equity, self.stop_distance)
        if size <= 0:
            return

        # Cap at leverage limit
        max_size = (equity * 100) / price
        size = min(size, max_size * 0.95)

        self.buy(size=size)
        self.entry_price = price
        self.position_type = 'long'
        self.entry_atr = atr
        self.initial_size = size
        self.partials_taken = 0
        self.high_water_mark = price
        self.low_water_mark = None

        # Calculate R-targets
        self.r_targets = self.risk_mgr.calculate_r_targets(price, self.stop_distance, 'long')
        self.current_stop = self.r_targets[-1]

        risk_amt = equity * self.risk_mgr.risk_pct
        dt = self.data15.datetime.datetime(0)
        print(f"[{dt}] LONG @ {price:.2f} | "
              f"Size: {size:.4f} | Risk: ${risk_amt:.0f} ({self.p.risk_per_trade_pct}%) | "
              f"Stop: {self.current_stop:.2f} (-1R) | "
              f"1R: {self.r_targets.get(1.0, 0):.2f} | "
              f"2R: {self.r_targets.get(2.0, 0):.2f} | "
              f"3R: {self.r_targets.get(3.0, 0):.2f}")

        # Snapshot market context for trade journal
        ch_width = self.channel_high[0] - self.channel_low[0]
        ch_width_pct = (ch_width / price * 100) if price > 0 else 0
        self._entry_context = {
            "atr": round(atr, 4),
            "channel_width_pct": round(ch_width_pct, 2),
            "direction": "long",
            "stop_distance": round(self.stop_distance, 4),
            "risk_pct": self.p.risk_per_trade_pct,
            "position_size": round(size, 4),
        }

    def _enter_short(self, price, atr):
        """Enter short position with R-based sizing."""
        equity = self.broker.getvalue()
        self.stop_distance = atr * self.p.atr_trail_mult

        size = self.risk_mgr.calculate_position_size(equity, self.stop_distance)
        if size <= 0:
            return

        # Cap at leverage limit
        max_size = (equity * 100) / price
        size = min(size, max_size * 0.95)

        self.sell(size=size)
        self.entry_price = price
        self.position_type = 'short'
        self.entry_atr = atr
        self.initial_size = size
        self.partials_taken = 0
        self.low_water_mark = price
        self.high_water_mark = None

        # Calculate R-targets
        self.r_targets = self.risk_mgr.calculate_r_targets(price, self.stop_distance, 'short')
        self.current_stop = self.r_targets[-1]

        risk_amt = equity * self.risk_mgr.risk_pct
        dt = self.data15.datetime.datetime(0)
        print(f"[{dt}] SHORT @ {price:.2f} | "
              f"Size: {size:.4f} | Risk: ${risk_amt:.0f} ({self.p.risk_per_trade_pct}%) | "
              f"Stop: {self.current_stop:.2f} (-1R) | "
              f"1R: {self.r_targets.get(1.0, 0):.2f} | "
              f"2R: {self.r_targets.get(2.0, 0):.2f} | "
              f"3R: {self.r_targets.get(3.0, 0):.2f}")

        # Snapshot market context for trade journal
        ch_width = self.channel_high[0] - self.channel_low[0]
        ch_width_pct = (ch_width / price * 100) if price > 0 else 0
        self._entry_context = {
            "atr": round(atr, 4),
            "channel_width_pct": round(ch_width_pct, 2),
            "direction": "short",
            "stop_distance": round(self.stop_distance, 4),
            "risk_pct": self.p.risk_per_trade_pct,
            "position_size": round(size, 4),
        }

    def _check_exits(self):
        """Check R-based exits on every 15m bar."""
        if self.entry_price is None or self.stop_distance is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)
        direction = self.position_type

        if direction == 'long':
            self._check_long_exits(current_price, dt)
        elif direction == 'short':
            self._check_short_exits(current_price, dt)

    def _check_long_exits(self, current_price, dt):
        """Check exits for long position."""
        # Update high water mark
        if current_price > self.high_water_mark:
            self.high_water_mark = current_price

        # Check R-target partials (1R, 2R, 3R)
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
                    print(f"[{dt}] LONG PARTIAL {self.partials_taken}/3 @ {current_price:.2f} "
                          f"(+{r_mult:.0f}R, selling {fraction:.0%}) | "
                          f"New stop: {self.current_stop:.2f}")
                    self.sell(size=partial_size)
                    return

        # Check ratcheted stop
        if current_price <= self.current_stop:
            pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
            r_mult = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'long')
            reason = "STOP (-1R)" if self.partials_taken == 0 else f"RATCHET STOP (after {self.partials_taken}R)"
            print(f"[{dt}] LONG {reason} @ {current_price:.2f} ({pnl_pct:+.2f}%, {r_mult:+.1f}R)")
            self.close()
            self._reset()
            return

        # Runner trailing stop (after all 3 partials)
        if self.partials_taken >= 3:
            trail_distance = self.entry_atr * self.p.atr_trail_mult
            trail_stop = self.high_water_mark - trail_distance
            effective_stop = max(self.current_stop, trail_stop)
            if current_price <= effective_stop:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                r_mult = self.risk_mgr.calculate_r_multiple(
                    self.entry_price, current_price, self.stop_distance, 'long')
                print(f"[{dt}] LONG RUNNER TRAIL @ {current_price:.2f} ({pnl_pct:+.2f}%, {r_mult:+.1f}R) | "
                      f"HWM: {self.high_water_mark:.2f}")
                self.close()
                self._reset()

    def _check_short_exits(self, current_price, dt):
        """Check exits for short position."""
        # Update low water mark
        if current_price < self.low_water_mark:
            self.low_water_mark = current_price

        # Check R-target partials (1R, 2R, 3R) — for shorts, target is BELOW entry
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
                    print(f"[{dt}] SHORT PARTIAL {self.partials_taken}/3 @ {current_price:.2f} "
                          f"(+{r_mult:.0f}R, selling {fraction:.0%}) | "
                          f"New stop: {self.current_stop:.2f}")
                    self.buy(size=partial_size)
                    return

        # Check ratcheted stop
        if current_price >= self.current_stop:
            pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
            r_mult = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'short')
            reason = "STOP (-1R)" if self.partials_taken == 0 else f"RATCHET STOP (after {self.partials_taken}R)"
            print(f"[{dt}] SHORT {reason} @ {current_price:.2f} ({pnl_pct:+.2f}%, {r_mult:+.1f}R)")
            self.close()
            self._reset()
            return

        # Runner trailing stop (after all 3 partials)
        if self.partials_taken >= 3:
            trail_distance = self.entry_atr * self.p.atr_trail_mult
            trail_stop = self.low_water_mark + trail_distance
            effective_stop = min(self.current_stop, trail_stop)
            if current_price >= effective_stop:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                r_mult = self.risk_mgr.calculate_r_multiple(
                    self.entry_price, current_price, self.stop_distance, 'short')
                print(f"[{dt}] SHORT RUNNER TRAIL @ {current_price:.2f} ({pnl_pct:+.2f}%, {r_mult:+.1f}R) | "
                      f"LWM: {self.low_water_mark:.2f}")
                self.close()
                self._reset()

    def _close_position(self, reason):
        """Close current position with logging (for reversals)."""
        if self.entry_price is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        if self.position_type == 'long':
            pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
            r_mult = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'long') if self.stop_distance else 0
            print(f"[{dt}] LONG {reason} @ {current_price:.2f} ({pnl_pct:+.2f}%, {r_mult:+.1f}R)")
        elif self.position_type == 'short':
            pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
            r_mult = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'short') if self.stop_distance else 0
            print(f"[{dt}] SHORT {reason} @ {current_price:.2f} ({pnl_pct:+.2f}%, {r_mult:+.1f}R)")

        self.close()
        self._reset()

    def _reset(self):
        """Reset position tracking."""
        self.entry_price = None
        self.position_type = None
        self.entry_atr = None
        self.stop_distance = None
        self.r_targets = {}
        self.current_stop = None
        self.partials_taken = 0
        self.initial_size = 0
        self.high_water_mark = None
        self.low_water_mark = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = "BUY" if order.isbuy() else "SELL"
            print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}")
