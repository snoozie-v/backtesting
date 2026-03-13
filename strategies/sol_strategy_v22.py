# strategies/sol_strategy_v22.py
"""
SolStrategy v22 - 4H Structural Level + ATR Squeeze Breakout
-------------------------------------------------------------
Three-filter swing entry:
  1. Daily trend bias (EMA slope + price vs EMA)
  2. Price proximity to N-bar structural support/resistance (4H swing high/low)
  3. ATR squeeze forms at that level, then breaks out of squeeze range

High confluence reduces trade frequency but targets better-quality entries.

Entry Logic (on each new 4H bar):
  LONG:  daily bullish bias + price ≤ swing_low + proximity*ATR + close > squeeze_high
  SHORT: daily bearish bias + price ≥ swing_high - proximity*ATR + close < squeeze_low

Exits (every 15M bar):
  - 30% at 1R, 30% at 2R, 30% at 3R (ratcheted stop)
  - 10% runner: ATR trail from HWM using frozen entry ATR × atr_trail_mult
  - Runner trail activates only after all 3 partials (conservative vs V19)

Data feeds:
  datas[0] → 15m (exit checking)
  datas[2] → 4h  (squeeze + structural level)
  datas[4] → daily (trend bias EMA)
"""

import backtrader as bt
import backtrader.indicators as btind
from risk_manager import RiskManager


class SolStrategyV22(bt.Strategy):
    params = (
        ('level_lookback',       50),    # 4H bars for swing high/low detection
        ('level_proximity_atr',  1.5),   # Price must be within N*ATR of structural level
        ('daily_ema_period',     21),    # Daily EMA for trend bias
        ('squeeze_lookback',     50),    # ATR percentile rank lookback (4H bars)
        ('squeeze_pctile',       30),    # Squeeze threshold (ATR rank < this = squeeze)
        ('atr_stop_mult',        2.0),   # 1R = 4H ATR × this
        ('atr_trail_mult',       3.0),   # Runner trail = frozen ATR × this from HWM
        # Hardcoded
        ('atr_period',           14),    # ATR calculation period
        ('risk_pct',             3.0),   # % account to risk at stop
    )

    def __init__(self):
        # Data feed aliases
        self.data15 = self.datas[0]   # 15m: exit checking every bar
        self.data4h = self.datas[2]   # 4h: squeeze detection + structural levels
        self.daily  = self.datas[4]   # daily: trend bias

        # 4H Indicators
        self.atr4h      = btind.ATR(self.data4h, period=self.p.atr_period)
        self.swing_high = btind.Highest(self.data4h.high, period=self.p.level_lookback)
        self.swing_low  = btind.Lowest(self.data4h.low,   period=self.p.level_lookback)

        # Daily indicator
        self.daily_ema = btind.EMA(self.daily.close, period=self.p.daily_ema_period)

        # Risk manager
        self.risk_mgr = RiskManager(risk_pct=self.p.risk_pct)

        # Squeeze tracking state
        self.in_squeeze   = False
        self.sq_high      = None
        self.sq_low       = None
        self.sq_bar_count = 0

        # Position tracking
        self.entry_price   = None
        self.position_type = None    # 'long' or 'short'
        self.entry_atr     = None    # Frozen ATR at entry (used for trail)
        self.stop_distance = None    # 1R distance
        self.r_targets     = {}      # {1.0: price, 2.0: price, 3.0: price}
        self.current_stop  = None    # Ratcheted stop price
        self.partials_taken = 0
        self.initial_size  = 0
        self.high_water_mark = None  # For long runner trail
        self.low_water_mark  = None  # For short runner trail
        self._entry_context  = None

        # Bar tracking
        self._last_4h_len = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _atr_percentile_rank(self):
        """ATR percentile rank over squeeze_lookback bars on 4H."""
        current = self.atr4h[0]
        if current <= 0:
            return 50.0
        count_below = sum(
            1 for i in range(1, self.p.squeeze_lookback + 1)
            if self.atr4h[-i] < current
        )
        return (count_below / self.p.squeeze_lookback) * 100.0

    def _is_bias_bullish(self):
        if len(self.daily_ema) < 6:
            return False
        return (self.daily.close[0] > self.daily_ema[0] and
                self.daily_ema[0] > self.daily_ema[-5])

    def _is_bias_bearish(self):
        if len(self.daily_ema) < 6:
            return False
        return (self.daily.close[0] < self.daily_ema[0] and
                self.daily_ema[0] < self.daily_ema[-5])

    def _reset_squeeze(self):
        self.in_squeeze   = False
        self.sq_high      = None
        self.sq_low       = None
        self.sq_bar_count = 0

    def _reset_state(self):
        self.entry_price    = None
        self.position_type  = None
        self.entry_atr      = None
        self.stop_distance  = None
        self.r_targets      = {}
        self.current_stop   = None
        self.partials_taken = 0
        self.initial_size   = 0
        self.high_water_mark = None
        self.low_water_mark  = None
        self._entry_context  = None

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def next(self):
        # Exit checks every 15M bar while in position
        if self.position:
            self._check_exits()
            if not self.position:
                return

        # Warmup guard
        min_4h = max(self.p.level_lookback, self.p.squeeze_lookback, self.p.atr_period) + 5
        if len(self.data4h) < min_4h:
            return
        if len(self.daily) < self.p.daily_ema_period + 6:
            return

        # Entry logic: once per new 4H bar
        if len(self.data4h) == self._last_4h_len:
            return
        self._last_4h_len = len(self.data4h)

        self._check_squeeze_4h()

    # ------------------------------------------------------------------
    # Squeeze + entry logic
    # ------------------------------------------------------------------

    def _check_squeeze_4h(self):
        atr = self.atr4h[0]
        if atr <= 0:
            return

        pctile = self._atr_percentile_rank()
        h = self.data4h.high[0]
        l = self.data4h.low[0]

        if pctile < self.p.squeeze_pctile:
            # Accumulate squeeze range
            self.in_squeeze   = True
            self.sq_bar_count += 1
            self.sq_high = max(self.sq_high, h) if self.sq_high is not None else h
            self.sq_low  = min(self.sq_low,  l) if self.sq_low  is not None else l
            return

        if not self.in_squeeze:
            return  # Never entered a squeeze — nothing to do

        # Squeeze just ended — capture state and reset
        sq_high, sq_low, sq_bars = self.sq_high, self.sq_low, self.sq_bar_count
        self._reset_squeeze()

        if sq_high is None or sq_low is None or sq_high <= sq_low:
            return
        if self.position:
            return  # Already in a trade

        bias_bull = self._is_bias_bullish()
        bias_bear = self._is_bias_bearish()

        close4h    = self.data4h.close[0]
        level_dist = self.p.level_proximity_atr * atr

        # Long: bullish bias + squeeze formed near swing low (support) + breakout above squeeze
        # Use sq_low (where the squeeze was) to check proximity to structural level
        if (bias_bull and
                sq_low <= self.swing_low[0] + level_dist and
                close4h > sq_high):
            self._enter_long(close4h, atr, sq_bars, sq_high, sq_low)

        # Short: bearish bias + squeeze formed near swing high (resistance) + breakdown below squeeze
        elif (bias_bear and
              sq_high >= self.swing_high[0] - level_dist and
              close4h < sq_low):
            self._enter_short(close4h, atr, sq_bars, sq_high, sq_low)

    # ------------------------------------------------------------------
    # Entries
    # ------------------------------------------------------------------

    def _enter_long(self, price, atr, sq_bars, sq_high, sq_low):
        equity = self.broker.getvalue()
        self.stop_distance = atr * self.p.atr_stop_mult

        size = self.risk_mgr.calculate_position_size(equity, self.stop_distance)
        if size <= 0:
            return

        max_size = (equity * 100) / price * 0.95
        size = min(size, max_size)

        self.buy(size=size)
        self.entry_price    = price
        self.position_type  = 'long'
        self.entry_atr      = atr
        self.initial_size   = size
        self.partials_taken = 0
        self.high_water_mark = price

        self.r_targets    = self.risk_mgr.calculate_r_targets(price, self.stop_distance, 'long')
        self.current_stop = self.r_targets[-1]

        dt = self.data15.datetime.datetime(0)
        risk_amt = equity * self.risk_mgr.risk_pct
        print(f"[{dt}] LONG @ {price:.2f} | Size: {size:.4f} | Risk: ${risk_amt:.0f} | "
              f"Stop: {self.current_stop:.2f} | "
              f"1R: {self.r_targets.get(1.0, 0):.2f} | "
              f"2R: {self.r_targets.get(2.0, 0):.2f} | "
              f"3R: {self.r_targets.get(3.0, 0):.2f} | "
              f"sq_bars: {sq_bars} sq_range: {sq_high-sq_low:.2f}")

        self._entry_context = {
            "direction":     "long",
            "atr":           round(atr, 4),
            "stop_distance": round(self.stop_distance, 4),
            "risk_pct":      self.p.risk_pct,
            "position_size": round(size, 4),
            "squeeze_bars":  sq_bars,
            "sq_range":      round(sq_high - sq_low, 4),
        }

    def _enter_short(self, price, atr, sq_bars, sq_high, sq_low):
        equity = self.broker.getvalue()
        self.stop_distance = atr * self.p.atr_stop_mult

        size = self.risk_mgr.calculate_position_size(equity, self.stop_distance)
        if size <= 0:
            return

        max_size = (equity * 100) / price * 0.95
        size = min(size, max_size)

        self.sell(size=size)
        self.entry_price    = price
        self.position_type  = 'short'
        self.entry_atr      = atr
        self.initial_size   = size
        self.partials_taken = 0
        self.low_water_mark = price

        self.r_targets    = self.risk_mgr.calculate_r_targets(price, self.stop_distance, 'short')
        self.current_stop = self.r_targets[-1]

        dt = self.data15.datetime.datetime(0)
        risk_amt = equity * self.risk_mgr.risk_pct
        print(f"[{dt}] SHORT @ {price:.2f} | Size: {size:.4f} | Risk: ${risk_amt:.0f} | "
              f"Stop: {self.current_stop:.2f} | "
              f"1R: {self.r_targets.get(1.0, 0):.2f} | "
              f"2R: {self.r_targets.get(2.0, 0):.2f} | "
              f"3R: {self.r_targets.get(3.0, 0):.2f} | "
              f"sq_bars: {sq_bars} sq_range: {sq_high-sq_low:.2f}")

        self._entry_context = {
            "direction":     "short",
            "atr":           round(atr, 4),
            "stop_distance": round(self.stop_distance, 4),
            "risk_pct":      self.p.risk_pct,
            "position_size": round(size, 4),
            "squeeze_bars":  sq_bars,
            "sq_range":      round(sq_high - sq_low, 4),
        }

    # ------------------------------------------------------------------
    # Exits
    # ------------------------------------------------------------------

    def _check_exits(self):
        if self.entry_price is None or self.stop_distance is None:
            return
        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)
        if self.position_type == 'long':
            self._check_long_exits(current_price, dt)
        elif self.position_type == 'short':
            self._check_short_exits(current_price, dt)

    def _check_long_exits(self, current_price, dt):
        # Update HWM
        if self.high_water_mark is None or current_price > self.high_water_mark:
            self.high_water_mark = current_price

        # R-target partials: 30% at 1R, 30% at 2R, 30% at 3R
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

        # Runner trail activates only after all 3 partials
        if self.partials_taken >= 3:
            trail_stop = self.high_water_mark - self.entry_atr * self.p.atr_trail_mult
            effective_stop = max(self.current_stop, trail_stop)
        else:
            effective_stop = self.current_stop

        if current_price <= effective_stop:
            r_mult = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'long')
            if self.partials_taken == 0:
                reason = "STOP (-1R)"
            elif self.partials_taken >= 3:
                reason = f"RUNNER TRAIL (after 3R) | HWM: {self.high_water_mark:.2f}"
            else:
                reason = f"RATCHET STOP (after {self.partials_taken}R)"
            print(f"[{dt}] LONG {reason} @ {current_price:.2f} ({r_mult:+.1f}R)")
            self.close()
            self._reset_state()

    def _check_short_exits(self, current_price, dt):
        # Update LWM (falling price = favorable for shorts)
        if self.low_water_mark is None or current_price < self.low_water_mark:
            self.low_water_mark = current_price

        # R-target partials: 30% at 1R, 30% at 2R, 30% at 3R
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
                          f"(+{r_mult:.0f}R, covering {fraction:.0%}) | "
                          f"New stop: {self.current_stop:.2f}")
                    self.buy(size=partial_size)
                    return

        # Runner trail activates only after all 3 partials
        if self.partials_taken >= 3:
            trail_stop = self.low_water_mark + self.entry_atr * self.p.atr_trail_mult
            effective_stop = min(self.current_stop, trail_stop)
        else:
            effective_stop = self.current_stop

        if current_price >= effective_stop:
            r_mult = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'short')
            if self.partials_taken == 0:
                reason = "STOP (-1R)"
            elif self.partials_taken >= 3:
                reason = f"RUNNER TRAIL (after 3R) | LWM: {self.low_water_mark:.2f}"
            else:
                reason = f"RATCHET STOP (after {self.partials_taken}R)"
            print(f"[{dt}] SHORT {reason} @ {current_price:.2f} ({r_mult:+.1f}R)")
            self.close()
            self._reset_state()

    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = "BUY" if order.isbuy() else "SELL"
            print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}")
