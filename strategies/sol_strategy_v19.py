# strategies/sol_strategy_v19.py
"""
SolStrategy v19 - Volatility Squeeze Breakout (3 Params, Long + Short)
----------------------------------------------------------------------
Detect when ATR contracts to a low percentile rank (squeeze), track the
squeeze range, then enter when price breaks out of the range.
High R-expectancy because squeezes create tight stops (low ATR = small 1R)
and post-squeeze moves tend to be directional (high R potential).

Core Concept:
- 1H: ATR percentile rank for squeeze detection + breakout entries
- 15m: R-based partial exits + ATR trailing stop after any partial

Entry Logic (on each new 1H bar):
1. ATR percentile rank over `lookback` bars
2. rank < squeeze_pctile  -->  "in squeeze", update squeeze_high/squeeze_low
3. When rank rises above threshold (squeeze ends):
   - Close > squeeze_high  -->  LONG
   - Close < squeeze_low   -->  SHORT

Regime Filter:
- Allows high_vol and normal_vol regimes
- Blocks only low_vol (4H ATR pctile < 25)
- normal_vol entries use 0.75x atr_mult for tighter R-targets

Exit Logic (every 15m bar):
- 1R = ATR_at_entry * effective_atr_mult (scaled by vol regime)
- Partials: 30% at 1R, 30% at 2R, 30% at 3R
- After any partial: ATR trail from HWM (floor = ratchet stop)
- Trail remaining 10% runner with same ATR trailing stop

Data feeds (expected index order):
  0 -> 15m (base, exit checking every bar)
  1 -> 1h  (squeeze detection, entry signals, ATR)
  2 -> 4h  (unused)
  3 -> weekly (unused)
  4 -> daily (unused)
"""

import backtrader as bt
import backtrader.indicators as btind
from risk_manager import RiskManager
from regime import MarketRegime


class SolStrategyV19(bt.Strategy):
    params = (
        # Shared squeeze detection
        ('lookback', 102),          # ATR percentile rank lookback (1H bars)
        ('squeeze_pctile', 25),     # Percentile threshold to qualify as squeeze
        # Direction-specific ATR multipliers (1R distance AND runner trail)
        ('atr_mult_long', 3.25),    # Long: walk-forward validated
        ('atr_mult_short', 8.0),    # Short: from 100-trial combined run (atr_mult capped at 8.0)
        # Fixed
        ('atr_period', 14),         # ATR calc period on 1H
        ('risk_per_trade_pct', 3.0),  # Risk 3% of account at stop loss
    )

    def __init__(self):
        # Data feeds
        self.data15 = self.datas[0]   # 15m: exit checking every bar
        self.data1h = self.datas[1]   # 1h: squeeze detection, ATR
        self.data4h = self.datas[2]   # 4h: volatility regime
        self.data_daily = self.datas[4]  # daily: trend regime

        # 1H Indicators
        self.atr_1h = btind.ATR(self.data1h, period=self.p.atr_period)

        # Regime classifier — only allow high_vol entries
        self.regime = MarketRegime(self.data_daily, self.data4h)

        # Risk manager — default 30/30/30/10 with runner
        self.risk_mgr = RiskManager(risk_pct=self.p.risk_per_trade_pct)

        # Squeeze state
        self.in_squeeze = False
        self.squeeze_high = None
        self.squeeze_low = None

        # Position tracking
        self.entry_price = None
        self.position_type = None       # 'long' or 'short'
        self.entry_atr = None           # 1H ATR snapshot at entry
        self.stop_distance = None       # 1R distance
        self.r_targets = {}             # {-1: stop, 1: 1R, 2: 2R, 3: 3R}
        self.current_stop = None        # Ratcheted stop price
        self.partials_taken = 0         # 0, 1, 2, or 3
        self.initial_size = 0           # Original position size
        self.high_water_mark = None     # Unused (no runner), kept for state reset
        self.low_water_mark = None      # Unused (no runner), kept for state reset
        self.effective_atr_mult = None  # Vol-scaled atr_mult (0.75x for normal_vol)

        # Bar tracking for new bar detection
        self.last_1h_len = 0
        self.last_4h_len = 0

    def _atr_percentile_rank(self):
        """Calculate ATR percentile rank over lookback bars on 1H."""
        current_atr = self.atr_1h[0]
        if current_atr <= 0:
            return 50.0  # Neutral if ATR is invalid

        lookback = self.p.lookback
        count_below = 0
        for i in range(1, lookback + 1):
            if self.atr_1h[-i] < current_atr:
                count_below += 1

        return (count_below / lookback) * 100.0

    def next(self):
        # Need enough data for ATR + lookback
        min_bars = self.p.atr_period + self.p.lookback + 2
        if len(self.data1h) < min_bars:
            return

        # Keep regime classifier's ATR history populated on every new 4H bar
        if len(self.data4h) > self.last_4h_len:
            self.last_4h_len = len(self.data4h)
            try:
                self.regime.classify()
            except Exception:
                pass

        # If in position, check exits on every 15m bar
        if self.position:
            self._check_exits()

        # Only check squeeze/entries on new 1H bar
        if len(self.data1h) == self.last_1h_len:
            return
        self.last_1h_len = len(self.data1h)

        self._check_squeeze()

    def _check_squeeze(self):
        """Detect squeeze state and check for breakout entries."""
        pctile_rank = self._atr_percentile_rank()
        close_1h = self.data1h.close[0]
        high_1h = self.data1h.high[0]
        low_1h = self.data1h.low[0]
        atr = self.atr_1h[0]

        if atr <= 0:
            return

        if pctile_rank < self.p.squeeze_pctile:
            # In squeeze: update range
            self.in_squeeze = True
            if self.squeeze_high is None or high_1h > self.squeeze_high:
                self.squeeze_high = high_1h
            if self.squeeze_low is None or low_1h < self.squeeze_low:
                self.squeeze_low = low_1h
            return

        # Rank rose above threshold: check if we were in a squeeze
        if not self.in_squeeze:
            return

        # Squeeze just ended - check for breakout
        sq_high = self.squeeze_high
        sq_low = self.squeeze_low

        # Reset squeeze state regardless of outcome
        self._reset_squeeze()

        # Skip degenerate ranges (doji/flat)
        if sq_high is None or sq_low is None or sq_high <= sq_low:
            return

        # Block only low_vol — normal_vol re-enabled with tighter targets
        try:
            regime_info = self.regime.classify()
            if regime_info.get('volatility') == 'low_vol':
                dt = self.data15.datetime.datetime(0)
                print(f"[{dt}] BLOCKED — {regime_info.get('volatility')} regime ({regime_info.get('regime')})")
                return
        except Exception:
            regime_info = None  # If regime classifier fails, allow the trade

        if self.position:
            return

        # Long breakout: close above squeeze high
        if close_1h > sq_high:
            self._enter_long(close_1h, atr, regime_info)
            return

        # Short breakout: close below squeeze low
        if close_1h < sq_low:
            self._enter_short(close_1h, atr, regime_info)

    def _enter_long(self, price, atr, regime_info=None):
        """Enter long position with R-based sizing. Normal_vol uses 0.75x atr_mult."""
        equity = self.broker.getvalue()
        vol_regime = regime_info.get('volatility', 'high_vol') if regime_info else 'high_vol'
        self.effective_atr_mult = self.p.atr_mult_long * (0.75 if vol_regime == 'normal_vol' else 1.0)
        self.stop_distance = atr * self.effective_atr_mult

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
        vol_tag = f"[{vol_regime}]" + (f" atr_mult={self.effective_atr_mult:.2f}" if vol_regime == 'normal_vol' else "")
        print(f"[{dt}] LONG {vol_tag} @ {price:.2f} | "
              f"Size: {size:.4f} | Risk: ${risk_amt:.0f} ({self.p.risk_per_trade_pct}%) | "
              f"Stop: {self.current_stop:.2f} (-1R) | "
              f"1R: {self.r_targets.get(1.0, 0):.2f} | "
              f"2R: {self.r_targets.get(2.0, 0):.2f} | "
              f"3R: {self.r_targets.get(3.0, 0):.2f}")

        self._entry_context = {
            "atr": round(atr, 4),
            "direction": "long",
            "stop_distance": round(self.stop_distance, 4),
            "risk_pct": self.p.risk_per_trade_pct,
            "position_size": round(size, 4),
        }

    def _enter_short(self, price, atr, regime_info=None):
        """Enter short position with R-based sizing. Normal_vol uses 0.75x atr_mult_short."""
        equity = self.broker.getvalue()
        vol_regime = regime_info.get('volatility', 'high_vol') if regime_info else 'high_vol'
        self.effective_atr_mult = self.p.atr_mult_short * (0.75 if vol_regime == 'normal_vol' else 1.0)
        self.stop_distance = atr * self.effective_atr_mult

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

        # Calculate R-targets for short
        self.r_targets = self.risk_mgr.calculate_r_targets(price, self.stop_distance, 'short')
        self.current_stop = self.r_targets[-1]

        risk_amt = equity * self.risk_mgr.risk_pct
        dt = self.data15.datetime.datetime(0)
        vol_tag = f"[{vol_regime}]" + (f" atr_mult={self.effective_atr_mult:.2f}" if vol_regime == 'normal_vol' else "")
        print(f"[{dt}] SHORT {vol_tag} @ {price:.2f} | "
              f"Size: {size:.4f} | Risk: ${risk_amt:.0f} ({self.p.risk_per_trade_pct}%) | "
              f"Stop: {self.current_stop:.2f} (-1R) | "
              f"1R: {self.r_targets.get(1.0, 0):.2f} | "
              f"2R: {self.r_targets.get(2.0, 0):.2f} | "
              f"3R: {self.r_targets.get(3.0, 0):.2f}")

        self._entry_context = {
            "atr": round(atr, 4),
            "direction": "short",
            "stop_distance": round(self.stop_distance, 4),
            "risk_pct": self.p.risk_per_trade_pct,
            "position_size": round(size, 4),
        }

    def _check_exits(self):
        """Check R-based exits on every 15m bar (long-only)."""
        if self.entry_price is None or self.stop_distance is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        if self.position_type == 'long':
            self._check_long_exits(current_price, dt)
        elif self.position_type == 'short':
            self._check_short_exits(current_price, dt)

    def _check_long_exits(self, current_price, dt):
        """Check exits for long position with ATR trail after any partial."""
        # Update high water mark
        if self.high_water_mark is None or current_price > self.high_water_mark:
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

        # Compute effective stop: ATR trail from HWM after any partial, ratchet floor always applies
        if self.partials_taken >= 1:
            trail_distance = self.entry_atr * self.effective_atr_mult
            trail_stop = self.high_water_mark - trail_distance
            effective_stop = max(self.current_stop, trail_stop)
        else:
            effective_stop = self.current_stop

        if current_price <= effective_stop:
            pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
            r_mult = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'long')
            if self.partials_taken == 0:
                reason = "STOP (-1R)"
            elif self.partials_taken >= 3:
                reason = f"RUNNER TRAIL (after {self.partials_taken}R)"
            else:
                reason = f"ATR TRAIL (after {self.partials_taken}R)"
            print(f"[{dt}] LONG {reason} @ {current_price:.2f} ({pnl_pct:+.2f}%, {r_mult:+.1f}R)"
                  + (f" | HWM: {self.high_water_mark:.2f}" if self.partials_taken >= 1 else ""))
            self.close()
            self._reset_state()
            return

    def _check_short_exits(self, current_price, dt):
        """Check exits for short position with ATR trail after any partial."""
        # Update low water mark (price moving down = good for shorts)
        if self.low_water_mark is None or current_price < self.low_water_mark:
            self.low_water_mark = current_price

        # Check R-target partials (1R, 2R, 3R — price moving DOWN)
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

        # Compute effective stop: ATR trail from LWM after any partial
        if self.partials_taken >= 1:
            trail_distance = self.entry_atr * self.effective_atr_mult
            trail_stop = self.low_water_mark + trail_distance
            effective_stop = min(self.current_stop, trail_stop)
        else:
            effective_stop = self.current_stop

        # For shorts, stopped out when price goes ABOVE stop
        if current_price >= effective_stop:
            pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
            r_mult = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'short')
            if self.partials_taken == 0:
                reason = "STOP (-1R)"
            elif self.partials_taken >= 3:
                reason = f"RUNNER TRAIL (after {self.partials_taken}R)"
            else:
                reason = f"ATR TRAIL (after {self.partials_taken}R)"
            print(f"[{dt}] SHORT {reason} @ {current_price:.2f} ({pnl_pct:+.2f}%, {r_mult:+.1f}R)"
                  + (f" | LWM: {self.low_water_mark:.2f}" if self.partials_taken >= 1 else ""))
            self.close()
            self._reset_state()
            return

    def _close_position(self, reason):
        """Close current position with logging."""
        if self.entry_price is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
        r_mult = self.risk_mgr.calculate_r_multiple(
            self.entry_price, current_price, self.stop_distance, 'long') if self.stop_distance else 0
        print(f"[{dt}] LONG {reason} @ {current_price:.2f} ({pnl_pct:+.2f}%, {r_mult:+.1f}R)")

        self.close()
        self._reset_state()

    def _reset_squeeze(self):
        """Reset squeeze tracking state."""
        self.in_squeeze = False
        self.squeeze_high = None
        self.squeeze_low = None

    def _reset_state(self):
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
        self.effective_atr_mult = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = "BUY" if order.isbuy() else "SELL"
            print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}")
