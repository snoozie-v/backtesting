# strategies/sol_strategy_v6.py
# Updated V6 - matching your real trading rules:
# - 4H & 1H trend confirmation + 1H pullback (RSI <= 55)
# - 15m EMA cross-up entry
# - Exits: 1% SL + 3% TP on whole position (bracket order)
# - Volume threshold set very low (1) for testing
import backtrader as bt
import backtrader.indicators as btind

class SolStrategyV6(bt.Strategy):
    params = (
        ('ema_short', 9),
        ('ema_long', 26),
        ('rsi_period', 14),
        ('rsi_low', 55),           # ← Updated to 55 (your request)
        ('stop_loss_pct', 3.0),    # ← Real value you use live
        ('take_profit_pct', 7.0),  # ← Real value you use live
        ('min_avg_volume', 1),     # ← Very low → almost disabled for testing
    )

    def __init__(self):
        self.data15 = self.datas[0]
        self.data1h = self.datas[1]
        self.data4h = self.datas[2]

        # 4H trend
        self.ema_short_4h = btind.EMA(self.data4h.close, period=self.p.ema_short)
        self.ema_long_4h = btind.EMA(self.data4h.close, period=self.p.ema_long)

        # 1H trend + setup
        self.ema_short_1h = btind.EMA(self.data1h.close, period=self.p.ema_short)
        self.ema_long_1h = btind.EMA(self.data1h.close, period=self.p.ema_long)
        self.rsi_1h = btind.RSI(self.data1h.close, period=self.p.rsi_period)

        # 15m entry signal
        self.ema_short_15 = btind.EMA(self.data15.close, period=self.p.ema_short)
        self.ema_long_15 = btind.EMA(self.data15.close, period=self.p.ema_long)
        self.ema_cross_15 = btind.CrossOver(self.ema_short_15, self.ema_long_15)

        # Volume filter
        self.avg_volume = btind.SMA(self.data15.volume, period=20)

    def next(self):
        min_period = max(self.p.ema_long, self.p.rsi_period)

        # Basic progress print
        if len(self.data15) % 100 == 0:
            print(f"Bar {len(self)} | 15m len: {len(self.data15)} | "
                  f"1h len: {len(self.data1h)} | 4h len: {len(self.data4h)}")

        if len(self.data4h) < min_period or len(self.data1h) < min_period or len(self.data15) < min_period:
            if len(self.data15) % 200 == 0:
                print("  → Waiting for warmup")
            return

        if self.avg_volume[0] < self.p.min_avg_volume:
            if len(self.data15) % 500 == 0:
                print(f"  → Volume too low: {self.avg_volume[0]:,.0f}")
            return

        # Core filters
        uptrend_4h = self.ema_short_4h[0] > self.ema_long_4h[0]
        uptrend_1h = self.ema_short_1h[0] > self.ema_long_1h[0]
        oversold_1h = self.rsi_1h[0] <= self.p.rsi_low

        if len(self.data15) % 500 == 0:
            print(f"  → Checks: 4h up={uptrend_4h} | 1h up={uptrend_1h} | 1h RSI<={self.rsi_1h[0]:.1f}")

        if not uptrend_4h or not uptrend_1h or not oversold_1h:
            return

        # Entry on 15m EMA cross up
        if self.ema_cross_15[0] == 1:
            entry_price = self.data15.close[0]
            sl_price = entry_price * (1 - self.p.stop_loss_pct / 100)
            tp_price = entry_price * (1 + self.p.take_profit_pct / 100)

            # Use almost full cash (leave tiny buffer for fees)
            size = max(1, int((self.broker.get_cash() / entry_price) * 0.99))

            print(f"ENTRY TRIGGERED at {self.data15.datetime.datetime(0)} | "
                  f"Price: {entry_price:.4f} | SL: {sl_price:.4f} | TP: {tp_price:.4f} | "
                  f"Size: {size} | Cash before: {self.broker.get_cash():.2f}")

            self.buy_bracket(size=size,
                             exectype=bt.Order.Market,
                             stopprice=sl_price,
                             limitprice=tp_price)

        # Optional: show when setup is ready but waiting for cross
        elif len(self.data15) % 200 == 0:
            print("  → Higher TFs aligned → waiting for 15m EMA cross")

        # Show position status every bar when we are in trade
        if self.position:
            pnl = self.broker.getvalue() - 10000
            print(f"IN POSITION | Size: {self.position.size} | Avg: {self.position.price:.4f} | "
                  f"Current: {self.data15.close[0]:.4f} | P&L: {pnl:+.2f}")

    # Optional: how to switch to LIMIT entry (uncomment if wanted)
    # if self.ema_cross_15[0] == 1:
    #     ...
    #     self.buy_bracket(size=size,
    #                      exectype=bt.Order.Limit,          # ← Change here
    #                      price=entry_price * 1.001,        # slight slippage buffer
    #                      stopprice=sl_price,
    #                      limitprice=tp_price)
