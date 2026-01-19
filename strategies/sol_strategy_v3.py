# strategies/sol_strategy_v3.py  # ← New version for improved exits + trailing stop
import backtrader as bt
import backtrader.indicators as btind
import backtrader.talib as btlib

class SolStrategyV3(bt.Strategy):
    """
    Updated version of SolStrategyV2 with improved exit logic:
    - Added trailing stop: % below high water mark since entry (locks in gains during runs)
    - Kept original stops: RSI > rsi_exit, EMA cross down, fixed stop below recent low or support EMA
    - Optional: Partial profit taking (e.g., sell 50% at target_pct profit) - uncomment if desired
    - Tune new params: trailing_pct (e.g., 10-15%), target_pct (e.g., 20-30%)
    """
    
    params = (
        # Existing params (unchanged from v2)
        ('decline_pct', 4.0),
        ('decline_window', 5),
        ('rise_pct_max', None),
        ('rise_window_min', 3),
        ('ema_short', 9),
        ('ema_long', 26),
        ('ema_support1', 21),
        ('ema_support2', 100),
        ('rsi_period', 14),
        ('rsi_low', 40),
        ('chandemo_period', 14),
        ('chandemo_threshold', -50),
        ('volume_increase_pct', 10.0),
        ('rsi_exit', 70),
        ('stop_loss_pct', 5.0),
        ('min_avg_volume', 1000000),
        ('scale_in_amount', 0.5),
        
        # New params for improved exits
        ('trailing_pct', 8.0),     # % trailing stop below high since entry (e.g., 12% = exit if drops 12% from peak)
        ('target_pct', 15.0),       # Optional: % profit to take partial (sell 50%) - set to 0 to disable
    )

    def __init__(self):
        # Indicators (unchanged)
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
        self.atr = btind.ATR(self.data, period=14)
        
        # New: For trailing stop
        self.high_water_mark = 0.0  # Highest close since entry
        
        # Internal states (unchanged)
        self.decline_detected = False
        self.rise_count = 0
        self.in_position = False
        self.entry_price = 0.0
        self.partial_taken = False  # For optional partial profit

    def next(self):
        if len(self) < max(self.p.decline_window, self.p.rise_window_min, self.p.ema_support2):
            return
        if self.avg_volume[0] < self.p.min_avg_volume:
            return
        
        # Daily change (unchanged)
        daily_change_pct = ((self.data.close[0] - self.data.close[-1]) / self.data.close[-1]) * 100 if len(self) > 1 else 0.0
        
        # Bear filter (still optional - uncomment to enable)
        # if self.data.close[0] < self.ema_support2[0] and self.ema_support2[0] < self.ema_support2[-1]:
        #     return
        
        # Decline detection (unchanged)
        if not self.decline_detected:
            declines = [((self.data.close[-i] - self.data.close[-i-1]) / self.data.close[-i-1] * 100) for i in range(1, self.p.decline_window + 1)]
            total_decline = sum(d for d in declines if d < 0)
            if total_decline <= -self.p.decline_pct:
                print(f"DECLINE DETECTED on {self.data.datetime.date(0)} | Total drop: {total_decline:.1f}%")
                self.decline_detected = True
                self.rise_count = 0
                return
        
        # Rise check (unchanged)
        if self.decline_detected:
            if daily_change_pct > 0:
                self.rise_count += 1
            else:
                self.rise_count = 0
                if daily_change_pct <= -self.p.decline_pct / 3:
                    self.decline_detected = False
            
            if self.rise_count >= self.p.rise_window_min:
                print(f"RISE QUALIFIED on {self.data.datetime.date(0)} | Rise days: {self.rise_count}")
            
            if self.rise_count < self.p.rise_window_min:
                return
        
        # Confirmations (unchanged)
        ema_bounce = (self.data.close[0] > self.ema_support1[0]) or (self.data.close[0] > self.ema_support2[0])
        chandemo_confirm = self.chandemo_cross[0] == 1
        
        # Almost-entry log (unchanged)
        if self.ema_crossover[0] == 1 and self.decline_detected and self.rise_count >= self.p.rise_window_min:
            print(f"ALMOST ENTRY on {self.data.datetime.date(0)} | Missing: bounce={not ema_bounce}, chande={not chandemo_confirm}")
        
        # Entry (unchanged)
        if not self.position and self.ema_crossover[0] == 1 and ema_bounce and self.decline_detected and self.rise_count >= self.p.rise_window_min:
            print(f"ENTRY TRIGGERED on {self.data.datetime.date(0)}")
            buy_size = self.broker.get_cash() / self.data.close[0] * 0.5
            self.buy(size=buy_size)
            self.in_position = True
            self.entry_price = self.data.close[0]
            self.high_water_mark = self.data.close[0]  # Init trailing
            self.partial_taken = False  # Reset partial
            self.decline_detected = False
        
        # Scale-in (unchanged)
        elif self.position and self.rise_count > self.p.rise_window_min and daily_change_pct > 0:
            if self.data.close[0] < self.entry_price * 0.98:
                print(f"SCALE-IN on {self.data.datetime.date(0)}")
                add_size = self.position.size * self.p.scale_in_amount
                self.buy(size=add_size)
                total_size = self.position.size + add_size
                self.entry_price = (self.entry_price * self.position.size + self.data.close[0] * add_size) / total_size
        
        # Exit conditions (improved)
        if self.position:
            # Update high water mark
            self.high_water_mark = max(self.high_water_mark, self.data.close[0])
            
            # Trailing stop
            trailing_stop = self.high_water_mark * (1 - self.p.trailing_pct / 100)
            if self.data.close[0] < trailing_stop:
                print(f"TRAILING STOP EXIT on {self.data.datetime.date(0)}")
                self.sell(size=self.position.size)
                self.in_position = False
                self.rise_count = 0
                return  # Early return after exit
            
            # Fixed stop loss (unchanged)
            stop_price = self.recent_low[0] * (1 - self.p.stop_loss_pct / 100)
            if self.data.close[0] < stop_price or self.data.close[0] < self.ema_support2[0]:
                print(f"STOP LOSS EXIT on {self.data.datetime.date(0)}")
                self.sell(size=self.position.size)
                self.in_position = False
                self.rise_count = 0
                return
            
            # Reversal / overbought exits (unchanged)
            if self.rsi[0] > self.p.rsi_exit or self.ema_crossover[0] == -1:
                print(f"REVERSAL EXIT on {self.data.datetime.date(0)}")
                self.sell(size=self.position.size)
                self.in_position = False
                self.rise_count = 0
                return
            
            # Optional: Partial profit take (uncomment to enable)
            # if not self.partial_taken and (self.data.close[0] - self.entry_price) / self.entry_price * 100 > self.p.target_pct:
            #     print(f"PARTIAL PROFIT on {self.data.datetime.date(0)}")
            #     sell_size = self.position.size * 0.5  # Sell half
            #     self.sell(size=sell_size)
            #     self.partial_taken = True
            #     # Update entry for remaining (optional)
            #     self.entry_price = self.data.close[0]  # Or keep original
