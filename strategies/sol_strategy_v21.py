# strategies/sol_strategy_v21.py
"""
SolStrategy V21 - VWAP Mean Reversion (4H Rolling Window)
----------------------------------------------------------
Enters counter-trend when price reaches the SD band on 4H and confirms
reversal by closing back inside the band on the next 4H bar.

LONG entry (two-bar pattern on 4H):
- Bar[-1]: close <= lower_band  (touch/cross below lower SD band)
- Bar[0]:  close >  lower_band  (close back above — reversal confirmed)
- ATR/price in normal range (not flat, not explosive)
- VWAP distance >= min_vwap_mult × ATR (VWAP is a meaningful target distance)
- Regime filter: no longs in confirmed downtrends

SHORT entry (mirror):
- Bar[-1]: close >= upper_band
- Bar[0]:  close <  upper_band
- Regime filter: no shorts in confirmed uptrends

Stop management (V19-style):
- Stop = entry ± ATR × atr_stop_mult  (= 1R)
- At +0.75R: stop moves to -0.5R  (early cushion, reduces full-stop frequency)
- At +1R:    stop moves to BE, 5× ATR trail from HWM starts
- Trail continues until VWAP is hit

Exits:
- 90% at VWAP (wick-based: high/low reaches VWAP) — primary mean reversion target
- 10% runner continues on ATR trail already active from 1R

Win condition: wick touches VWAP target (mirrors limit order fill at exchange)

Data feeds (expected index order):
  0 → 15m   (base — precise entry/exit prices)
  1 → 1h    (unused)
  2 → 4h    (main signal logic)
  3 → weekly (unused)
  4 → daily  (regime: EMA 21)
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
        # VWAP window (4H bars)
        ('vwap_period', 50),
        # SD level to trigger the setup (touch/close at band)
        ('sd_entry', 2.5),
        # ATR settings
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),       # Stop distance = ATR × this (= 1R)
        ('atr_trailing_mult', 5.0),   # Trail = ATR × this from HWM (active from 1R)
        # VWAP distance filter: only enter if VWAP is at least this many ATRs away
        # Prevents entries in calm markets where VWAP is trivially close
        ('min_vwap_mult', 2.0),
        # V19-style early stop management
        ('early_be_trig', 0.75),      # Trigger early stop move at 0.75R (0–1)
        ('early_be_dest', 0.5),       # Move stop to -dest×1R (0.5 = halfway to entry)
        # Volatility range filter (% of price)
        ('atr_vol_min_pct', 0.5),
        ('atr_vol_max_pct', 6.0),
        # Regime filter: block counter-trend mean reversion trades
        ('regime_filter', True),
        # Risk management
        ('risk_per_trade_pct', 3.0),
    )

    def __init__(self):
        self.data15    = self.datas[0]   # 15m: precise entry/exit
        self.data4h    = self.datas[2]   # 4H: signals
        self.data_daily = self.datas[4]  # Daily: regime filter (EMA 21)

        # VWAP bands on 4H
        self.vwap_bands = VWAPBands(
            self.data4h,
            period=self.p.vwap_period,
            sd_mult=self.p.sd_entry,
        )

        # ATR on 4H for stop sizing and volatility filter
        self.atr = btind.ATR(self.data4h, period=self.p.atr_period)

        # Daily EMA for regime classification
        self.daily_ema = btind.EMA(self.data_daily.close, period=21)

        # Risk manager (position sizing only — partials handled manually)
        self.risk_mgr = RiskManager(
            risk_pct=self.p.risk_per_trade_pct,
            partial_schedule=[],
        )

        # ── Position state ──────────────────────────────────────────────────
        self.position_type   = None    # 'long' or 'short'
        self.entry_price     = None
        self.entry_atr       = None
        self.stop_distance   = None    # 1R distance (ATR × stop_mult)
        self.vwap_target     = None    # VWAP at entry — 90% exit target
        self.current_stop    = None    # Ratcheting stop
        self.early_be_done   = False   # 0.75R early stop move done
        self.one_r_hit       = False   # 1R crossed (trail/BE active)
        self.vwap_hit        = False   # VWAP exit taken (90% out)
        self.initial_size    = 0
        self.high_water_mark = None
        self.low_water_mark  = None

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

        # Wait for indicators to warm up
        min_bars = self.p.vwap_period + self.p.atr_period + 2
        if len(self.data4h) < min_bars:
            return

        # Entry logic only on new 4H bar
        if len(self.data4h) == self.last_4h_len:
            return
        self.last_4h_len = len(self.data4h)

        if self.position:
            return

        dt = self.data4h.datetime.datetime(0)
        self._check_entry(dt)

    # ──────────────────────────────────────────────────────────────────────────
    # Regime classification
    # ──────────────────────────────────────────────────────────────────────────

    def _get_regime(self):
        """
        Classify market regime using daily EMA(21).
        Returns 'uptrend', 'downtrend', or 'ranging'.
        Uptrend:   EMA sloping up  AND daily close > EMA
        Downtrend: EMA sloping down AND daily close < EMA
        """
        if len(self.daily_ema) < 6:
            return 'ranging'
        ema_now    = self.daily_ema[0]
        ema_5d_ago = self.daily_ema[-5]
        daily_close = self.data_daily.close[0]
        if ema_5d_ago <= 0:
            return 'ranging'
        ema_slope_pct = (ema_now - ema_5d_ago) / ema_5d_ago * 100
        if ema_slope_pct > 0 and daily_close > ema_now:
            return 'uptrend'
        elif ema_slope_pct < 0 and daily_close < ema_now:
            return 'downtrend'
        return 'ranging'

    # ──────────────────────────────────────────────────────────────────────────
    # Entry detection
    # ──────────────────────────────────────────────────────────────────────────

    def _check_entry(self, dt):
        """Detect two-bar reversal pattern at SD bands on new 4H bar."""
        if len(self.vwap_bands) < 2:
            return

        atr   = self.atr[0]
        price = self.data4h.close[0]
        if atr <= 0 or price <= 0:
            return

        # Volatility filter
        atr_pct = (atr / price) * 100
        if atr_pct < self.p.atr_vol_min_pct or atr_pct > self.p.atr_vol_max_pct:
            return

        vwap_val   = self.vwap_bands.vwap[0]
        lower_band = self.vwap_bands.lower[0]
        upper_band = self.vwap_bands.upper[0]
        lower_prev = self.vwap_bands.lower[-1]
        upper_prev = self.vwap_bands.upper[-1]
        prev_close = self.data4h.close[-1]
        curr_close = self.data4h.close[0]

        if vwap_val <= 0:
            return

        # VWAP distance filter: skip if VWAP is too close (calm market / small extension)
        vwap_dist = abs(curr_close - vwap_val)
        if vwap_dist < atr * self.p.min_vwap_mult:
            return

        # Regime filter (direction-aware — mean reversion logic)
        regime = self._get_regime() if self.p.regime_filter else 'ranging'

        # ── Long: prev bar closed below lower band, current closes back above ──
        if prev_close <= lower_prev and curr_close > lower_band:
            if regime == 'downtrend':
                # Block counter-trend longs in downtrend — likely to continue lower
                return
            print(f"[{dt}] LONG SETUP: prev_close={prev_close:.4f} <= lower={lower_prev:.4f}, "
                  f"curr={curr_close:.4f} > lower={lower_band:.4f} | "
                  f"ATR%={atr_pct:.2f}, regime={regime}, "
                  f"VWAP_dist={vwap_dist/atr:.1f}×ATR")
            self._enter_long(dt, atr, vwap_val)
            return

        # ── Short: prev bar closed above upper band, current closes back below ──
        if prev_close >= upper_prev and curr_close < upper_band:
            if regime == 'uptrend':
                # Block counter-trend shorts in uptrend — likely to continue higher
                return
            print(f"[{dt}] SHORT SETUP: prev_close={prev_close:.4f} >= upper={upper_prev:.4f}, "
                  f"curr={curr_close:.4f} < upper={upper_band:.4f} | "
                  f"ATR%={atr_pct:.2f}, regime={regime}, "
                  f"VWAP_dist={vwap_dist/atr:.1f}×ATR")
            self._enter_short(dt, atr, vwap_val)

    # ──────────────────────────────────────────────────────────────────────────
    # Entry execution
    # ──────────────────────────────────────────────────────────────────────────

    def _enter_long(self, dt, atr, vwap_val):
        price  = self.data15.close[0]
        equity = self.broker.getvalue()

        self.stop_distance = atr * self.p.atr_stop_mult
        size = self.risk_mgr.calculate_position_size(equity, self.stop_distance)
        if size <= 0:
            return

        max_size = (equity * 100) / price
        size = min(size, max_size * 0.95)

        self.buy(size=size)
        self.position_type   = 'long'
        self.entry_price     = price
        self.entry_atr       = atr
        self.vwap_target     = vwap_val
        self.initial_size    = size
        self.current_stop    = price - self.stop_distance
        self.early_be_done   = False
        self.one_r_hit       = False
        self.vwap_hit        = False
        self.high_water_mark = price

        risk_amt      = equity * self.risk_mgr.risk_pct
        vwap_dist_pct = (price - vwap_val) / vwap_val * 100
        vwap_r        = abs(price - vwap_val) / self.stop_distance

        print(f"[{dt}] LONG ENTRY @ {price:.4f} | "
              f"Size: {size:.4f} | Risk: ${risk_amt:.0f} ({self.p.risk_per_trade_pct}%) | "
              f"Stop: {self.current_stop:.4f} | "
              f"VWAP target: {vwap_val:.4f} ({vwap_r:.1f}R, 90%) | "
              f"VWAP dist: {vwap_dist_pct:+.2f}%")

        self._entry_context = {
            "direction": "long",
            "atr": round(atr, 4),
            "vwap_dist_pct": round(vwap_dist_pct, 2),
            "stop_distance": round(self.stop_distance, 4),
            "risk_pct": self.p.risk_per_trade_pct,
        }

    def _enter_short(self, dt, atr, vwap_val):
        price  = self.data15.close[0]
        equity = self.broker.getvalue()

        self.stop_distance = atr * self.p.atr_stop_mult
        size = self.risk_mgr.calculate_position_size(equity, self.stop_distance)
        if size <= 0:
            return

        max_size = (equity * 100) / price
        size = min(size, max_size * 0.95)

        self.sell(size=size)
        self.position_type  = 'short'
        self.entry_price    = price
        self.entry_atr      = atr
        self.vwap_target    = vwap_val
        self.initial_size   = size
        self.current_stop   = price + self.stop_distance
        self.early_be_done  = False
        self.one_r_hit      = False
        self.vwap_hit       = False
        self.low_water_mark = price

        risk_amt      = equity * self.risk_mgr.risk_pct
        vwap_dist_pct = (price - vwap_val) / vwap_val * 100
        vwap_r        = abs(price - vwap_val) / self.stop_distance

        print(f"[{dt}] SHORT ENTRY @ {price:.4f} | "
              f"Size: {size:.4f} | Risk: ${risk_amt:.0f} ({self.p.risk_per_trade_pct}%) | "
              f"Stop: {self.current_stop:.4f} | "
              f"VWAP target: {vwap_val:.4f} ({vwap_r:.1f}R, 90%) | "
              f"VWAP dist: {vwap_dist_pct:+.2f}%")

        self._entry_context = {
            "direction": "short",
            "atr": round(atr, 4),
            "vwap_dist_pct": round(vwap_dist_pct, 2),
            "stop_distance": round(self.stop_distance, 4),
            "risk_pct": self.p.risk_per_trade_pct,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Exit logic
    # ──────────────────────────────────────────────────────────────────────────

    def _check_exits(self):
        if self.entry_price is None:
            return
        if self.position_type == 'long':
            self._check_long_exits()
        elif self.position_type == 'short':
            self._check_short_exits()

    def _check_long_exits(self):
        price = self.data15.close[0]
        high  = self.data15.high[0]
        dt    = self.data15.datetime.datetime(0)

        self.high_water_mark = max(self.high_water_mark, high)

        # ── Stage 1: Pre-1R stop management (close-based triggers) ──────────
        if not self.one_r_hit:
            # 0.75R: early stop cushion — tighten stop to halfway before entry
            if not self.early_be_done:
                if price >= self.entry_price + self.p.early_be_trig * self.stop_distance:
                    new_stop = self.entry_price - self.p.early_be_dest * self.stop_distance
                    self.current_stop = max(self.current_stop, new_stop)
                    self.early_be_done = True
                    print(f"[{dt}] LONG EARLY BE @ {price:.4f}: "
                          f"stop → {self.current_stop:.4f} (-{self.p.early_be_dest}R)")

            # 1R: stop to breakeven, trail starts
            if price > self.entry_price + self.stop_distance:
                self.one_r_hit = True
                self.current_stop = max(self.current_stop, self.entry_price)
                print(f"[{dt}] LONG 1R HIT @ {price:.4f}: stop → BE {self.entry_price:.4f}, trail active")

        # ── Stage 2: ATR trail from HWM after 1R ────────────────────────────
        if self.one_r_hit:
            trail = self.high_water_mark - self.entry_atr * self.p.atr_trailing_mult
            self.current_stop = max(self.current_stop, trail)

        # ── VWAP exit: 90% out when wick touches VWAP ───────────────────────
        # Uses high (wick) to mirror a limit order at VWAP on the exchange
        if not self.vwap_hit and high >= self.vwap_target:
            partial_size = self.initial_size * 0.90
            if partial_size > abs(self.position.size):
                partial_size = abs(self.position.size)
            if partial_size > 0:
                self.vwap_hit = True
                pnl_pct = (self.vwap_target - self.entry_price) / self.entry_price * 100
                vwap_r  = (self.vwap_target - self.entry_price) / self.stop_distance
                print(f"[{dt}] LONG VWAP HIT @ {self.vwap_target:.4f} "
                      f"({pnl_pct:+.1f}%, {vwap_r:+.1f}R) — selling 90%, runner trails")
                self.sell(size=partial_size)
                return  # Don't check stop on same bar

        # ── Stop hit: exit remaining (full stop or runner stop) ──────────────
        if price <= self.current_stop:
            pnl_pct = (price - self.entry_price) / self.entry_price * 100
            r_val   = (price - self.entry_price) / self.stop_distance
            if self.vwap_hit:
                reason = "LONG RUNNER STOP"
            elif self.one_r_hit:
                reason = "LONG BE STOP"
            elif self.early_be_done:
                reason = "LONG EARLY STOP"
            else:
                reason = "LONG STOP"
            print(f"[{dt}] {reason} @ {price:.4f} ({pnl_pct:+.1f}%, {r_val:+.1f}R)")
            self.sell(size=abs(self.position.size))
            self._reset_state()

    def _check_short_exits(self):
        price = self.data15.close[0]
        low   = self.data15.low[0]
        dt    = self.data15.datetime.datetime(0)

        self.low_water_mark = min(self.low_water_mark, low)

        # ── Stage 1: Pre-1R stop management ─────────────────────────────────
        if not self.one_r_hit:
            if not self.early_be_done:
                if price <= self.entry_price - self.p.early_be_trig * self.stop_distance:
                    new_stop = self.entry_price + self.p.early_be_dest * self.stop_distance
                    self.current_stop = min(self.current_stop, new_stop)
                    self.early_be_done = True
                    print(f"[{dt}] SHORT EARLY BE @ {price:.4f}: "
                          f"stop → {self.current_stop:.4f} (-{self.p.early_be_dest}R)")

            if price < self.entry_price - self.stop_distance:
                self.one_r_hit = True
                self.current_stop = min(self.current_stop, self.entry_price)
                print(f"[{dt}] SHORT 1R HIT @ {price:.4f}: stop → BE {self.entry_price:.4f}, trail active")

        # ── Stage 2: ATR trail from LWM after 1R ─────────────────────────────
        if self.one_r_hit:
            trail = self.low_water_mark + self.entry_atr * self.p.atr_trailing_mult
            self.current_stop = min(self.current_stop, trail)

        # ── VWAP exit: 90% out when wick touches VWAP ────────────────────────
        if not self.vwap_hit and low <= self.vwap_target:
            partial_size = self.initial_size * 0.90
            if partial_size > abs(self.position.size):
                partial_size = abs(self.position.size)
            if partial_size > 0:
                self.vwap_hit = True
                pnl_pct = (self.entry_price - self.vwap_target) / self.entry_price * 100
                vwap_r  = (self.entry_price - self.vwap_target) / self.stop_distance
                print(f"[{dt}] SHORT VWAP HIT @ {self.vwap_target:.4f} "
                      f"({pnl_pct:+.1f}%, {vwap_r:+.1f}R) — buying 90%, runner trails")
                self.buy(size=partial_size)
                return

        # ── Stop hit: exit remaining ──────────────────────────────────────────
        if price >= self.current_stop:
            pnl_pct = (self.entry_price - price) / self.entry_price * 100
            r_val   = (self.entry_price - price) / self.stop_distance
            if self.vwap_hit:
                reason = "SHORT RUNNER STOP"
            elif self.one_r_hit:
                reason = "SHORT BE STOP"
            elif self.early_be_done:
                reason = "SHORT EARLY STOP"
            else:
                reason = "SHORT STOP"
            print(f"[{dt}] {reason} @ {price:.4f} ({pnl_pct:+.1f}%, {r_val:+.1f}R)")
            self.buy(size=abs(self.position.size))
            self._reset_state()

    def _reset_state(self):
        self.position_type   = None
        self.entry_price     = None
        self.entry_atr       = None
        self.stop_distance   = None
        self.vwap_target     = None
        self.current_stop    = None
        self.early_be_done   = False
        self.one_r_hit       = False
        self.vwap_hit        = False
        self.initial_size    = 0
        self.high_water_mark = None
        self.low_water_mark  = None

    # ──────────────────────────────────────────────────────────────────────────
    # Order / trade tracking
    # ──────────────────────────────────────────────────────────────────────────

    def notify_order(self, order):
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f"Order {order.status}: {order.info}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"TRADE CLOSED: PnL={trade.pnl:.2f} (net={trade.pnlcomm:.2f})")
