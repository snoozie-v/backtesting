# strategies/sol_strategy_v14.py
"""
SolStrategy v14 - 4H EMA Trend with 15M Crossover Entries
---------------------------------------------------------
Based on TradingView strategy: 4H trend alignment + 15M EMA crossover + volume.

Core Concept:
- 4H trend: EMA9 > EMA25 = uptrend, EMA9 < EMA25 = downtrend
- 15M entry: EMA9/25 crossover aligned with 4H trend
- Volume confirmation: Volume > 20-period SMA
- ATR-based TP/SL with 2:1 reward-to-risk ratio
- Exit on 4H trend reversal

Data feeds (expected index order):
  0 -> 15m (base, entries and exits)
  1 -> 1h (unused)
  2 -> 4h (trend detection)
  3 -> weekly (unused)
  4 -> daily (unused)
"""

import backtrader as bt
import backtrader.indicators as btind


class SolStrategyV14(bt.Strategy):
    params = (
        # 4H Trend EMAs
        ('ema_fast', 9),
        ('ema_slow', 25),

        # 15M Entry EMAs (same periods, different timeframe)
        ('entry_ema_fast', 9),
        ('entry_ema_slow', 25),

        # Volume confirmation
        ('vol_sma_period', 20),
        ('require_volume', True),

        # ATR-based stops
        ('atr_period', 14),
        ('stop_multiplier', 1.5),    # SL = ATR * 1.5
        ('tp_multiplier', 3.0),      # TP = ATR * 3.0 (2:1 R:R)

        # Trend reversal exit
        ('exit_on_trend_reversal', True),

        # Position sizing
        ('position_pct', 95.0),

        # Cooldown (prevent rapid re-entry)
        ('cooldown_bars', 4),
    )

    def __init__(self):
        # Data feeds
        self.data15 = self.datas[0]   # 15m
        self.data4h = self.datas[2]   # 4h

        # 4H Trend EMAs
        self.ema_fast_4h = btind.EMA(self.data4h.close, period=self.p.ema_fast)
        self.ema_slow_4h = btind.EMA(self.data4h.close, period=self.p.ema_slow)

        # 15M Entry EMAs
        self.ema_fast_15m = btind.EMA(self.data15.close, period=self.p.entry_ema_fast)
        self.ema_slow_15m = btind.EMA(self.data15.close, period=self.p.entry_ema_slow)

        # 15M Crossover signals
        self.crossover_15m = btind.CrossOver(self.ema_fast_15m, self.ema_slow_15m)

        # Volume
        self.vol_sma_15m = btind.SMA(self.data15.volume, period=self.p.vol_sma_period)

        # ATR for stops (15M timeframe)
        self.atr_15m = btind.ATR(self.data15, period=self.p.atr_period)

        # Position tracking
        self.entry_price = None
        self.position_type = None
        self.stop_loss = None
        self.take_profit = None

        # Bar tracking
        self.last_trade_bar = -999
        self.last_15m_len = 0

    def next(self):
        # Need enough data
        if len(self.data4h) < self.p.ema_slow + 1:
            return
        if len(self.data15) < max(self.p.entry_ema_slow, self.p.atr_period, self.p.vol_sma_period) + 1:
            return

        # Determine 4H trend
        uptrend_4h = self.ema_fast_4h[0] > self.ema_slow_4h[0]
        downtrend_4h = self.ema_fast_4h[0] < self.ema_slow_4h[0]

        # If in position, check exits
        if self.position:
            self._check_exits(uptrend_4h, downtrend_4h)
            return

        # Only check entries on new 15m bar
        if len(self.data15) == self.last_15m_len:
            return
        self.last_15m_len = len(self.data15)

        # Check cooldown
        if len(self.data15) - self.last_trade_bar < self.p.cooldown_bars:
            return

        # Check entry conditions
        self._check_entry(uptrend_4h, downtrend_4h)

    def _check_entry(self, uptrend_4h, downtrend_4h):
        """Check for entry signals based on 15M crossover + 4H trend + volume."""
        current_price = self.data15.close[0]
        atr = self.atr_15m[0]

        # Volume confirmation
        high_volume = True
        if self.p.require_volume:
            high_volume = self.data15.volume[0] > self.vol_sma_15m[0]

        # Long signal: 15M bullish crossover + 4H uptrend + volume
        if self.crossover_15m[0] > 0 and uptrend_4h and high_volume:
            self._enter_long(current_price, atr)

        # Short signal: 15M bearish crossunder + 4H downtrend + volume
        elif self.crossover_15m[0] < 0 and downtrend_4h and high_volume:
            self._enter_short(current_price, atr)

    def _enter_long(self, price, atr):
        """Enter long position with ATR-based TP/SL."""
        self.stop_loss = price - (atr * self.p.stop_multiplier)
        self.take_profit = price + (atr * self.p.tp_multiplier)

        # Position sizing
        equity = self.broker.getvalue()
        cash = self.broker.get_cash()
        size = min(
            (equity * self.p.position_pct / 100) / price,
            cash * 0.99 / price
        )

        if size <= 0:
            return

        self.buy(size=size)
        self.entry_price = price
        self.position_type = 'long'
        self.last_trade_bar = len(self.data15)

        dt = self.data15.datetime.datetime(0)
        vol_ratio = self.data15.volume[0] / self.vol_sma_15m[0] if self.vol_sma_15m[0] > 0 else 0
        print(f"[{dt}] LONG @ {price:.2f} | "
              f"SL: {self.stop_loss:.2f} | TP: {self.take_profit:.2f} | "
              f"ATR: {atr:.2f} | Vol: {vol_ratio:.1f}x")

    def _enter_short(self, price, atr):
        """Enter short position with ATR-based TP/SL."""
        self.stop_loss = price + (atr * self.p.stop_multiplier)
        self.take_profit = price - (atr * self.p.tp_multiplier)

        # Position sizing
        equity = self.broker.getvalue()
        cash = self.broker.get_cash()
        size = min(
            (equity * self.p.position_pct / 100) / price,
            cash * 0.99 / price
        )

        if size <= 0:
            return

        self.sell(size=size)
        self.entry_price = price
        self.position_type = 'short'
        self.last_trade_bar = len(self.data15)

        dt = self.data15.datetime.datetime(0)
        vol_ratio = self.data15.volume[0] / self.vol_sma_15m[0] if self.vol_sma_15m[0] > 0 else 0
        print(f"[{dt}] SHORT @ {price:.2f} | "
              f"SL: {self.stop_loss:.2f} | TP: {self.take_profit:.2f} | "
              f"ATR: {atr:.2f} | Vol: {vol_ratio:.1f}x")

    def _check_exits(self, uptrend_4h, downtrend_4h):
        """Check TP/SL and trend reversal exits."""
        if self.entry_price is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        if self.position_type == 'long':
            # Check TP
            if current_price >= self.take_profit:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                print(f"[{dt}] LONG TP HIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

            # Check SL
            if current_price <= self.stop_loss:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                print(f"[{dt}] LONG SL HIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

            # Check trend reversal exit
            if self.p.exit_on_trend_reversal and not uptrend_4h:
                pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                print(f"[{dt}] LONG TREND REVERSAL EXIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

        elif self.position_type == 'short':
            # Check TP
            if current_price <= self.take_profit:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                print(f"[{dt}] SHORT TP HIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

            # Check SL
            if current_price >= self.stop_loss:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                print(f"[{dt}] SHORT SL HIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

            # Check trend reversal exit
            if self.p.exit_on_trend_reversal and not downtrend_4h:
                pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
                print(f"[{dt}] SHORT TREND REVERSAL EXIT @ {current_price:.2f} ({pnl_pct:+.2f}%)")
                self.close()
                self._reset()
                return

    def _reset(self):
        """Reset position tracking."""
        self.entry_price = None
        self.position_type = None
        self.stop_loss = None
        self.take_profit = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = "BUY" if order.isbuy() else "SELL"
            print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: {trade.pnlcomm:.2f}")
