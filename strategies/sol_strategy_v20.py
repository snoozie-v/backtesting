# strategies/sol_strategy_v20.py
"""
SolStrategy v20 - BTC Pattern Detection → Short SOL (4 Params)
--------------------------------------------------------------
Detect bearish patterns (double top, H&S) on BTC 15m chart, then short SOL.
BTC leads altcoins — when BTC tops out, SOL follows.

Signal Chart: BTC 15m (datas[5], raw feed)
  - Swing detection + pattern recognition runs on every new BTC 15m bar
  - Neckline break on BTC 15m close triggers SHORT SOL

Trade Execution: SOL 15m/1H (datas[0], datas[1])
  - Entry price: SOL 15m close at signal bar
  - Stop: entry + SOL_ATR_1H × atr_stop_mult (pure ATR stop on SOL)
  - Position size: risk_mgr.calculate_position_size(equity, stop_distance)
  - Exits: R-based partials on SOL 15m (30/30/30/10, stop ratcheting, ATR trail)

Regime Filter: Block entries when SOL daily trend == "uptrend"

Data feeds (expected index order):
  0 -> SOL 15m (base, entries/exits)
  1 -> SOL 1h  (ATR for stops)
  2 -> SOL 4h  (unused)
  3 -> SOL weekly (unused)
  4 -> SOL daily (regime filter)
  5 -> BTC 15m (pattern detection, raw feed)
"""

import backtrader as bt
import backtrader.indicators as btind
from risk_manager import RiskManager
from regime import MarketRegime


class SolStrategyV20(bt.Strategy):
    params = (
        # 4 optimizable
        ('swing_lookback', 5),       # Bars each side to confirm swing pivot (on BTC 15m)
        ('top_tolerance', 0.03),     # Max % diff between tops/shoulders (3%)
        ('atr_stop_mult', 2.5),     # SOL ATR mult for stop above entry
        ('atr_trail_mult', 3.0),     # SOL ATR trail mult for runner
        # Fixed
        ('atr_period', 14),          # ATR calc period on SOL 1H
        ('risk_per_trade_pct', 3.0), # Risk 3% of account at stop loss
        ('min_pattern_bars', 10),    # Min BTC 15m bars for double top pattern
        ('min_hs_bars', 15),         # Min BTC 15m bars for H&S pattern
    )

    def __init__(self):
        # SOL data feeds
        self.data15 = self.datas[0]     # SOL 15m: entries/exits
        self.data1h = self.datas[1]     # SOL 1H: ATR for stops
        self.data_daily = self.datas[4] # SOL daily: trend regime

        # BTC signal feed
        self.data_btc = self.datas[5]   # BTC 15m: pattern detection

        # SOL 1H ATR for stop placement
        self.atr_1h = btind.ATR(self.data1h, period=self.p.atr_period)

        # Regime classifier on SOL — block uptrend entries
        self.regime = MarketRegime(self.data_daily, self.datas[2])

        # Risk manager — default 30/30/30/10 with runner
        self.risk_mgr = RiskManager(risk_pct=self.p.risk_per_trade_pct)

        # Swing point storage on BTC: list of (bar_index, price) tuples
        self.swing_highs = []  # Last 8 BTC swing highs
        self.swing_lows = []   # Last 8 BTC swing lows

        # Position tracking (SOL)
        self.entry_price = None
        self.stop_distance = None       # 1R distance
        self.r_targets = {}             # {-1: stop, 1: 1R, 2: 2R, 3: 3R}
        self.current_stop = None        # Ratcheted stop price
        self.partials_taken = 0         # 0, 1, 2, or 3
        self.initial_size = 0           # Original position size
        self.low_water_mark = None      # For ATR trail on shorts (SOL price)
        self.entry_atr = None           # SOL 1H ATR snapshot at entry
        self.pattern_label = None       # "BTC_DOUBLE_TOP" or "BTC_HEAD_AND_SHOULDERS"

        # Bar tracking for BTC 15m new bar detection
        self.last_btc_len = 0
        self.last_btc_bar_idx = 0       # Monotonic BTC bar counter

    def next(self):
        # Need enough BTC data for swing detection
        min_btc_bars = 2 * self.p.swing_lookback + 1
        if len(self.data_btc) < min_btc_bars:
            return

        # Need enough SOL 1H data for ATR
        if len(self.data1h) < self.p.atr_period + 2:
            return

        # Detect new BTC 15m bar
        new_btc_bar = len(self.data_btc) > self.last_btc_len
        if new_btc_bar:
            self.last_btc_len = len(self.data_btc)
            self.last_btc_bar_idx += 1

            # Update swings on every new BTC bar
            self._detect_swings()

            # Check patterns only if not in position
            if not self.position:
                self._check_patterns()

        # If in position, check exits on every SOL 15m bar
        if self.position:
            self._check_short_exits()

    def _detect_swings(self):
        """Check if the BTC bar at [-swing_lookback] is a confirmed swing high/low."""
        lb = self.p.swing_lookback

        # Need at least 2*lb+1 bars for confirmation
        if len(self.data_btc) < 2 * lb + 1:
            return

        # The candidate bar is at index [-lb] (confirmed with lb bars after it)
        candidate_high = self.data_btc.high[-lb]
        candidate_low = self.data_btc.low[-lb]
        candidate_idx = self.last_btc_bar_idx - lb

        # Check swing high: candidate high > all surrounding bars
        is_swing_high = True
        for i in range(1, lb + 1):
            if self.data_btc.high[-lb - i] >= candidate_high:
                is_swing_high = False
                break
            if self.data_btc.high[-lb + i] >= candidate_high:
                is_swing_high = False
                break

        if is_swing_high:
            self.swing_highs.append((candidate_idx, candidate_high))
            if len(self.swing_highs) > 8:
                self.swing_highs = self.swing_highs[-8:]

        # Check swing low: candidate low < all surrounding bars
        is_swing_low = True
        for i in range(1, lb + 1):
            if self.data_btc.low[-lb - i] <= candidate_low:
                is_swing_low = False
                break
            if self.data_btc.low[-lb + i] <= candidate_low:
                is_swing_low = False
                break

        if is_swing_low:
            self.swing_lows.append((candidate_idx, candidate_low))
            if len(self.swing_lows) > 8:
                self.swing_lows = self.swing_lows[-8:]

    def _check_patterns(self):
        """Check for H&S (first) then double top patterns on BTC. Apply SOL regime filter."""
        btc_close = self.data_btc.close[0]
        sol_atr = self.atr_1h[0]
        if sol_atr <= 0:
            return

        # SOL regime filter: block uptrend (shorting SOL into uptrend is negative EV)
        blocked_by_regime = False
        regime_label = ""
        try:
            regime_info = self.regime.classify()
            trend = regime_info.get('trend', 'ranging')
            if trend == 'uptrend':
                blocked_by_regime = True
                regime_label = regime_info.get('regime', 'uptrend')
        except Exception:
            pass

        # Try H&S first (higher conviction)
        if self._check_head_and_shoulders(btc_close, sol_atr, blocked_by_regime, regime_label):
            return

        # Then try double top
        self._check_double_top(btc_close, sol_atr, blocked_by_regime, regime_label)

    def _check_double_top(self, btc_close, sol_atr, blocked_by_regime=False, regime_label=""):
        """Detect BTC double top pattern and enter short SOL on neckline break."""
        if len(self.swing_highs) < 2:
            return False

        # Last 2 BTC swing highs
        sh1_idx, sh1_price = self.swing_highs[-2]
        sh2_idx, sh2_price = self.swing_highs[-1]

        # Tops within tolerance
        avg_top = (sh1_price + sh2_price) / 2.0
        if abs(sh1_price - sh2_price) / avg_top > self.p.top_tolerance:
            return False

        # Pattern must span minimum bars
        if (sh2_idx - sh1_idx) < self.p.min_pattern_bars:
            return False

        # Find the lowest BTC swing low between the two tops (neckline)
        neckline = None
        for sl_idx, sl_price in self.swing_lows:
            if sh1_idx < sl_idx < sh2_idx:
                if neckline is None or sl_price < neckline:
                    neckline = sl_price

        if neckline is None:
            return False

        # Neckline break: BTC 15m close below neckline
        if btc_close >= neckline:
            return False

        # Pattern confirmed with neckline break — check SOL regime
        if blocked_by_regime:
            dt = self.data15.datetime.datetime(0)
            print(f"[{dt}] BLOCKED BTC_DOUBLE_TOP — SOL uptrend regime ({regime_label})")
            return True  # Pattern found but blocked

        self._enter_short(sol_atr, neckline, "BTC_DOUBLE_TOP")
        return True

    def _check_head_and_shoulders(self, btc_close, sol_atr, blocked_by_regime=False, regime_label=""):
        """Detect BTC head & shoulders pattern and enter short SOL on neckline break."""
        if len(self.swing_highs) < 3:
            return False

        # Last 3 BTC swing highs: left shoulder, head, right shoulder
        sh1_idx, sh1_price = self.swing_highs[-3]  # Left shoulder
        sh2_idx, sh2_price = self.swing_highs[-2]  # Head
        sh3_idx, sh3_price = self.swing_highs[-1]  # Right shoulder

        # Head must be highest
        if sh2_price <= sh1_price or sh2_price <= sh3_price:
            return False

        # Shoulders within tolerance of each other
        avg_shoulder = (sh1_price + sh3_price) / 2.0
        if abs(sh1_price - sh3_price) / avg_shoulder > self.p.top_tolerance:
            return False

        # Pattern must span minimum bars
        if (sh3_idx - sh1_idx) < self.p.min_hs_bars:
            return False

        # Find BTC troughs between shoulders and head
        trough1 = None  # Between left shoulder and head
        trough2 = None  # Between head and right shoulder
        for sl_idx, sl_price in self.swing_lows:
            if sh1_idx < sl_idx < sh2_idx:
                if trough1 is None or sl_price < trough1:
                    trough1 = sl_price
            elif sh2_idx < sl_idx < sh3_idx:
                if trough2 is None or sl_price < trough2:
                    trough2 = sl_price

        if trough1 is None or trough2 is None:
            return False

        # Neckline = max of the two troughs (conservative — higher neckline)
        neckline = max(trough1, trough2)

        # Neckline break: BTC 15m close below neckline
        if btc_close >= neckline:
            return False

        # Pattern confirmed with neckline break — check SOL regime
        if blocked_by_regime:
            dt = self.data15.datetime.datetime(0)
            print(f"[{dt}] BLOCKED BTC_HEAD_AND_SHOULDERS — SOL uptrend regime ({regime_label})")
            return True  # Pattern found but blocked

        self._enter_short(sol_atr, neckline, "BTC_HEAD_AND_SHOULDERS")
        return True

    def _enter_short(self, sol_atr, neckline, pattern_label):
        """Enter short SOL position with R-based sizing. Stop = SOL entry + SOL_ATR * mult."""
        equity = self.broker.getvalue()
        price = self.data15.close[0]  # SOL 15m entry price

        # Stop above entry using SOL 1H ATR (no BTC pattern high)
        stop_distance = sol_atr * self.p.atr_stop_mult

        if stop_distance <= 0:
            return

        size = self.risk_mgr.calculate_position_size(equity, stop_distance)
        if size <= 0:
            return

        # Cap at leverage limit
        max_size = (equity * 100) / price
        size = min(size, max_size * 0.95)

        self.sell(size=size)
        self.entry_price = price
        self.stop_distance = stop_distance
        self.entry_atr = sol_atr
        self.initial_size = size
        self.partials_taken = 0
        self.low_water_mark = price
        self.pattern_label = pattern_label

        # Calculate R-targets for short
        self.r_targets = self.risk_mgr.calculate_r_targets(price, stop_distance, 'short')
        self.current_stop = self.r_targets[-1]  # stop_price

        risk_amt = equity * self.risk_mgr.risk_pct
        dt = self.data15.datetime.datetime(0)
        print(f"[{dt}] SHORT [{pattern_label}] @ SOL {price:.2f} | "
              f"Size: {size:.4f} | Risk: ${risk_amt:.0f} ({self.p.risk_per_trade_pct}%) | "
              f"BTC neckline: {neckline:.2f} | SOL ATR: {sol_atr:.2f} | "
              f"Stop: {self.current_stop:.2f} (-1R) | "
              f"1R: {self.r_targets.get(1.0, 0):.2f} | "
              f"2R: {self.r_targets.get(2.0, 0):.2f} | "
              f"3R: {self.r_targets.get(3.0, 0):.2f}")

        self._entry_context = {
            "atr": round(sol_atr, 4),
            "direction": "short",
            "stop_distance": round(stop_distance, 4),
            "risk_pct": self.p.risk_per_trade_pct,
            "position_size": round(size, 4),
            "pattern": pattern_label,
        }

    def _check_short_exits(self):
        """Check R-based exits on every SOL 15m bar (short direction)."""
        if self.entry_price is None or self.stop_distance is None:
            return

        current_price = self.data15.close[0]
        dt = self.data15.datetime.datetime(0)

        # Update low water mark (price moving down = good for shorts)
        if self.low_water_mark is None or current_price < self.low_water_mark:
            self.low_water_mark = current_price

        # Check R-target partials (1R, 2R, 3R — price moving DOWN)
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
                    print(f"[{dt}] SHORT PARTIAL {self.partials_taken}/3 @ {current_price:.2f} "
                          f"(+{r_mult:.0f}R, covering {fraction:.0%}) | "
                          f"New stop: {self.current_stop:.2f}")
                    self.buy(size=partial_size)
                    return

        # Compute effective stop: ATR trail from LWM after any partial, ratchet floor always applies
        if self.partials_taken >= 1:
            trail_distance = self.entry_atr * self.p.atr_trail_mult
            # For shorts, trail stop goes UP from LWM
            trail_stop = self.low_water_mark + trail_distance
            # For shorts, effective stop is the LOWER of ratchet and trail (tighter)
            effective_stop = min(self.current_stop, trail_stop)
        else:
            effective_stop = self.current_stop

        # For shorts, stopped out when price goes ABOVE stop
        if current_price >= effective_stop:
            pnl_pct = ((self.entry_price - current_price) / self.entry_price) * 100
            r_mult = self.risk_mgr.calculate_r_multiple(
                self.entry_price, current_price, self.stop_distance, 'short')
            if self.partials_taken == 0:
                reason = "STOP (-1R)"
            elif self.partials_taken >= 3:
                reason = f"RUNNER TRAIL (after {self.partials_taken}R)"
            else:
                reason = f"ATR TRAIL (after {self.partials_taken}R)"
            print(f"[{dt}] SHORT {reason} @ {current_price:.2f} ({pnl_pct:+.2f}%, {r_mult:+.1f}R)"
                  + (f" | LWM: {self.low_water_mark:.2f}" if self.partials_taken >= 1 else ""))
            self.close()
            self._reset_state()

    def _reset_state(self):
        """Reset position tracking."""
        self.entry_price = None
        self.stop_distance = None
        self.r_targets = {}
        self.current_stop = None
        self.partials_taken = 0
        self.initial_size = 0
        self.low_water_mark = None
        self.entry_atr = None
        self.pattern_label = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = "SELL" if order.issell() else "BUY"
            print(f"    {action} EXECUTED @ {order.executed.price:.2f}, Size: {order.executed.size:.4f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f"    TRADE CLOSED - PnL: Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}")
