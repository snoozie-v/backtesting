# strategies/sol_strategy_v9.py
"""
SolStrategy v9 - Range Trading with Previous Day High/Low
----------------------------------------------------------
Logic:
- Detect RANGING market: No 3 consecutive higher highs/higher lows (uptrend)
  AND no 3 consecutive lower highs/lower lows (downtrend) on daily timeframe
- Entry on HOURLY timeframe when price approaches previous day's high/low within threshold
  - Long: price within 0.5% of previous day LOW
  - Short: price within 0.5% of previous day HIGH
- Targets use 1% buffer (99% of range) to avoid exact extremes
- 3:1 Risk/Reward with partial take profits:
  - TP1: 1/3 of effective range → close 33.3%, move SL to entry
  - TP2: 2/3 of effective range → close 33.3%, move SL to TP1
  - TP3: Full effective target → close remaining 33.4%

Data feeds (expected index order):
  0 → 15m (base)
  1 → 1h (entry signals)
  2 → 4h (unused)
  3 → weekly (unused)
  4 → daily (range detection, prev day high/low)
"""

import backtrader as bt


class SolStrategyV9(bt.Strategy):
    params = (
        # Range detection
        ('trend_lookback', 3),           # Days to check for trend (HH/HL or LH/LL)

        # Entry threshold
        ('approach_pct', 0.5),           # % within prev day high/low to trigger entry

        # Target buffer
        ('target_buffer_pct', 1.0),      # % buffer from exact high/low (99% of range)

        # Risk/Reward ratio
        ('rr_ratio', 3.0),               # Risk:Reward ratio (SL distance = range / rr_ratio)

        # Minimum range filter
        ('min_range_pct', 1.0),          # Minimum prev day range as % of price

        # Trade cooldown
        ('cooldown_bars', 4),            # Minimum hourly bars between trades

        # Position sizing
        ('position_pct', 0.98),          # % of cash to use per trade
    )

    def __init__(self):
        # Data feeds
        self.data15 = self.datas[0]   # 15m: base timeframe
        self.data1h = self.datas[1]   # 1h: entry signals
        self.daily = self.datas[4]    # Daily: range detection, prev high/low

        # Track previous daily bar data
        self.prev_day_high = None
        self.prev_day_low = None

        # Position state
        self.entry_price = None
        self.position_type = None      # 'long' or 'short'
        self.initial_size = None       # Original position size
        self.remaining_size = None     # Current position size after partials

        # TP/SL levels
        self.stop_loss = None
        self.tp1_price = None
        self.tp2_price = None
        self.tp3_price = None

        # TP hit tracking
        self.tp1_hit = False
        self.tp2_hit = False

        # Track bar counts for new bar detection
        self.last_daily_len = 0
        self.last_hourly_len = 0

        # Trade cooldown tracking
        self.last_trade_bar = -999  # Hourly bar count of last trade

    def next(self):
        # Need enough daily data for trend detection
        if len(self.daily) < self.p.trend_lookback + 2:
            return

        # Update previous day high/low on new daily bar
        if len(self.daily) != self.last_daily_len:
            self.last_daily_len = len(self.daily)
            # Previous day's high/low (index -1 is the prior completed bar)
            self.prev_day_high = self.daily.high[-1]
            self.prev_day_low = self.daily.low[-1]

        # If in position, check exits on every 15m bar
        # Also verify we have valid position tracking (not just pending close)
        if self.position and self.position_type is not None:
            self._check_exits()
            return

        # Entry logic: only check on new hourly bar
        if len(self.data1h) == self.last_hourly_len:
            return
        self.last_hourly_len = len(self.data1h)

        # Check if market is ranging (not trending)
        if not self._is_ranging():
            return

        # Check for entry signals
        self._check_entry()

    def _is_ranging(self):
        """
        Returns True if market is ranging (not in a clear trend).
        Ranging = NOT (3 consecutive HH/HL) AND NOT (3 consecutive LH/LL)
        """
        n = self.p.trend_lookback

        # Get daily highs and lows for trend detection
        highs = [self.daily.high[-i] for i in range(n + 1)]  # [today, -1, -2, -3]
        lows = [self.daily.low[-i] for i in range(n + 1)]

        # Reverse so index 0 is oldest
        highs = highs[::-1]  # [oldest, ..., newest]
        lows = lows[::-1]

        # Check for uptrend: 3 consecutive higher highs AND higher lows
        uptrend = True
        for i in range(1, len(highs)):
            if highs[i] <= highs[i-1] or lows[i] <= lows[i-1]:
                uptrend = False
                break

        # Check for downtrend: 3 consecutive lower highs AND lower lows
        downtrend = True
        for i in range(1, len(highs)):
            if highs[i] >= highs[i-1] or lows[i] >= lows[i-1]:
                downtrend = False
                break

        # Ranging if neither uptrend nor downtrend
        is_range = not uptrend and not downtrend

        return is_range

    def _check_entry(self):
        """Check for long/short entry signals near previous day's high/low."""
        if self.prev_day_high is None or self.prev_day_low is None:
            return

        # Check cooldown
        bars_since_trade = len(self.data1h) - self.last_trade_bar
        if bars_since_trade < self.p.cooldown_bars:
            return

        current_price = self.data1h.close[0]
        approach_threshold = self.p.approach_pct / 100

        # Calculate range and effective target with buffer
        day_range = self.prev_day_high - self.prev_day_low
        buffer = day_range * (self.p.target_buffer_pct / 100)

        # Check minimum range requirement
        range_pct = (day_range / current_price) * 100
        if range_pct < self.p.min_range_pct:
            return

        # Check for LONG entry: price near previous day low
        low_threshold = self.prev_day_low * (1 + approach_threshold)
        if current_price <= low_threshold:
            self._enter_long(current_price, day_range, buffer)
            return

        # Check for SHORT entry: price near previous day high
        high_threshold = self.prev_day_high * (1 - approach_threshold)
        if current_price >= high_threshold:
            self._enter_short(current_price, day_range, buffer)
            return

    def _enter_long(self, price, day_range, buffer):
        """Enter long position with calculated TP/SL levels."""
        effective_target = self.prev_day_high - buffer
        effective_range = effective_target - price

        # Avoid invalid setups (negative or tiny range)
        if effective_range <= 0:
            return

        # Calculate levels using R:R ratio
        sl_distance = effective_range / self.p.rr_ratio
        self.stop_loss = price - sl_distance
        self.tp1_price = price + (effective_range / 3)
        self.tp2_price = price + (effective_range * 2 / 3)
        self.tp3_price = effective_target

        # Position sizing
        cash = self.broker.get_cash()
        size = (cash * self.p.position_pct) / price

        self.buy(size=size)

        self.entry_price = price
        self.position_type = 'long'
        self.initial_size = size
        self.remaining_size = size
        self.tp1_hit = False
        self.tp2_hit = False
        self.last_trade_bar = len(self.data1h)

        dt = self.data1h.datetime.datetime(0)
        print(f"[{dt}] LONG ENTRY @ {price:.4f} | "
              f"SL: {self.stop_loss:.4f} | TP1: {self.tp1_price:.4f} | "
              f"TP2: {self.tp2_price:.4f} | TP3: {self.tp3_price:.4f}")

    def _enter_short(self, price, day_range, buffer):
        """Enter short position with calculated TP/SL levels."""
        effective_target = self.prev_day_low + buffer
        effective_range = price - effective_target

        # Avoid invalid setups (negative or tiny range)
        if effective_range <= 0:
            return

        # Calculate levels using R:R ratio
        sl_distance = effective_range / self.p.rr_ratio
        self.stop_loss = price + sl_distance
        self.tp1_price = price - (effective_range / 3)
        self.tp2_price = price - (effective_range * 2 / 3)
        self.tp3_price = effective_target

        # Position sizing
        cash = self.broker.get_cash()
        size = (cash * self.p.position_pct) / price

        self.sell(size=size)

        self.entry_price = price
        self.position_type = 'short'
        self.initial_size = size
        self.remaining_size = size
        self.tp1_hit = False
        self.tp2_hit = False
        self.last_trade_bar = len(self.data1h)

        dt = self.data1h.datetime.datetime(0)
        print(f"[{dt}] SHORT ENTRY @ {price:.4f} | "
              f"SL: {self.stop_loss:.4f} | TP1: {self.tp1_price:.4f} | "
              f"TP2: {self.tp2_price:.4f} | TP3: {self.tp3_price:.4f}")

    def _check_exits(self):
        """Check for stop loss and take profit exits."""
        # Safety check - ensure we have valid position data
        if self.initial_size is None or self.position_type is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        partial_size = self.initial_size / 3

        if self.position_type == 'long':
            # Check stop loss
            if current_price <= self.stop_loss:
                print(f"[{dt}] LONG STOP LOSS @ {current_price:.4f}")
                self.close()
                self._reset_position()
                return

            # Check TP3 (full exit)
            if current_price >= self.tp3_price:
                print(f"[{dt}] LONG TP3 HIT @ {current_price:.4f} - Closing remaining")
                self.close()
                self._reset_position()
                return

            # Check TP2
            if not self.tp2_hit and current_price >= self.tp2_price:
                print(f"[{dt}] LONG TP2 HIT @ {current_price:.4f} - Selling 33.3%, SL → TP1")
                self.sell(size=partial_size)
                self.remaining_size -= partial_size
                self.stop_loss = self.tp1_price  # Move SL to TP1
                self.tp2_hit = True
                return

            # Check TP1
            if not self.tp1_hit and current_price >= self.tp1_price:
                print(f"[{dt}] LONG TP1 HIT @ {current_price:.4f} - Selling 33.3%, SL → Entry")
                self.sell(size=partial_size)
                self.remaining_size -= partial_size
                self.stop_loss = self.entry_price  # Move SL to breakeven
                self.tp1_hit = True
                return

        elif self.position_type == 'short':
            # Check stop loss
            if current_price >= self.stop_loss:
                print(f"[{dt}] SHORT STOP LOSS @ {current_price:.4f}")
                self.close()
                self._reset_position()
                return

            # Check TP3 (full exit)
            if current_price <= self.tp3_price:
                print(f"[{dt}] SHORT TP3 HIT @ {current_price:.4f} - Closing remaining")
                self.close()
                self._reset_position()
                return

            # Check TP2
            if not self.tp2_hit and current_price <= self.tp2_price:
                print(f"[{dt}] SHORT TP2 HIT @ {current_price:.4f} - Buying 33.3%, SL → TP1")
                self.buy(size=partial_size)
                self.remaining_size -= partial_size
                self.stop_loss = self.tp1_price  # Move SL to TP1
                self.tp2_hit = True
                return

            # Check TP1
            if not self.tp1_hit and current_price <= self.tp1_price:
                print(f"[{dt}] SHORT TP1 HIT @ {current_price:.4f} - Buying 33.3%, SL → Entry")
                self.buy(size=partial_size)
                self.remaining_size -= partial_size
                self.stop_loss = self.entry_price  # Move SL to breakeven
                self.tp1_hit = True
                return

    def _reset_position(self):
        """Reset all position tracking variables."""
        self.entry_price = None
        self.position_type = None
        self.initial_size = None
        self.remaining_size = None
        self.stop_loss = None
        self.tp1_price = None
        self.tp2_price = None
        self.tp3_price = None
        self.tp1_hit = False
        self.tp2_hit = False

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                action = "BUY" if self.position_type == 'long' else "COVER"
                print(f"    {action} EXECUTED @ {order.executed.price:.4f}, Size: {order.executed.size:.4f}")
            else:
                action = "SELL" if self.position_type == 'short' else "SELL"
                print(f"    {action} EXECUTED @ {order.executed.price:.4f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}")
