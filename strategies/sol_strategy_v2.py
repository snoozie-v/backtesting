# strategies/sol_strategy_v2.py
import backtrader as bt
import backtrader.indicators as btind
import backtrader.talib as btlib

class SolStrategyV2(bt.Strategy):
    params = (
        # Decline detection
        ('decline_pct', 4.0),       # Loosened to catch more (was 5.0)
        ('decline_window', 5),      # Widened to catch longer sharp drops (was 3)
        
        # Rise detection
        ('rise_pct_max', None),     # Removed cap - any positive change counts
        ('rise_window_min', 3),     # Keep at 3 for now
        
        # Indicators (unchanged)
        ('ema_short', 9),
        ('ema_long', 26),
        ('ema_support1', 21),
        ('ema_support2', 100),
        ('rsi_period', 14),
        ('rsi_low', 40),
        ('chandemo_period', 14),
        ('chandemo_threshold', -50),
        
        # Entry/Exit (unchanged)
        ('volume_increase_pct', 10.0),
        ('rsi_exit', 70),
        ('stop_loss_pct', 5.0),
        
        # Filters (unchanged)
        ('min_avg_volume', 1000000),
        ('scale_in_amount', 0.5),
    )

    def __init__(self):
        # EMAs (unchanged)
        self.ema_short = btind.EMA(self.data.close, period=self.p.ema_short)
        self.ema_long = btind.EMA(self.data.close, period=self.p.ema_long)
        self.ema_support1 = btind.EMA(self.data.close, period=self.p.ema_support1)
        self.ema_support2 = btind.EMA(self.data.close, period=self.p.ema_support2)
        
        # Crossovers (unchanged)
        self.ema_crossover = btind.CrossOver(self.ema_short, self.ema_long)
        
        # RSI (unchanged)
        self.rsi = btind.RSI(self.data.close, period=self.p.rsi_period)
        
        # Chande Momentum Oscillator - keep but don't require for entry
        self.chandemo = btlib.CMO(self.data.close, timeperiod=self.p.chandemo_period)
        self.chandemo_cross = btind.CrossOver(self.chandemo, self.p.chandemo_threshold)
        
        # Average Volume (unchanged)
        self.avg_volume = btind.SMA(self.data.volume, period=20)
        
        # Track recent low (unchanged)
        self.recent_low = btind.Lowest(self.data.low(-1), period=10)
        
        # Internal states (unchanged)
        self.decline_detected = False
        self.rise_count = 0
        self.in_position = False
        self.entry_price = 0.0

    def next(self):
        if len(self) < max(self.p.decline_window, self.p.rise_window_min, self.p.ema_support2):
            return
        if self.avg_volume[0] < self.p.min_avg_volume:
            return
        
        # Calculate daily change once - always available
        daily_change_pct = ((self.data.close[0] - self.data.close[-1]) / self.data.close[-1]) * 100 if len(self) > 1 else 0.0
        
        # Bear market filter (still commented out)
        # if self.data.close[0] < self.ema_support2[0] and self.ema_support2[0] < self.ema_support2[-1]:
        #     return
        
        # Step 1: Detect sharp decline (if not already detected)
        if not self.decline_detected:
            declines = [((self.data.close[-i] - self.data.close[-i-1]) / self.data.close[-i-1] * 100) for i in range(1, self.p.decline_window + 1)]
            total_decline = sum(d for d in declines if d < 0)
            if total_decline <= -self.p.decline_pct:
                print(f"DECLINE DETECTED on {self.data.datetime.date(0)} | Total drop: {total_decline:.1f}%")
                self.decline_detected = True
                self.rise_count = 0
                return
        
        # Step 2: Check for gradual rise after decline
        if self.decline_detected:
            if daily_change_pct > 0:  # Any positive change
                self.rise_count += 1
            else:
                self.rise_count = 0
                if daily_change_pct <= -self.p.decline_pct / 3:
                    self.decline_detected = False
            
            if self.rise_count >= self.p.rise_window_min:
                print(f"RISE QUALIFIED on {self.data.datetime.date(0)} | Rise days: {self.rise_count}")
            
            if self.rise_count < self.p.rise_window_min:
                return
        
        # Step 3: Confirmations
        ema_bounce = (self.data.close[0] > self.ema_support1[0]) or (self.data.close[0] > self.ema_support2[0])
        chandemo_confirm = self.chandemo_cross[0] == 1
        
        # Log almost-entries (keep for debugging)
        if self.ema_crossover[0] == 1 and self.decline_detected and self.rise_count >= self.p.rise_window_min:
            print(f"ALMOST ENTRY on {self.data.datetime.date(0)} | Missing: bounce={not ema_bounce}, chande={not chandemo_confirm}")
        
        # Entry
        if not self.position and self.ema_crossover[0] == 1 and ema_bounce and self.decline_detected and self.rise_count >= self.p.rise_window_min:
            print(f"ENTRY TRIGGERED on {self.data.datetime.date(0)}")
            buy_size = self.broker.get_cash() / self.data.close[0] * 0.5
            self.buy(size=buy_size)
            self.in_position = True
            self.entry_price = self.data.close[0]
            self.decline_detected = False  # Reset
        
        # Scale-in: Now safe because daily_change_pct is always defined
        elif self.position and self.rise_count > self.p.rise_window_min and daily_change_pct > 0:
            if self.data.close[0] < self.entry_price * 0.98:
                print(f"SCALE-IN on {self.data.datetime.date(0)}")  # Optional log
                add_size = self.position.size * self.p.scale_in_amount
                self.buy(size=add_size)
                # Update average entry price
                total_size = self.position.size + add_size
                self.entry_price = (self.entry_price * self.position.size + self.data.close[0] * add_size) / total_size
        
        # Exit conditions
        if self.position:
            stop_price = self.recent_low[0] * (1 - self.p.stop_loss_pct / 100)
            if self.data.close[0] < stop_price or self.data.close[0] < self.ema_support2[0]:
                self.sell(size=self.position.size)
                self.in_position = False
                self.rise_count = 0
            
            elif self.rsi[0] > self.p.rsi_exit or self.ema_crossover[0] == -1:
                self.sell(size=self.position.size)
                self.in_position = False
                self.rise_count = 0    
