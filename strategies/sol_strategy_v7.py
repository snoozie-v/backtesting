# strategies/sol_strategy_v7.py
# Goal: Keep good V6 multi-TF entries → but let winners run like V3

import backtrader as bt
import backtrader.indicators as btind

class SolStrategyV7(bt.Strategy):
    params = (
        # ── Entry related ───────────────────────────────
        ('ema_short', 9),
        ('ema_long', 26),
        ('rsi_period', 14),
        ('rsi_pullback_1h', 57),     # was rsi_low
        ('min_avg_volume', 1),       # keep low for testing

        # ── Risk / Exit related ─────────────────────────
        ('initial_stop_pct', 7),   # wider than current 3%
        ('trailing_pct', 14.0),      # ← most important! 10–16% range usually best for SOL
        ('rsi_exit_1h', 76),         # overbought exit (1h)
        ('partial_target_pct', 24.0),# sell ~40–50% here (0 = disable)
        ('partial_sell_ratio', 0.45),

        # Optional extra protection
        ('use_4h_death_cross_exit', True),
    )

    def __init__(self):
        self.data15 = self.datas[0]
        self.data1h = self.datas[1]
        self.data4h = self.datas[2]

        # ── Indicators ──────────────────────────────────
        # 4H trend
        self.ema_short_4h = btind.EMA(self.data4h.close, period=self.p.ema_short)
        self.ema_long_4h  = btind.EMA(self.data4h.close, period=self.p.ema_long)
        self.ema_cross_4h = btind.CrossOver(self.ema_short_4h, self.ema_long_4h)

        # 1H trend + momentum
        self.ema_short_1h = btind.EMA(self.data1h.close, period=self.p.ema_short)
        self.ema_long_1h  = btind.EMA(self.data1h.close, period=self.p.ema_long)
        self.rsi_1h = btind.RSI(self.data1h.close, period=self.p.rsi_period)

        # 15m entry
        self.ema_short_15 = btind.EMA(self.data15.close, period=self.p.ema_short)
        self.ema_long_15  = btind.EMA(self.data15.close, period=self.p.ema_long)
        self.ema_cross_15 = btind.CrossOver(self.ema_short_15, self.ema_long_15)

        # Volume
        self.avg_volume = btind.SMA(self.data15.volume, period=20)

        # ── State variables for trailing & partial ──────
        self.high_water_mark = None
        self.partial_taken = False

    def next(self):
        if len(self.data4h) < 50 or len(self.data1h) < 50 or len(self.data15) < 50:
            return

        if self.avg_volume[0] < self.p.min_avg_volume:
            return

        # ── Trend & setup filters (same good logic as V6) ───────
        uptrend_4h = self.ema_short_4h[0] > self.ema_long_4h[0]
        uptrend_1h = self.ema_short_1h[0] > self.ema_long_1h[0]
        pullback_1h = self.rsi_1h[0] <= self.p.rsi_pullback_1h

        if not (uptrend_4h and uptrend_1h and pullback_1h):
            # Optional early exit on 4h death cross
            if self.position and self.p.use_4h_death_cross_exit and self.ema_cross_4h[0] == -1:
                self.close()
                self._reset_state()
            return

        # ── ENTRY ───────────────────────────────────────
        if not self.position and self.ema_cross_15[0] == 1:
            size = self.broker.get_cash() / self.data15.close[0] * 0.98  # almost all-in

            self.buy(size=size)

            self.high_water_mark = self.data15.close[0]
            self.partial_taken = False
            print(f"ENTRY  {self.data15.datetime.datetime(0):%Y-%m-%d %H:%M}  {self.data15.close[0]:.3f}")

            # Optional: place initial hard stop (you can remove later)
            # self.sell(exectype=bt.Order.Stop, price=self.data15.close[0]*(1-self.p.initial_stop_pct/100))

        # ── IN POSITION logic ───────────────────────────
        if self.position:
            # 1. Update trailing reference
            self.high_water_mark = max(self.high_water_mark, self.data15.close[0])

            # 2. Trailing stop check
            trail_level = self.high_water_mark * (1 - self.p.trailing_pct / 100)
            if self.data15.close[0] < trail_level:
                self.close()
                print(f"TRAIL EXIT @ {self.data15.close[0]:.3f}  (high was {self.high_water_mark:.3f})")
                self._reset_state()
                return

            # 3. Optional partial profit
            if not self.partial_taken and self.p.partial_target_pct > 0:
                profit_pct = (self.data15.close[0]/self.position.price - 1) * 100
                if profit_pct >= self.p.partial_target_pct:
                    sell_size = self.position.size * self.p.partial_sell_ratio
                    self.sell(size=sell_size)
                    self.partial_taken = True
                    print(f"PARTIAL {self.p.partial_sell_ratio*100:.0f}% @ {profit_pct:.1f}% profit")

            # 4. Overbought / momentum exit (1h)
            if self.rsi_1h[0] > self.p.rsi_exit_1h:
                self.close()
                print(f"RSI OVERBOUGHT EXIT 1h RSI={self.rsi_1h[0]:.1f}")
                self._reset_state()

    def _reset_state(self):
        self.high_water_mark = None
        self.partial_taken = False
