# strategies/sol_strategy_v11.py
"""
SolStrategy v11 - Combined Range + Trend Strategy (4H Based)
-------------------------------------------------------------
Combines Range and Trend strategies based on 4H market classification.

Key Changes from Original Guide:
- Much longer cooldowns to reduce overtrading (commission drag was killing returns)
- Higher minimum range requirements
- Simplified exit: full TP or full SL (no partials cutting winners short)
- Risk-based position sizing (2% risk per trade)

Market Classification (Last 6 4H Candles):
  - UPTREND: 4+ consecutive higher highs AND higher lows → Trade LONG only
  - DOWNTREND: 4+ consecutive lower highs AND lower lows → Trade SHORT only
  - RANGING: Mixed/no pattern → Trade both directions (mean reversion)

Data feeds (expected index order):
  0 → 15m (base, used for entries)
  1 → 1h (unused)
  2 → 4h (trend detection, prev candle high/low)
  3 → weekly (unused)
  4 → daily (unused)
"""

import backtrader as bt


class SolStrategyV11(bt.Strategy):
    params = (
        # Trend detection (4H candles)
        ('trend_lookback', 6),           # 4H candles to check for trend
        ('min_trend_candles', 4),        # Minimum consecutive HH/HL or LH/LL for trend

        # Range Strategy parameters
        ('range_approach_pct', 0.5),     # Entry threshold for range
        ('range_min_range_pct', 5.0),    # Minimum 4H range (increased from 2.5%)
        ('range_buffer_pct', 3.0),       # Target buffer (reduced to let winners run more)
        ('range_rr_ratio', 3.0),         # R:R ratio (increased from 2.2)
        ('range_cooldown_bars', 96),     # 24 hours = 96 x 15m bars (was 2)

        # Trend Strategy parameters
        ('trend_approach_pct', 0.3),     # Entry threshold for trend (tighter)
        ('trend_min_range_pct', 4.0),    # Minimum 4H range (increased from 1.0%)
        ('trend_buffer_pct', 3.0),       # Target buffer
        ('trend_rr_ratio', 3.5),         # R:R ratio (increased from 2.7)
        ('trend_cooldown_bars', 192),    # 48 hours = 192 x 15m bars (was 16)

        # Risk-based position sizing
        ('risk_per_trade_pct', 2.0),     # Risk 2% of equity per trade
        ('max_position_pct', 30.0),      # Max 30% of equity in single position
    )

    def __init__(self):
        # Data feeds
        self.data15 = self.datas[0]   # 15m: base timeframe (entry signals)
        self.data4h = self.datas[2]   # 4h: trend detection, prev high/low

        # Track previous 4H bar data
        self.prev_4h_high = None
        self.prev_4h_low = None

        # Current market state
        self.market_state = None       # 'uptrend', 'downtrend', or 'ranging'

        # Position state
        self.entry_price = None
        self.position_type = None      # 'long' or 'short'
        self.trade_mode = None         # 'range' or 'trend'
        self.initial_size = None

        # TP/SL levels (simplified - no partials)
        self.stop_loss = None
        self.take_profit = None

        # Track bar counts for new bar detection
        self.last_4h_len = 0
        self.last_15m_len = 0

        # Trade cooldown tracking
        self.last_trade_bar = -999

    def next(self):
        # Need enough 4H data for trend detection
        if len(self.data4h) < self.p.trend_lookback + 2:
            return

        # Update previous 4H high/low and market state on new 4H bar
        if len(self.data4h) != self.last_4h_len:
            self.last_4h_len = len(self.data4h)
            # Previous 4H candle's high/low (index -1 is the prior completed bar)
            self.prev_4h_high = self.data4h.high[-1]
            self.prev_4h_low = self.data4h.low[-1]
            # Update market state classification
            self.market_state = self._classify_market()

        # If in position, check exits on every 15m bar
        if self.position and self.position_type is not None:
            self._check_exits()
            return

        # Entry logic: only check on new 15m bar
        if len(self.data15) == self.last_15m_len:
            return
        self.last_15m_len = len(self.data15)

        # Check for entry signals based on market state
        self._check_entry()

    def _classify_market(self):
        """
        Classify market as uptrend, downtrend, or ranging based on 4H candles.
        """
        n = self.p.trend_lookback
        min_trend = self.p.min_trend_candles

        # Get 4H highs and lows
        highs = [self.data4h.high[-i] for i in range(n + 1)]
        lows = [self.data4h.low[-i] for i in range(n + 1)]

        # Reverse so index 0 is oldest
        highs = highs[::-1]
        lows = lows[::-1]

        # Count consecutive higher highs AND higher lows (uptrend)
        uptrend_count = 0
        for i in range(1, len(highs)):
            if highs[i] > highs[i-1] and lows[i] > lows[i-1]:
                uptrend_count += 1
            else:
                break

        if uptrend_count >= min_trend:
            return 'uptrend'

        # Count consecutive lower highs AND lower lows (downtrend)
        downtrend_count = 0
        for i in range(1, len(highs)):
            if highs[i] < highs[i-1] and lows[i] < lows[i-1]:
                downtrend_count += 1
            else:
                break

        if downtrend_count >= min_trend:
            return 'downtrend'

        return 'ranging'

    def _check_entry(self):
        """Check for entry signals based on market state."""
        if self.prev_4h_high is None or self.prev_4h_low is None:
            return

        current_price = self.data15.close[0]
        candle_range = self.prev_4h_high - self.prev_4h_low
        range_pct = (candle_range / current_price) * 100

        # Determine parameters based on market state
        if self.market_state == 'ranging':
            approach_pct = self.p.range_approach_pct
            min_range_pct = self.p.range_min_range_pct
            cooldown_bars = self.p.range_cooldown_bars
            self.trade_mode = 'range'
        else:
            approach_pct = self.p.trend_approach_pct
            min_range_pct = self.p.trend_min_range_pct
            cooldown_bars = self.p.trend_cooldown_bars
            self.trade_mode = 'trend'

        # Check minimum range requirement
        if range_pct < min_range_pct:
            return

        # Check cooldown
        bars_since_trade = len(self.data15) - self.last_trade_bar
        if bars_since_trade < cooldown_bars:
            return

        approach_threshold = approach_pct / 100

        # Entry signals based on market state
        if self.market_state == 'ranging':
            low_threshold = self.prev_4h_low * (1 + approach_threshold)
            high_threshold = self.prev_4h_high * (1 - approach_threshold)

            if current_price <= low_threshold:
                self._enter_long(current_price, candle_range)
            elif current_price >= high_threshold:
                self._enter_short(current_price, candle_range)

        elif self.market_state == 'uptrend':
            low_threshold = self.prev_4h_low * (1 + approach_threshold)
            if current_price <= low_threshold:
                self._enter_long(current_price, candle_range)

        elif self.market_state == 'downtrend':
            high_threshold = self.prev_4h_high * (1 - approach_threshold)
            if current_price >= high_threshold:
                self._enter_short(current_price, candle_range)

    def _get_params_for_mode(self):
        """Get the appropriate parameters based on trade mode."""
        if self.trade_mode == 'range':
            return {
                'buffer_pct': self.p.range_buffer_pct,
                'rr_ratio': self.p.range_rr_ratio,
            }
        else:
            return {
                'buffer_pct': self.p.trend_buffer_pct,
                'rr_ratio': self.p.trend_rr_ratio,
            }

    def _calculate_position_size(self, entry_price, stop_loss):
        """
        Calculate position size based on risking X% of equity per trade.
        """
        equity = self.broker.getvalue()
        risk_amount = equity * (self.p.risk_per_trade_pct / 100)
        risk_per_unit = abs(entry_price - stop_loss)

        if risk_per_unit <= 0:
            return 0

        size = risk_amount / risk_per_unit

        # Cap at max position percentage
        max_size = (equity * (self.p.max_position_pct / 100)) / entry_price
        size = min(size, max_size)

        # Ensure we have enough cash
        max_affordable = self.broker.get_cash() / entry_price
        size = min(size, max_affordable * 0.99)

        return size

    def _enter_long(self, price, candle_range):
        """Enter long position with calculated TP/SL levels."""
        params = self._get_params_for_mode()

        buffer = candle_range * (params['buffer_pct'] / 100)
        effective_target = self.prev_4h_high - buffer
        effective_range = effective_target - price

        if effective_range <= 0:
            return

        # Calculate SL and TP (simplified - no partials)
        sl_distance = effective_range / params['rr_ratio']
        self.stop_loss = price - sl_distance
        self.take_profit = effective_target

        # Risk-based position sizing
        size = self._calculate_position_size(price, self.stop_loss)
        if size <= 0:
            return

        self.buy(size=size)

        self.entry_price = price
        self.position_type = 'long'
        self.initial_size = size
        self.last_trade_bar = len(self.data15)

        dt = self.data15.datetime.datetime(0)
        risk_pct = (sl_distance / price) * 100
        reward_pct = (effective_range / price) * 100
        print(f"[{dt}] {self.market_state.upper()} LONG @ {price:.2f} | "
              f"SL: {self.stop_loss:.2f} ({risk_pct:.1f}%) | "
              f"TP: {self.take_profit:.2f} ({reward_pct:.1f}%) | "
              f"R:R {params['rr_ratio']:.1f}")

    def _enter_short(self, price, candle_range):
        """Enter short position with calculated TP/SL levels."""
        params = self._get_params_for_mode()

        buffer = candle_range * (params['buffer_pct'] / 100)
        effective_target = self.prev_4h_low + buffer
        effective_range = price - effective_target

        if effective_range <= 0:
            return

        # Calculate SL and TP (simplified - no partials)
        sl_distance = effective_range / params['rr_ratio']
        self.stop_loss = price + sl_distance
        self.take_profit = effective_target

        # Risk-based position sizing
        size = self._calculate_position_size(price, self.stop_loss)
        if size <= 0:
            return

        self.sell(size=size)

        self.entry_price = price
        self.position_type = 'short'
        self.initial_size = size
        self.last_trade_bar = len(self.data15)

        dt = self.data15.datetime.datetime(0)
        risk_pct = (sl_distance / price) * 100
        reward_pct = (effective_range / price) * 100
        print(f"[{dt}] {self.market_state.upper()} SHORT @ {price:.2f} | "
              f"SL: {self.stop_loss:.2f} ({risk_pct:.1f}%) | "
              f"TP: {self.take_profit:.2f} ({reward_pct:.1f}%) | "
              f"R:R {params['rr_ratio']:.1f}")

    def _check_exits(self):
        """Check for stop loss and take profit exits."""
        if self.initial_size is None or self.position_type is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        if self.position_type == 'long':
            if current_price <= self.stop_loss:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                print(f"[{dt}] LONG STOP LOSS @ {current_price:.2f} ({pnl_pct:+.1f}%)")
                self.close()
                self._reset_position()
                return

            if current_price >= self.take_profit:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                print(f"[{dt}] LONG TAKE PROFIT @ {current_price:.2f} ({pnl_pct:+.1f}%)")
                self.close()
                self._reset_position()
                return

        elif self.position_type == 'short':
            if current_price >= self.stop_loss:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                print(f"[{dt}] SHORT STOP LOSS @ {current_price:.2f} ({pnl_pct:+.1f}%)")
                self.close()
                self._reset_position()
                return

            if current_price <= self.take_profit:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                print(f"[{dt}] SHORT TAKE PROFIT @ {current_price:.2f} ({pnl_pct:+.1f}%)")
                self.close()
                self._reset_position()
                return

    def _reset_position(self):
        """Reset all position tracking variables."""
        self.entry_price = None
        self.position_type = None
        self.trade_mode = None
        self.initial_size = None
        self.stop_loss = None
        self.take_profit = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                action = "BUY" if self.position_type == 'long' else "COVER"
                print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")
            else:
                action = "SELL" if self.position_type == 'short' else "SELL"
                print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}")
