# strategies/sol_strategy_v4.py
import backtrader as bt
import backtrader.indicators as btind
import backtrader.talib as btlib

class SolStrategyV4(bt.Strategy):
    """
    SolStrategy v4 - with Phase 1 volume & safety improvements
    
    New / changed features:
    • Relative volume logic (continuation + climax detection)
    • Stronger bear filter (multi-bar declining 100EMA)
    • Low volume near recent highs → tighten trailing significantly
    • Dynamic trailing activation lowered + ATR based
    • Partial profits optional (still present but commented by default)
    """
    
    params = (
        # ── Core signal parameters ──
        ('decline_pct', 4.0),
        ('decline_window', 5),
        ('rise_window_min', 3),
        ('ema_short', 9),
        ('ema_long', 26),
        ('ema_support1', 21),
        ('ema_support2', 100),
        ('rsi_period', 14),
        ('rsi_low', 40),
        ('chandemo_period', 14),
        ('chandemo_threshold', -50),
        ('min_avg_volume', 1000000),

        # ── Exit & Risk Management ──
        ('rsi_exit', 80),
        ('stop_loss_pct', 5.0),
        ('scale_in_amount', 0.45),         # slightly reduced aggressiveness

        # ── Trailing & Partial ──
        ('trailing_activation_pct', 5.0),   # lowered from 10%
        ('atr_multiplier', 2.7),
        ('target_pct', 15.0),               # partial profit target (0 = disable)

        # ── VOLUME LOGIC (new Phase 1) ──
        ('low_vol_threshold',    0.70),     # < this → likely continuation / healthy
        ('very_low_vol_threshold', 0.55),   # very low → exhaustion risk near highs
        ('high_vol_threshold',   1.65),     # > this + high RSI → potential climax
        ('tight_trail_on_lowvol', 4.5),     # % trailing when very low vol near highs
        ('normal_trailing_pct',   9.0),     # default % trailing (used before activation)
    )

    def __init__(self):
        # Indicators
        self.ema_short    = btind.EMA(self.data.close, period=self.p.ema_short)
        self.ema_long     = btind.EMA(self.data.close, period=self.p.ema_long)
        self.ema_support1 = btind.EMA(self.data.close, period=self.p.ema_support1)
        self.ema_support2 = btind.EMA(self.data.close, period=self.p.ema_support2)
        self.ema_crossover = btind.CrossOver(self.ema_short, self.ema_long)

        self.rsi          = btind.RSI(self.data.close, period=self.p.rsi_period)
        self.chandemo     = btlib.CMO(self.data.close, timeperiod=self.p.chandemo_period)
        self.chandemo_cross = btind.CrossOver(self.chandemo, self.p.chandemo_threshold)

        self.avg_volume   = btind.SMA(self.data.volume, period=20)
        self.recent_low   = btind.Lowest(self.data.low(-1), period=10)
        self.recent_high  = btind.Highest(self.data.close(-1), period=15)   # ← new

        self.atr          = btind.ATR(self.data, period=14)

        # States
        self.high_water_mark = 0.0
        self.decline_detected = False
        self.rise_count = 0
        self.entry_price = 0.0
        self.partial_taken = False

    def next(self):
        if len(self) < max(self.p.decline_window, self.p.rise_window_min, self.p.ema_support2, 20):
            return

        if self.avg_volume[0] < self.p.min_avg_volume:
            return

        # ── Relative Volume (very useful context) ───────────────────────────────
        rel_vol = self.data.volume[0] / self.avg_volume[0] if self.avg_volume[0] > 0 else 1.0

        daily_change_pct = 100 * (self.data.close[0] - self.data.close[-1]) / self.data.close[-1] \
                            if len(self) > 1 else 0.0

        # ── Stronger Bear Filter ────────────────────────────────────────────────
        if self.data.close[0] < self.ema_support2[0] and \
           self.ema_support2[0] < self.ema_support2[-5]:
            if self.position:
                print(f"STRONG BEAR FILTER EXIT  {self.data.datetime.date(0)}")
                self.close()
            return

        # ── Decline / Rebound detection (same as before) ────────────────────────
        if not self.decline_detected:
            declines = [100 * (self.data.close[-i] - self.data.close[-i-1]) / self.data.close[-i-1]
                        for i in range(1, self.p.decline_window + 1)]
            total_decline = sum(d for d in declines if d < 0)

            if total_decline <= -self.p.decline_pct:
                self.decline_detected = True
                self.rise_count = 0
                # print(f"DECLINE DETECTED {self.data.datetime.date(0)} {total_decline:5.1f}%")

        if self.decline_detected:
            if daily_change_pct > 0:
                self.rise_count += 1
            else:
                self.rise_count = 0
                if daily_change_pct <= -self.p.decline_pct / 3.2:
                    self.decline_detected = False

            if self.rise_count < self.p.rise_window_min:
                return

        # ── Entry conditions ────────────────────────────────────────────────────
        ema_bounce = self.data.close[0] > self.ema_support1[0] or \
                     self.data.close[0] > self.ema_support2[0]

        chandemo_confirm = self.chandemo_cross[0] == 1

        if not self.position and \
           self.ema_crossover[0] == 1 and \
           ema_bounce and self.decline_detected and \
           self.rise_count >= self.p.rise_window_min:

            size = self.broker.get_cash() * 0.48 / self.data.close[0]
            self.buy(size=size)
            self.entry_price = self.data.close[0]
            self.high_water_mark = self.data.close[0]
            self.partial_taken = False
            self.decline_detected = False
            # print(f"ENTRY {self.data.datetime.date(0)}")

        # ── Scale-in (only when still healthy momentum) ─────────────────────────
        elif self.position and self.rise_count >= self.p.rise_window_min + 1 and daily_change_pct > -0.4:
            if self.data.close[0] <= self.entry_price * 0.975:   # a bit deeper dip allowed
                add_size = self.position.size * self.p.scale_in_amount
                self.buy(size=add_size)
                total_size = self.position.size + add_size
                self.entry_price = (self.entry_price * (total_size - add_size) + self.data.close[0] * add_size) / total_size

        # ── EXIT LOGIC ──────────────────────────────────────────────────────────
        if self.position:
            self.high_water_mark = max(self.high_water_mark, self.data.close[0])

            unrealized_pct = 100 * (self.data.close[0] - self.entry_price) / self.entry_price

            # 1. Climax / exhaustion partial exit
            if rel_vol > self.p.high_vol_threshold and self.rsi[0] > 74 and unrealized_pct > 8:
                sell_size = self.position.size * 0.45
                self.sell(size=sell_size, exectype=bt.Order.Market)
                print(f"CLIMAX PARTIAL EXIT  {self.data.datetime.date(0)}  rel_vol:{rel_vol:.2f}")

            # 2. Optional target partial (disabled by default - set target_pct > 0)
            if self.p.target_pct > 0 and not self.partial_taken and unrealized_pct > self.p.target_pct:
                sell_size = self.position.size * 0.50
                self.sell(size=sell_size)
                self.partial_taken = True
                self.entry_price = self.data.close[0]          # reset breakeven for rest
                self.high_water_mark = self.data.close[0]
                print(f"TARGET PARTIAL  {unrealized_pct:5.1f}%")

            # 3. Low volume near highs → tighten protection
            near_high = self.data.close[0] > self.recent_high[0] * 0.992
            tight_trail_active = near_high and rel_vol < self.p.very_low_vol_threshold

            # 4. Trailing stop logic
            if unrealized_pct > self.p.trailing_activation_pct:
                # Dynamic ATR trailing after activation
                trail_price = self.high_water_mark - self.atr[0] * self.p.atr_multiplier
            else:
                # Before activation → use regular % trailing (can be tightened)
                trail_pct = self.p.tight_trail_on_lowvol if tight_trail_active else self.p.normal_trailing_pct
                trail_price = self.high_water_mark * (1 - trail_pct/100)

            if self.data.close[0] < trail_price:
                print(f"TRAILING EXIT  {self.data.datetime.date(0)}  "
                      f"{'TIGHT ' if tight_trail_active else ''}rel_vol:{rel_vol:.2f}")
                self.close()
                return

            # 5. Classic stops
            stop_price = self.recent_low[0] * (1 - self.p.stop_loss_pct / 100)

            if self.data.close[0] < stop_price or self.data.close[0] < self.ema_support2[0]:
                self.close()
                print(f"STOP / EMA2 EXIT  {self.data.datetime.date(0)}")
                return

            if self.rsi[0] > self.p.rsi_exit:
                self.close()
                print(f"RSI OVERBOUGHT EXIT  {self.data.datetime.date(0)}")
                return
