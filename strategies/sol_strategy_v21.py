# strategies/sol_strategy_v21.py
"""
SolStrategy V21 - VWAP Mean Reversion (4H Rolling Window)
----------------------------------------------------------
Enters counter-trend when price reaches 1-2 SD from rolling VWAP on 4H,
then confirms reversal by closing back inside the band on the next 4H bar.

LONG entry (two-bar pattern on 4H):
- Bar[-1]: close <= lower_band (touch/cross below lower SD band)
- Bar[0]:  close >  lower_band (close back above — reversal confirmed)
- ATR/price in normal range (not flat, not explosive)
- No existing position

SHORT entry (mirror):
- Bar[-1]: close >= upper_band (touch/cross above upper SD band)
- Bar[0]:  close <  upper_band (close back below — reversal confirmed)
- Same ATR filter

Exits (mean-reversion optimised):
- 50% at 1R, stop → breakeven, ATR trail activates (5x ATR from HWM)
- 40% at 2R, stop → +1R, trail continues
- 10% runner: whichever of ratcheted stop / ATR trail is tighter

Risk Model:
- Stop = entry price ± (ATR * atr_stop_mult)  → defines 1R
- Position sized so stop = risk_per_trade_pct of equity

Data feeds (expected index order):
  0 → 15m (base — precise entry/exit prices)
  1 → 1h  (unused)
  2 → 4h  (main signal logic)
  3 → weekly (unused)
  4 → daily (unused)
"""

import math

import backtrader as bt
import backtrader.indicators as btind
from risk_manager import RiskManager


class VWAPBands(bt.Indicator):
    """
    Rolling VWAP with standard deviation bands.

    Computes over a sliding window of N bars:
        typical_price  = (high + low + close) / 3
        vwap           = sum(tp * volume, N) / sum(volume, N)
        variance       = sum((close - vwap)^2, N) / N
        std_dev        = sqrt(variance)
        upper_band     = vwap + sd_mult * std_dev
        lower_band     = vwap - sd_mult * std_dev

    All computation done in next() to guard against zero-volume bars.
    """
    lines = ('vwap', 'upper', 'lower', 'std_dev')
    params = (('period', 30), ('sd_mult', 1.5))

    def __init__(self):
        self.addminperiod(self.p.period)

    def next(self):
        period = self.p.period
        highs  = self.data.high.get(size=period)
        lows   = self.data.low.get(size=period)
        closes = self.data.close.get(size=period)
        vols   = self.data.volume.get(size=period)

        sum_vol = sum(vols)
        if sum_vol <= 0:
            # No volume — carry forward previous values
            self.l.vwap[0]    = self.l.vwap[-1]
            self.l.upper[0]   = self.l.upper[-1]
            self.l.lower[0]   = self.l.lower[-1]
            self.l.std_dev[0] = self.l.std_dev[-1]
            return

        tpv_sum = sum((h + l + c) / 3.0 * v for h, l, c, v in zip(highs, lows, closes, vols))
        vwap = tpv_sum / sum_vol

        variance = sum((c - vwap) ** 2 for c in closes) / period
        sd = math.sqrt(max(variance, 0.0))

        self.l.vwap[0]    = vwap
        self.l.std_dev[0] = sd
        self.l.upper[0]   = vwap + self.p.sd_mult * sd
        self.l.lower[0]   = vwap - self.p.sd_mult * sd


class SolStrategyV21(bt.Strategy):
    params = (
        # VWAP window (4H bars; 30 bars ≈ 5 trading days)
        ('vwap_period', 30),
        # SD level to trigger the setup (touch)
        ('sd_entry', 1.5),
        # Max SD — ignore if price is too extended (likely trending)
        ('sd_max', 2.5),
        # ATR settings
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),       # Stop distance = ATR * this (= 1R)
        ('atr_trailing_mult', 5.0),   # Runner trail = ATR * this from HWM (V19 style, active from 1R)
        # Volatility range filter (% of price)
        ('atr_vol_min_pct', 0.5),     # Filter flat/dead markets
        ('atr_vol_max_pct', 8.0),     # Filter explosive/trending markets
        # Risk management
        ('risk_per_trade_pct', 3.0),
    )

    def __init__(self):
        self.data15 = self.datas[0]   # 15m: precise entry/exit
        self.data4h = self.datas[2]   # 4H: signals

        # VWAP bands (entry SD level)
        self.vwap_entry = VWAPBands(
            self.data4h,
            period=self.p.vwap_period,
            sd_mult=self.p.sd_entry,
        )
        # VWAP bands (max SD level — for sd_max filter)
        self.vwap_max = VWAPBands(
            self.data4h,
            period=self.p.vwap_period,
            sd_mult=self.p.sd_max,
        )

        # ATR on 4H for stop sizing and volatility filter
        self.atr = btind.ATR(self.data4h, period=self.p.atr_period)

        # Risk manager — 50% at 1R, 40% at 2R, 10% runner
        self.risk_mgr = RiskManager(
            risk_pct=self.p.risk_per_trade_pct,
            partial_schedule=[(1.0, 0.50), (2.0, 0.40)],
        )

        # ── Position state ──────────────────────────────────────────────────
        self.position_type = None     # 'long' or 'short'
        self.entry_price = None
        self.entry_atr = None
        self.stop_distance = None     # 1R distance
        self.r_targets = {}           # {r_mult: price}
        self.current_stop = None      # Ratcheting stop
        self.partials_taken = 0
        self.initial_size = 0
        self.high_water_mark = None   # For long runner trail
        self.low_water_mark = None    # For short runner trail

        # 4H bar counter (detect new bars)
        self.last_4h_len = 0

    # ──────────────────────────────────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────────────────────────────────

    def next(self):
        # Exit checks run every 15m bar for precision
        if self.position:
            self._check_exits()
            if not self.position:
                return

        # Need enough history for indicators to warm up
        min_bars = self.p.vwap_period + self.p.atr_period + 2
        if len(self.data4h) < min_bars:
            return

        # Entry logic only on new 4H bar
        if len(self.data4h) == self.last_4h_len:
            return
        self.last_4h_len = len(self.data4h)

        if self.position:
            return  # Already in position — exits handled above

        dt = self.data4h.datetime.datetime(0)
        self._check_entry(dt)

    # ──────────────────────────────────────────────────────────────────────────
    # Entry detection
    # ──────────────────────────────────────────────────────────────────────────

    def _check_entry(self, dt):
        """Detect two-bar reversal pattern at SD bands on new 4H bar."""
        # Need at least 2 bars of band history
        if len(self.vwap_entry) < 2:
            return

        atr = self.atr[0]
        price = self.data4h.close[0]
        if atr <= 0 or price <= 0:
            return

        # Volatility filter: skip if ATR% is outside normal range
        atr_pct = (atr / price) * 100
        if atr_pct < self.p.atr_vol_min_pct or atr_pct > self.p.atr_vol_max_pct:
            return

        prev_close = self.data4h.close[-1]
        curr_close = self.data4h.close[0]

        lower_entry = self.vwap_entry.lower[0]
        upper_entry = self.vwap_entry.upper[0]
        lower_prev  = self.vwap_entry.lower[-1]
        upper_prev  = self.vwap_entry.upper[-1]

        # sd_max guard: ignore if price was too extended (sd_max bands)
        lower_max = self.vwap_max.lower[0]
        upper_max = self.vwap_max.upper[0]

        # ── Long: prev bar touched/crossed below lower_entry band ──────────
        if prev_close <= lower_prev and curr_close > lower_entry:
            # Price not absurdly extended (between sd_entry and sd_max is fine;
            # if it went past sd_max we still allow — it's a stronger reversal)
            print(f"[{dt}] LONG SETUP: prev_close={prev_close:.4f} <= lower={lower_prev:.4f}, "
                  f"curr_close={curr_close:.4f} > lower={lower_entry:.4f} | "
                  f"ATR%={atr_pct:.2f}")
            self._enter_long(dt, atr, curr_close)
            return

        # ── Short: prev bar touched/crossed above upper_entry band ──────────
        if prev_close >= upper_prev and curr_close < upper_entry:
            print(f"[{dt}] SHORT SETUP: prev_close={prev_close:.4f} >= upper={upper_prev:.4f}, "
                  f"curr_close={curr_close:.4f} < upper={upper_entry:.4f} | "
                  f"ATR%={atr_pct:.2f}")
            self._enter_short(dt, atr, curr_close)

    # ──────────────────────────────────────────────────────────────────────────
    # Entry execution
    # ──────────────────────────────────────────────────────────────────────────

    def _enter_long(self, dt, atr, signal_price):
        """Execute long entry with R-based position sizing."""
        price = self.data15.close[0]
        equity = self.broker.getvalue()

        self.stop_distance = atr * self.p.atr_stop_mult

        size = self.risk_mgr.calculate_position_size(equity, self.stop_distance)
        if size <= 0:
            return

        # Cap at 100x leverage
        max_size = (equity * 100) / price
        size = min(size, max_size * 0.95)

        self.buy(size=size)
        self.position_type = 'long'
        self.entry_price = price
        self.entry_atr = atr
        self.initial_size = size
        self.partials_taken = 0
        self.high_water_mark = price

        self.r_targets = self.risk_mgr.calculate_r_targets(price, self.stop_distance, 'long')
        self.current_stop = self.r_targets[-1]

        risk_amt = equity * self.risk_mgr.risk_pct
        vwap_val = self.vwap_entry.vwap[0]
        vwap_dist_pct = (price - vwap_val) / vwap_val * 100 if vwap_val > 0 else 0

        print(f"[{dt}] LONG ENTRY @ {price:.4f} | "
              f"Size: {size:.4f} | Risk: ${risk_amt:.0f} ({self.p.risk_per_trade_pct}%) | "
              f"Stop: {self.current_stop:.4f} | "
              f"1R: {self.r_targets.get(1.0, 0):.4f} (50%) | "
              f"2R: {self.r_targets.get(2.0, 0):.4f} (40%) | "
              f"VWAP dist: {vwap_dist_pct:+.2f}%")

        self._entry_context = {
            "direction": "long",
            "atr": round(atr, 4),
            "vwap_dist_pct": round(vwap_dist_pct, 2),
            "stop_distance": round(self.stop_distance, 4),
            "risk_pct": self.p.risk_per_trade_pct,
            "position_size": round(size, 4),
        }

    def _enter_short(self, dt, atr, signal_price):
        """Execute short entry with R-based position sizing."""
        price = self.data15.close[0]
        equity = self.broker.getvalue()

        self.stop_distance = atr * self.p.atr_stop_mult

        size = self.risk_mgr.calculate_position_size(equity, self.stop_distance)
        if size <= 0:
            return

        max_size = (equity * 100) / price
        size = min(size, max_size * 0.95)

        self.sell(size=size)
        self.position_type = 'short'
        self.entry_price = price
        self.entry_atr = atr
        self.initial_size = size
        self.partials_taken = 0
        self.low_water_mark = price

        self.r_targets = self.risk_mgr.calculate_r_targets(price, self.stop_distance, 'short')
        self.current_stop = self.r_targets[-1]

        risk_amt = equity * self.risk_mgr.risk_pct
        vwap_val = self.vwap_entry.vwap[0]
        vwap_dist_pct = (price - vwap_val) / vwap_val * 100 if vwap_val > 0 else 0

        print(f"[{dt}] SHORT ENTRY @ {price:.4f} | "
              f"Size: {size:.4f} | Risk: ${risk_amt:.0f} ({self.p.risk_per_trade_pct}%) | "
              f"Stop: {self.current_stop:.4f} | "
              f"1R: {self.r_targets.get(1.0, 0):.4f} (50%) | "
              f"2R: {self.r_targets.get(2.0, 0):.4f} (40%) | "
              f"VWAP dist: {vwap_dist_pct:+.2f}%")

        self._entry_context = {
            "direction": "short",
            "atr": round(atr, 4),
            "vwap_dist_pct": round(vwap_dist_pct, 2),
            "stop_distance": round(self.stop_distance, 4),
            "risk_pct": self.p.risk_per_trade_pct,
            "position_size": round(size, 4),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Exit logic (R-based — identical pattern to v8_fast)
    # ──────────────────────────────────────────────────────────────────────────

    def _check_exits(self):
        if self.entry_price is None or self.stop_distance is None:
            return
        if self.position_type == 'long':
            self._check_long_exits()
        elif self.position_type == 'short':
            self._check_short_exits()

    def _check_long_exits(self):
        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        self.high_water_mark = max(self.high_water_mark, current_price)

        # R-target partials (50% at 1R, 40% at 2R)
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
                    print(f"[{dt}] LONG PARTIAL {self.partials_taken}/2 @ {current_price:.4f} "
                          f"(+{r_mult:.0f}R, selling {fraction:.0%}) | "
                          f"New stop: {self.current_stop:.4f}")
                    self.sell(size=partial_size)
                    return

        # Effective stop = ratcheted stop, plus ATR trail from HWM once 1R is hit
        effective_stop = self.current_stop
        if self.partials_taken >= 1:
            trail_stop = self.high_water_mark - self.entry_atr * self.p.atr_trailing_mult
            effective_stop = max(self.current_stop, trail_stop)

        if current_price <= effective_stop:
            pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
            r_val = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'long')
            if self.partials_taken == 0:
                reason = "LONG STOP"
            elif self.partials_taken >= 2:
                reason = f"LONG RUNNER EXIT (after 2R)"
            else:
                reason = f"LONG RATCHET STOP (after 1R)"
            print(f"[{dt}] {reason} @ {current_price:.4f} ({pnl_pct:+.1f}%, {r_val:+.1f}R)")
            self.sell(size=self.position.size)
            self._reset_state()

    def _check_short_exits(self):
        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        self.low_water_mark = min(self.low_water_mark, current_price)

        # R-target partials (50% at 1R, 40% at 2R)
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
                    print(f"[{dt}] SHORT PARTIAL {self.partials_taken}/2 @ {current_price:.4f} "
                          f"(+{r_mult:.0f}R, buying {fraction:.0%}) | "
                          f"New stop: {self.current_stop:.4f}")
                    self.buy(size=partial_size)
                    return

        # Effective stop = ratcheted stop, plus ATR trail from LWM once 1R is hit
        effective_stop = self.current_stop
        if self.partials_taken >= 1:
            trail_stop = self.low_water_mark + self.entry_atr * self.p.atr_trailing_mult
            effective_stop = min(self.current_stop, trail_stop)

        if current_price >= effective_stop:
            pnl_pct = (self.entry_price - current_price) / self.entry_price * 100
            r_val = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'short')
            if self.partials_taken == 0:
                reason = "SHORT STOP"
            elif self.partials_taken >= 2:
                reason = f"SHORT RUNNER EXIT (after 2R)"
            else:
                reason = f"SHORT RATCHET STOP (after 1R)"
            print(f"[{dt}] {reason} @ {current_price:.4f} ({pnl_pct:+.1f}%, {r_val:+.1f}R)")
            self.buy(size=abs(self.position.size))
            self._reset_state()

    def _reset_state(self):
        self.position_type = None
        self.entry_price = None
        self.entry_atr = None
        self.stop_distance = None
        self.r_targets = {}
        self.current_stop = None
        self.partials_taken = 0
        self.initial_size = 0
        self.high_water_mark = None
        self.low_water_mark = None

    # ──────────────────────────────────────────────────────────────────────────
    # Order / trade tracking
    # ──────────────────────────────────────────────────────────────────────────

    def notify_order(self, order):
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f"Order {order.status}: {order.info}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"TRADE CLOSED: PnL={trade.pnl:.2f} (net={trade.pnlcomm:.2f})")
