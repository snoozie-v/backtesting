# strategies/sol_strategy_v3_5.py
"""
SolStrategy v3.5 - Evolution of the best-performing v3 version (Jan 2026)

Philosophy:
- Keep the simple, effective core of v3 that has been outperforming
- Add only high-conviction, low-risk improvements:
  1. Earlier but still percentage-based trailing (activates after small profit)
  2. Two-stage trailing: more generous at first, tighter after meaningful gains
  3. Stronger bear-market regime filter
  4. Very conservative high-target partial profit (optional, usually disabled)
  5. Slightly more breathing room on RSI exit

Main goal: Protect gains earlier without cutting winners too aggressively
"""

import backtrader as bt
import backtrader.indicators as btind
import backtrader.talib as btlib


class SolStrategyV3_5(bt.Strategy):

    params = (
        # ── Core entry parameters (kept close to v3) ───────────────────────────
        ('decline_pct', 4.2),           # slightly more lenient than 4.0
        ('decline_window', 5),
        ('rise_window_min', 3),
        ('ema_short', 9),
        ('ema_long', 26),
        ('ema_support1', 21),
        ('ema_support2', 100),
        ('rsi_period', 14),
        ('rsi_low', 38),                # slightly lower → easier confirmation
        ('chandemo_period', 14),
        ('chandemo_threshold', -50),
        ('min_avg_volume', 900000),     # slightly relaxed

        # ── Exit & Risk Management ─────────────────────────────────────────────
        ('rsi_exit', 78),               # more room than original 70
        ('stop_loss_pct', 5.8),         # bit more forgiving than 5.0

        # ── Trailing (two-stage, percentage based) ─────────────────────────────
        ('trailing_start_pct', 2.8),       # activate trailing after this % profit
        ('trailing_pct_stage1', 12.5),     # loose stage - let it run
        ('trailing_pct_stage2', 7.2),      # tighter protection after bigger move
        ('stage2_activation_pct', 21.0),   # when to switch to tighter trailing

        # ── Very conservative partial profit (usually disabled) ────────────────
        ('partial_target_pct', 0.0),       # 0 = disabled | 35-45 typical when enabled
        ('partial_sell_ratio', 0.45),

        # ── Safety net ─────────────────────────────────────────────────────────
        ('bear_ema_decline_bars', 6),      # how many bars EMA-100 must be declining
    )

    def __init__(self):
        # Indicators (same core as v3)
        self.ema_short = btind.EMA(self.data.close, period=self.p.ema_short)
        self.ema_long = btind.EMA(self.data.close, period=self.p.ema_long)
        self.ema_support1 = btind.EMA(self.data.close, period=self.p.ema_support1)
        self.ema_support2 = btind.EMA(self.data.close, period=self.p.ema_support2)
        self.ema_crossover = btind.CrossOver(self.ema_short, self.ema_long)

        self.rsi = btind.RSI(self.data.close, period=self.p.rsi_period)
        self.chandemo = btlib.CMO(self.data.close, timeperiod=self.p.chandemo_period)
        self.chandemo_cross = btind.CrossOver(self.chandemo, self.p.chandemo_threshold)

        self.avg_volume = btind.SMA(self.data.volume, period=20)
        self.recent_low = btind.Lowest(self.data.low(-1), period=10)
        self.atr = btind.ATR(self.data, period=14)  # kept for info/logging only

        # State variables
        self.high_water_mark = 0.0
        self.decline_detected = False
        self.rise_count = 0
        self.entry_price = 0.0
        self.in_position = False
        self.partial_taken = False

    def next(self):
        if len(self) < max(self.p.decline_window, self.p.rise_window_min, self.p.ema_support2):
            return

        if self.avg_volume[0] < self.p.min_avg_volume:
            return

        daily_change_pct = ((self.data.close[0] - self.data.close[-1]) / self.data.close[-1]) * 100 \
            if len(self) > 1 else 0.0

        # ── Stronger Bear Market Filter ────────────────────────────────────────
        if self.data.close[0] < self.ema_support2[0]:
            ema_decline = all(self.ema_support2[0 - i] > self.ema_support2[-i] 
                             for i in range(1, self.p.bear_ema_decline_bars + 1))
            if ema_decline:
                if self.position:
                    print(f"BEAR REGIME EXIT {self.data.datetime.date(0)}")
                    self.close()
                return

        # ── Decline detection ──────────────────────────────────────────────────
        if not self.decline_detected:
            declines = [((self.data.close[-i] - self.data.close[-i-1]) / self.data.close[-i-1] * 100)
                        for i in range(1, self.p.decline_window + 1)]
            total_decline = sum(d for d in declines if d < 0)
            if total_decline <= -self.p.decline_pct:
                self.decline_detected = True
                self.rise_count = 0

        # ── Rise / rebound qualification ───────────────────────────────────────
        if self.decline_detected:
            if daily_change_pct > 0:
                self.rise_count += 1
            else:
                self.rise_count = 0
                if daily_change_pct <= -self.p.decline_pct / 3:
                    self.decline_detected = False

            if self.rise_count < self.p.rise_window_min:
                return

        # ── Confirmation conditions ────────────────────────────────────────────
        ema_bounce = (self.data.close[0] > self.ema_support1[0]) or \
                     (self.data.close[0] > self.ema_support2[0])
        chandemo_confirm = self.chandemo_cross[0] == 1

        # ── ENTRY ──────────────────────────────────────────────────────────────
        if not self.position and \
           self.ema_crossover[0] == 1 and \
           ema_bounce and \
           self.decline_detected and \
           self.rise_count >= self.p.rise_window_min:

            buy_size = self.broker.get_cash() * 0.5 / self.data.close[0]
            self.buy(size=buy_size)
            self.in_position = True
            self.entry_price = self.data.close[0]
            self.high_water_mark = self.data.close[0]
            self.partial_taken = False
            self.decline_detected = False
            print(f"ENTRY {self.data.datetime.date(0)}")

        # ── Scale-in (conservative) ────────────────────────────────────────────
        elif self.position and self.rise_count > self.p.rise_window_min and daily_change_pct > 0:
            if self.data.close[0] < self.entry_price * 0.975:  # 2.5% dip
                add_size = self.position.size * 0.45
                self.buy(size=add_size)
                total_size = self.position.size + add_size
                self.entry_price = (self.entry_price * self.position.size +
                                  self.data.close[0] * add_size) / total_size
                print(f"SCALE-IN {self.data.datetime.date(0)}")

        # ── EXIT LOGIC ─────────────────────────────────────────────────────────
        if self.position:
            self.high_water_mark = max(self.high_water_mark, self.data.close[0])
            unrealized_pct = (self.data.close[0] / self.entry_price - 1) * 100

            # Very high target partial profit (usually disabled)
            if self.p.partial_target_pct > 0 and not self.partial_taken and \
               unrealized_pct > self.p.partial_target_pct:
                sell_size = self.position.size * self.p.partial_sell_ratio
                self.sell(size=sell_size)
                self.partial_taken = True
                self.entry_price = self.data.close[0]          # reset for remaining position
                self.high_water_mark = self.data.close[0]
                print(f"PARTIAL PROFIT at {unrealized_pct:.1f}% {self.data.datetime.date(0)}")

            # Two-stage percentage trailing
            if unrealized_pct > self.p.trailing_start_pct:
                if unrealized_pct >= self.p.stage2_activation_pct:
                    trail_pct = self.p.trailing_pct_stage2
                else:
                    trail_pct = self.p.trailing_pct_stage1

                trail_price = self.high_water_mark * (1 - trail_pct / 100)

                if self.data.close[0] < trail_price:
                    print(f"TRAILING EXIT ({trail_pct}% stage) {self.data.datetime.date(0)}")
                    self.close()
                    self.in_position = False
                    self.rise_count = 0
                    return

            # Classic protective exits (v3 style)
            stop_price = self.recent_low[0] * (1 - self.p.stop_loss_pct / 100)

            if self.data.close[0] < stop_price or self.data.close[0] < self.ema_support2[0]:
                print(f"STOP / EMA2 EXIT {self.data.datetime.date(0)}")
                self.close()
                self.in_position = False
                self.rise_count = 0
                return

            if self.rsi[0] > self.p.rsi_exit:
                print(f"RSI OVERBOUGHT EXIT {self.data.datetime.date(0)}")
                self.close()
                self.in_position = False
                self.rise_count = 0
                return
