# strategies/sol_strategy_v8.py
"""
SolStrategy v8 - Simplified Rounded Bottom Catcher (Multi-Timeframe Version)
-------------------------------------------------------------------------
Logic:
- Detect FAST DROP: ≥25% decline over max 15 days on DAILY timeframe
- Then look for SLOW/CONTROLLED RISE over next 20 days on DAILY:
  - ≥50% up days
  - No single day > +20% or < -10%
  - Total rise ≥5% during the window
  - Volume confirmation: avg volume in rise window ≥ current 20-day avg
- Multi-timeframe filter: daily close > 5-period EMA on WEEKLY chart
- Entry: on the daily bar that meets conditions, using current 15m close price
- Exits: checked on every 15m bar - 8% trailing from HWM OR 5% fixed SL

Data feeds (expected index order):
  0 → 15m (base for entry/exit prices)
  1 → 1h (unused in v8)
  2 → 4h (unused in v8)
  3 → weekly (for MTF EMA)
  4 → daily (main logic: drop/rise detection)
"""

import backtrader as bt
import backtrader.indicators as btind


class SolStrategyV8(bt.Strategy):
    params = (
        # Drop detection
        ('drop_window', 15),
        ('min_drop_pct', 25.0),

        # Rise (recovery) requirements
        ('rise_window', 20),
        ('min_up_days_ratio', 0.50),        # at least 50% up days
        ('max_single_up_day', 20.0),        # no explosive +20%+ days
        ('max_single_down_day', -10.0),     # no big panic -10% days
        ('min_rise_pct', 5.0),              # total rise during window

        # Volume confirmation during rise
        ('volume_confirm', True),

        # Weekly confirmation
        ('weekly_ema_period', 5),

        # Risk management
        ('trailing_pct', 8.0),
        ('fixed_stop_pct', 5.0),
    )

    def __init__(self):
        # Data feeds
        self.data15 = self.datas[0]  # 15m: for precise entry/exit prices
        self.weekly = self.datas[3]  # Weekly: for MTF filter
        self.daily  = self.datas[4]  # Daily: for drop/rise logic

        # Indicators on daily
        self.avg_volume = btind.SMA(self.daily.volume, period=20)

        # Weekly EMA
        self.weekly_ema = btind.EMA(self.weekly.close, period=self.p.weekly_ema_period)

        # State tracking
        self.drop_detected = False
        self.rise_start_day = None
        self.high_water_mark = None
        self.entry_price = None

        # For rise window analysis (on daily bars)
        self.rise_prices = []
        self.rise_volumes = []
        self.rise_days = 0

        # To run main logic only on new daily bars
        self.last_daily_len = 0

    def next(self):
        # Exit checks: run on every 15m bar if in position
        if self.position:
            self.high_water_mark = max(self.high_water_mark, self.data15.close[0])

            trailing_stop = self.high_water_mark * (1 - self.p.trailing_pct / 100)
            fixed_stop = self.entry_price * (1 - self.p.fixed_stop_pct / 100)

            # Use max() - trailing stop protects profits as price rises
            if self.data15.close[0] <= max(trailing_stop, fixed_stop):
                reason = "TRAILING" if self.data15.close[0] <= trailing_stop else "FIXED"
                print(f"[{self.data15.datetime.datetime(0)}] EXIT ({reason} STOP) "
                      f"Price: {self.data15.close[0]:.4f} | HWM: {self.high_water_mark:.4f}")
                self.sell(size=self.position.size)
                self._reset_recovery()
                return  # Early return after exit

        # Safety: need enough data on daily and weekly
        if len(self.daily) < max(self.p.drop_window + 1, self.p.rise_window + 1, 30):
            return

        if len(self.weekly) < self.p.weekly_ema_period + 1:
            return

        # Run detection/entry logic only on new daily bar
        if len(self.daily) == self.last_daily_len:
            return

        self.last_daily_len = len(self.daily)

        # Use daily datetime for prints
        dt = self.daily.datetime.date(0)

        # ── 1. Detect Fast Drop ───────────────────────────────────────
        if not self.drop_detected and not self.position:
            closes = self.daily.close.get(size=self.p.drop_window)

            if len(closes) < self.p.drop_window:
                return

            peak = max(closes)
            trough = min(closes)
            drop_pct = (trough - peak) / peak * 100

            if drop_pct <= -self.p.min_drop_pct:
                print(f"[{dt}] FAST DROP DETECTED: {-drop_pct:.1f}% over ≤{self.p.drop_window} days")
                self.drop_detected = True
                self.rise_start_day = None  # Reset rise if needed

        # ── 2. Monitor potential slow rise after drop ──────────────────
        if self.drop_detected and not self.position:
            # Start collecting rise window
            if self.rise_start_day is None:
                self.rise_start_day = len(self.daily)
                self.rise_prices = [self.daily.close[0]]  # current bar
                self.rise_volumes = [self.daily.volume[0]]
                self.rise_days = 1
                return

            # Add current daily bar to rise window
            self.rise_prices.append(self.daily.close[0])
            self.rise_volumes.append(self.daily.volume[0])
            self.rise_days += 1

            # Check daily change for disqualifiers
            if self.rise_days >= 2:
                daily_change = (self.daily.close[0] - self.daily.close[-1]) / self.daily.close[-1] * 100

                if daily_change > self.p.max_single_up_day:
                    print(f"[{dt}] Rise disqualified - explosive day +{daily_change:.1f}%")
                    self._reset_recovery()
                    return

                if daily_change < self.p.max_single_down_day:
                    print(f"[{dt}] Rise disqualified - panic day {daily_change:.1f}%")
                    self._reset_recovery()
                    return

            # If window complete → evaluate
            if self.rise_days == self.p.rise_window:
                closes_in_window = self.daily.close.get(size=self.p.rise_window)

                if len(closes_in_window) < self.p.rise_window:
                    self._reset_recovery()
                    return

                start_price = closes_in_window[0]   # oldest
                end_price   = closes_in_window[-1]  # newest
                total_rise_pct = (end_price - start_price) / start_price * 100

                # Count up days
                up_days = 0
                for i in range(1, len(closes_in_window)):
                    if closes_in_window[i] > closes_in_window[i-1]:
                        up_days += 1
                up_ratio = up_days / (self.p.rise_window - 1)

                volume_ok = True
                if self.p.volume_confirm:
                    avg_rise_vol = sum(self.rise_volumes) / len(self.rise_volumes)
                    current_avg_vol = self.avg_volume[0]
                    volume_ok = avg_rise_vol >= current_avg_vol

                # MTF filter: daily close above weekly EMA
                mtf_ok = self.daily.close[0] > self.weekly_ema[0]

                conditions_met = (
                    up_ratio >= self.p.min_up_days_ratio and
                    total_rise_pct >= self.p.min_rise_pct and
                    volume_ok and
                    mtf_ok
                )

                if conditions_met:
                    print(f"[{dt}] ENTRY TRIGGER! "
                          f"Rise: {total_rise_pct:.1f}%, Up days: {up_ratio:.2%}, "
                          f"Vol ok: {volume_ok}, Weekly EMA ok: {mtf_ok}")
                    size = self.broker.get_cash() / self.data15.close[0] * 0.98
                    self.buy(size=size)
                    self.entry_price = self.data15.close[0]
                    self.high_water_mark = self.data15.close[0]
                else:
                    print(f"[{dt}] Rise window finished but conditions NOT met "
                          f"(rise={total_rise_pct:.1f}%, up={up_ratio:.2%}, vol={volume_ok}, mtf={mtf_ok})")

                self._reset_recovery()

    def _reset_recovery(self):
        """Reset all recovery tracking variables"""
        self.drop_detected = False
        self.rise_start_day = None
        self.rise_prices = []
        self.rise_volumes = []
        self.rise_days = 0
