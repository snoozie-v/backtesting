# Scalping Trading Guide - V12 High Win Rate Trend Scalper

## Strategy Overview

This is a **trend-following scalp strategy** optimized for high win rate through:
- Trading **WITH** the 4H trend only (no counter-trend trades)
- **Tight take profit** (0.5%) - hit target before reversal
- **Wide stop loss** (6%) - avoid getting stopped on noise
- **RSI momentum confirmation** - enter on oversold/overbought extremes

**Optimized Parameters** (26 Optuna trials, best return: 86.73%):
| Parameter | Value |
|-----------|-------|
| EMA Fast (4H) | 9 |
| EMA Slow (4H) | 25 |
| Trend Strength | 1.2% |
| RSI Period (15m) | 11 |
| RSI Oversold | 29 |
| RSI Overbought | 72 |
| Pullback % | 1.25% |
| Take Profit | 0.5% |
| Stop Loss | 6.0% |

| Cooldown | 7 bars (1h 45m) |

---

## Step 1: Identify 4H Trend

Open your **4H chart** and add:
- **EMA 9** (Fast)
- **EMA 25** (Slow)

### Trend Rules

| Condition | Trend | Action |
|-----------|-------|--------|
| EMA 9 > EMA 25 by **1.2%+** | UPTREND | Look for LONG entries only |
| EMA 9 < EMA 25 by **1.2%+** | DOWNTREND | Look for SHORT entries only |
| EMAs within 1.2% | NO TREND | **Do not trade** |

**Calculate trend strength:**
```
Trend Strength % = ((EMA9 - EMA25) / EMA25) * 100
```

If absolute value < 1.2%, skip trading.

---

## Step 2: Entry Signals (15m Chart)

Switch to your **15m chart** and add:
- **RSI(11)**
- **12-bar High** (3-hour high)
- **12-bar Low** (3-hour low)

### LONG Entry (Uptrend Only)

All conditions must be true:
1. 4H trend is UP (EMA9 > EMA25 by 1.2%+)
2. RSI(11) <= **29** (oversold)
3. Price has pulled back **1.25%+** from 3-hour high

**Entry:** Market buy when all conditions met

### SHORT Entry (Downtrend Only)

All conditions must be true:
1. 4H trend is DOWN (EMA9 < EMA25 by 1.2%+)
2. RSI(11) >= **72** (overbought)
3. Price has rallied **1.25%+** from 3-hour low

**Entry:** Market sell when all conditions met

---

## Step 3: Take Profit & Stop Loss

| Trade Type | Take Profit | Stop Loss |
|------------|-------------|-----------|
| LONG | Entry + **0.5%** | Entry - **6.0%** |
| SHORT | Entry - **0.5%** | Entry + **6.0%** |

**Example LONG at $100:**
- TP: $100.50
- SL: $94.00

**Risk:Reward = 1:12** (but high win rate compensates)

---

## Step 4: Position Sizing

Use **1%** of available capital per trade on 100X SOL Leverage
---

## Step 5: Cooldown

After any trade (win or loss), wait **7 x 15m bars = 1 hour 45 minutes** before next entry.

This prevents overtrading and revenge trading.

---

## Pre-Trade Checklist

- [ ] 4H EMA9 vs EMA25 gap > 1.2%?
- [ ] Trend direction identified (UP or DOWN)?
- [ ] On 15m chart with RSI(11)?
- [ ] RSI at extreme (<=29 for long, >=72 for short)?
- [ ] Price pulled back 1.25% from recent swing?
- [ ] No trade in last 1h 45m?
- [ ] TP and SL levels calculated?
- [ ] Position size set at 1% w/ 100X Lev

---

## TradingView Setup

### Pine Script Indicator

Copy this into TradingView (Indicators > Pine Editor > New):

```pinescript
//@version=5
indicator("V12 Scalp Signals", overlay=true, max_lines_count=500, max_labels_count=500)

// === INPUTS ===
ema_fast_len = input.int(9, "EMA Fast (4H)")
ema_slow_len = input.int(25, "EMA Slow (4H)")
trend_strength = input.float(1.2, "Trend Strength %")
rsi_period = input.int(11, "RSI Period")
rsi_oversold = input.int(29, "RSI Oversold")
rsi_overbought = input.int(72, "RSI Overbought")
pullback_pct = input.float(1.25, "Pullback %")
tp_pct = input.float(0.5, "Take Profit %")
sl_pct = input.float(6.0, "Stop Loss %")
cooldown_bars = input.int(7, "Cooldown Bars")
show_tp_sl_lines = input.bool(true, "Show TP/SL Lines")
show_trade_labels = input.bool(true, "Show Trade Plan Labels")
show_historical = input.bool(true, "Show Historical Win/Loss")

// === 4H TREND (use on 15m chart - request 4H data) ===
ema_fast_4h = request.security(syminfo.tickerid, "240", ta.ema(close, ema_fast_len))
ema_slow_4h = request.security(syminfo.tickerid, "240", ta.ema(close, ema_slow_len))

trend_diff = ((ema_fast_4h - ema_slow_4h) / ema_slow_4h) * 100
uptrend = trend_diff > trend_strength
downtrend = trend_diff < -trend_strength

// === 15M ENTRY INDICATORS ===
rsi = ta.rsi(close, rsi_period)
recent_high = ta.highest(high, 12)
recent_low = ta.lowest(low, 12)

pullback_from_high = ((recent_high - close) / recent_high) * 100
rally_from_low = ((close - recent_low) / recent_low) * 100

// === COOLDOWN TRACKING ===
var int bars_since_signal = 999
bars_since_signal := bars_since_signal + 1

// === ENTRY CONDITIONS (with cooldown) ===
long_condition = uptrend and rsi <= rsi_oversold and pullback_from_high >= pullback_pct
short_condition = downtrend and rsi >= rsi_overbought and rally_from_low >= pullback_pct

long_signal = long_condition and bars_since_signal >= cooldown_bars
short_signal = short_condition and bars_since_signal >= cooldown_bars

// Reset cooldown on signal
if long_signal or short_signal
    bars_since_signal := 0

// === CALCULATE TP/SL LEVELS ===
long_tp = close * (1 + tp_pct / 100)
long_sl = close * (1 - sl_pct / 100)
short_tp = close * (1 - tp_pct / 100)
short_sl = close * (1 + sl_pct / 100)

// === TRACK ACTIVE TRADE FOR TP/SL LINES ===
var float active_entry = na
var float active_tp = na
var float active_sl = na
var int active_direction = 0  // 1 = long, -1 = short, 0 = none
var int active_bar = na
var line tp_line = na
var line sl_line = na
var line entry_line = na
var label trade_label = na

// === HISTORICAL TRADE TRACKING ===
var int total_wins = 0
var int total_losses = 0

// Check if active trade hit TP or SL
if active_direction == 1  // Long trade active
    if high >= active_tp
        // WIN - hit TP
        if show_historical
            label.new(bar_index, active_tp, "WIN", color=color.green, textcolor=color.white, style=label.style_label_down, size=size.small)
        total_wins := total_wins + 1
        active_direction := 0
        active_entry := na
        active_tp := na
        active_sl := na
    else if low <= active_sl
        // LOSS - hit SL
        if show_historical
            label.new(bar_index, active_sl, "LOSS", color=color.red, textcolor=color.white, style=label.style_label_up, size=size.small)
        total_losses := total_losses + 1
        active_direction := 0
        active_entry := na
        active_tp := na
        active_sl := na

if active_direction == -1  // Short trade active
    if low <= active_tp
        // WIN - hit TP
        if show_historical
            label.new(bar_index, active_tp, "WIN", color=color.green, textcolor=color.white, style=label.style_label_up, size=size.small)
        total_wins := total_wins + 1
        active_direction := 0
        active_entry := na
        active_tp := na
        active_sl := na
    else if high >= active_sl
        // LOSS - hit SL
        if show_historical
            label.new(bar_index, active_sl, "LOSS", color=color.red, textcolor=color.white, style=label.style_label_down, size=size.small)
        total_losses := total_losses + 1
        active_direction := 0
        active_entry := na
        active_tp := na
        active_sl := na

// === NEW SIGNAL - CREATE TP/SL LINES AND TRADE LABEL ===
if long_signal and active_direction == 0
    active_entry := close
    active_tp := long_tp
    active_sl := long_sl
    active_direction := 1
    active_bar := bar_index

    if show_tp_sl_lines
        tp_line := line.new(bar_index, long_tp, bar_index + 50, long_tp, color=color.green, width=2, style=line.style_dashed)
        sl_line := line.new(bar_index, long_sl, bar_index + 50, long_sl, color=color.red, width=2, style=line.style_dashed)
        entry_line := line.new(bar_index, close, bar_index + 50, close, color=color.blue, width=1, style=line.style_dotted)

    if show_trade_labels
        trade_label := label.new(bar_index, close,
             "LONG TRADE PLAN\n" +
             "Entry: $" + str.tostring(close, "#.##") + "\n" +
             "TP: $" + str.tostring(long_tp, "#.##") + " (+" + str.tostring(tp_pct) + "%)\n" +
             "SL: $" + str.tostring(long_sl, "#.##") + " (-" + str.tostring(sl_pct) + "%)\n" +
             "RSI: " + str.tostring(rsi, "#.#"),
             color=color.new(color.green, 20),
             textcolor=color.white,
             style=label.style_label_up,
             size=size.normal)

if short_signal and active_direction == 0
    active_entry := close
    active_tp := short_tp
    active_sl := short_sl
    active_direction := -1
    active_bar := bar_index

    if show_tp_sl_lines
        tp_line := line.new(bar_index, short_tp, bar_index + 50, short_tp, color=color.green, width=2, style=line.style_dashed)
        sl_line := line.new(bar_index, short_sl, bar_index + 50, short_sl, color=color.red, width=2, style=line.style_dashed)
        entry_line := line.new(bar_index, close, bar_index + 50, close, color=color.blue, width=1, style=line.style_dotted)

    if show_trade_labels
        trade_label := label.new(bar_index, close,
             "SHORT TRADE PLAN\n" +
             "Entry: $" + str.tostring(close, "#.##") + "\n" +
             "TP: $" + str.tostring(short_tp, "#.##") + " (-" + str.tostring(tp_pct) + "%)\n" +
             "SL: $" + str.tostring(short_sl, "#.##") + " (+" + str.tostring(sl_pct) + "%)\n" +
             "RSI: " + str.tostring(rsi, "#.#"),
             color=color.new(color.red, 20),
             textcolor=color.white,
             style=label.style_label_down,
             size=size.normal)

// === PLOT SIGNALS ===
plotshape(long_signal, "Long", shape.triangleup, location.belowbar, color.green, size=size.small)
plotshape(short_signal, "Short", shape.triangledown, location.abovebar, color.red, size=size.small)

// === PLOT EMAs (4H on 15m chart) ===
plot(ema_fast_4h, "EMA 9 (4H)", color.blue, 2)
plot(ema_slow_4h, "EMA 25 (4H)", color.orange, 2)

// === BACKGROUND COLOR FOR TREND ===
bgcolor(uptrend ? color.new(color.green, 90) : downtrend ? color.new(color.red, 90) : na)

// === INFO TABLE ===
var table info = table.new(position.top_right, 2, 8, bgcolor=color.new(color.black, 80))
if barstate.islast
    table.cell(info, 0, 0, "Trend", text_color=color.white)
    table.cell(info, 1, 0, uptrend ? "UP" : downtrend ? "DOWN" : "NONE", text_color=uptrend ? color.green : downtrend ? color.red : color.gray)
    table.cell(info, 0, 1, "Trend %", text_color=color.white)
    table.cell(info, 1, 1, str.tostring(trend_diff, "#.##") + "%", text_color=color.white)
    table.cell(info, 0, 2, "RSI(11)", text_color=color.white)
    table.cell(info, 1, 2, str.tostring(rsi, "#.#"), text_color=rsi <= rsi_oversold ? color.green : rsi >= rsi_overbought ? color.red : color.white)
    table.cell(info, 0, 3, "Pullback", text_color=color.white)
    table.cell(info, 1, 3, str.tostring(pullback_from_high, "#.##") + "%", text_color=color.white)
    table.cell(info, 0, 4, "Rally", text_color=color.white)
    table.cell(info, 1, 4, str.tostring(rally_from_low, "#.##") + "%", text_color=color.white)
    table.cell(info, 0, 5, "Cooldown", text_color=color.white)
    cooldown_remaining = math.max(0, cooldown_bars - bars_since_signal)
    table.cell(info, 1, 5, cooldown_remaining > 0 ? str.tostring(cooldown_remaining) + " bars" : "READY", text_color=cooldown_remaining > 0 ? color.yellow : color.green)
    table.cell(info, 0, 6, "Wins", text_color=color.white)
    table.cell(info, 1, 6, str.tostring(total_wins), text_color=color.green)
    table.cell(info, 0, 7, "Losses", text_color=color.white)
    table.cell(info, 1, 7, str.tostring(total_losses), text_color=color.red)

// === ALERTS ===
alertcondition(long_signal, "Long Signal", "V12 LONG: RSI oversold + pullback in uptrend")
alertcondition(short_signal, "Short Signal", "V12 SHORT: RSI overbought + rally in downtrend")
```

### RSI Panel Indicator (Separate Pane)

Add this as a **second indicator** for the RSI panel with zones:

```pinescript
//@version=5
indicator("V12 RSI Panel", overlay=false)

// === INPUTS ===
rsi_period = input.int(11, "RSI Period")
rsi_oversold = input.int(29, "RSI Oversold")
rsi_overbought = input.int(72, "RSI Overbought")

// === RSI CALCULATION ===
rsi = ta.rsi(close, rsi_period)

// === PLOT RSI LINE ===
plot(rsi, "RSI", color.purple, 2)

// === THRESHOLD LINES ===
hline(rsi_oversold, "Oversold", color.green, hline.style_dashed, 2)
hline(rsi_overbought, "Overbought", color.red, hline.style_dashed, 2)
hline(50, "Midline", color.gray, hline.style_dotted, 1)

// === COLORED ZONES ===
bgcolor(rsi <= rsi_oversold ? color.new(color.green, 80) : rsi >= rsi_overbought ? color.new(color.red, 80) : na)

// === FILL ZONES ===
upper_line = hline(100, color=color.new(color.white, 100))
lower_line = hline(0, color=color.new(color.white, 100))
ob_line = hline(rsi_overbought, color=color.new(color.white, 100))
os_line = hline(rsi_oversold, color=color.new(color.white, 100))

fill(upper_line, ob_line, color=color.new(color.red, 90), title="Overbought Zone")
fill(lower_line, os_line, color=color.new(color.green, 90), title="Oversold Zone")

// === SIGNAL DOTS ===
plotshape(rsi <= rsi_oversold, "Oversold Signal", shape.circle, location.absolute, color.green, 0, size=size.tiny)
plotshape(rsi >= rsi_overbought, "Overbought Signal", shape.circle, location.absolute, color.red, 0, size=size.tiny)
```

### How to Use in TradingView

1. Open **SOLUSDT** (or any pair) on **15-minute** timeframe
2. Add the indicator (Pine Editor > Add to Chart)
3. The indicator will:
   - Show **green background** when 4H is uptrend
   - Show **red background** when 4H is downtrend
   - Plot **green triangles** for long signals
   - Plot **red triangles** for short signals
   - Display info table with current readings

### Setting Up Alerts

1. Click the alert icon (clock) in TradingView
2. Condition: Select "V12 Scalp Signals"
3. Choose "Long Signal" or "Short Signal"
4. Set notification method (app, email, webhook)

---

## Manual TradingView Setup (No Pine Script)

If you prefer manual indicators:

### 4H Chart Setup
1. Add **EMA 9** (blue)
2. Add **EMA 25** (orange)
3. Watch for 1.2%+ gap between them

### 15m Chart Setup
1. Add **RSI(11)** with levels at 29 and 72
2. Add **Donchian Channel (12)** or manually track 12-bar high/low
3. Watch for signals per the rules above

---

## Risk Management Notes

- **Win rate focus**: This strategy prioritizes hitting TP quickly over big gains
- **Wide stops**: 6% SL means you need high win rate to be profitable

- **Cooldown is crucial**: Don't skip the 1h 45m wait between trades

---

## Adapting to Other Markets

This was optimized on **SOL/USD**. For other markets:

1. **Higher volatility assets** (memecoins, small caps): Consider wider TP (0.75-1%)
2. **Lower volatility assets** (BTC, ETH): Consider tighter SL (4-5%)
3. **Stocks/Forex**: May need different RSI thresholds due to different volatility profiles
4. **Always backtest** on new markets before live trading

---

## Quick Reference Card

```
LONG ENTRY:
  4H: EMA9 > EMA25 by 1.2%+
  15m: RSI(11) <= 29
  15m: Price down 1.25%+ from 3hr high
  TP: +0.5%  |  SL: -6.0%

SHORT ENTRY:
  4H: EMA9 < EMA25 by 1.2%+
  15m: RSI(11) >= 72
  15m: Price up 1.25%+ from 3hr low
  TP: -0.5%  |  SL: +6.0%

COOLDOWN: 1h 45m between trades
POSITION: 1% of capital on 100x Lev
```

---

# V13 - Trend Momentum Rider

## V13 Overview

V13 is designed to capture **BIGGER trend moves** by addressing V12's limitations:

| Feature | V12 (Scalper) | V13 (Momentum Rider) |
|---------|---------------|----------------------|
| Goal | High win rate | Bigger moves |
| TP | Fixed 0.5% | ATR trailing stop |
| SL | Fixed 6% | ATR-based (dynamic) |
| RSI | 29/72 (extreme) | 45/55 (lenient) |
| Primary Filter | RSI + Pullback | **Volume expansion** |
| OBV | Not used | Trend confirmation |
| Partials | None | 33% at 3x ATR |

## V13 Entry Rules

**LONG Entry (Uptrend):**
1. 4H: EMA 8 > EMA 21 by 0.8%+
2. 15m: Volume > 1.3x 20-period average
3. 15m: RSI(14) < 55 (not overbought)
4. 4H: OBV > OBV EMA(10) (bullish)

**SHORT Entry (Downtrend):**
1. 4H: EMA 8 < EMA 21 by 0.8%+
2. 15m: Volume > 1.3x 20-period average
3. 15m: RSI(14) > 45 (not oversold)
4. 4H: OBV < OBV EMA(10) (bearish)

## V13 Exit Rules

- **Initial Stop**: Entry +/- (ATR * 1.5)
- **Trailing Stop**: High/Low Water Mark +/- (ATR * 2.5)
- **Partial Profit**: Take 33% at 3x ATR gain, move stop to breakeven
- **Volume Climax Exit**: If volume > 2.5x average with < 0.3% price move, tighten stop

## V13 TradingView Pine Script

```pinescript
//@version=5
indicator("V13 Trend Momentum Rider", overlay=true, max_lines_count=100, max_labels_count=100)

// === INPUTS ===
ema_fast_len = input.int(8, "EMA Fast")
ema_slow_len = input.int(21, "EMA Slow")
trend_strength_min = input.float(0.8, "Min Trend Strength %")
vol_sma_period = input.int(20, "Volume SMA Period")
vol_expansion_mult = input.float(1.3, "Volume Expansion Multiplier")
vol_climax_mult = input.float(2.5, "Volume Climax Multiplier")
rsi_period = input.int(14, "RSI Period")
rsi_oversold = input.int(45, "RSI Oversold")
rsi_overbought = input.int(55, "RSI Overbought")
obv_ema_period = input.int(10, "OBV EMA Period")
atr_period = input.int(14, "ATR Period")
atr_trailing_mult = input.float(2.5, "ATR Trailing Multiplier")
atr_initial_mult = input.float(1.5, "ATR Initial Stop Multiplier")
cooldown_bars = input.int(8, "Cooldown Bars")

// === 4H DATA (from 15m chart) ===
ema_fast_4h = request.security(syminfo.tickerid, "240", ta.ema(close, ema_fast_len))
ema_slow_4h = request.security(syminfo.tickerid, "240", ta.ema(close, ema_slow_len))
atr_4h = request.security(syminfo.tickerid, "240", ta.atr(atr_period))
obv_4h = request.security(syminfo.tickerid, "240", ta.obv)
obv_ema_4h = request.security(syminfo.tickerid, "240", ta.ema(ta.obv, obv_ema_period))

// === TREND DETECTION ===
trend_diff = ((ema_fast_4h - ema_slow_4h) / ema_slow_4h) * 100
is_uptrend = trend_diff > trend_strength_min
is_downtrend = trend_diff < -trend_strength_min

// === VOLUME ANALYSIS ===
vol_sma = ta.sma(volume, vol_sma_period)
vol_ratio = vol_sma > 0 ? volume / vol_sma : 0
vol_expansion = vol_ratio >= vol_expansion_mult
vol_climax = vol_ratio >= vol_climax_mult

// === OBV CONFIRMATION ===
obv_bullish = obv_4h > obv_ema_4h
obv_bearish = obv_4h < obv_ema_4h

// === RSI ===
rsi = ta.rsi(close, rsi_period)

// === COOLDOWN ===
var int bars_since_signal = 999
bars_since_signal := bars_since_signal + 1

// === ENTRY CONDITIONS ===
long_condition = is_uptrend and vol_expansion and rsi < rsi_overbought and obv_bullish
short_condition = is_downtrend and vol_expansion and rsi > rsi_oversold and obv_bearish

long_signal = long_condition and bars_since_signal >= cooldown_bars
short_signal = short_condition and bars_since_signal >= cooldown_bars

if long_signal or short_signal
    bars_since_signal := 0

// === ATR STOP LEVELS ===
atr_trail_distance = atr_4h * atr_trailing_mult
atr_initial_distance = atr_4h * atr_initial_mult

// === TRADE TRACKING ===
var float active_entry = na
var float active_hwm = na
var float active_lwm = na
var float initial_stop = na
var int active_direction = 0
var int total_wins = 0
var int total_losses = 0

// Track positions
if active_direction == 1
    active_hwm := math.max(active_hwm, high)
    trailing_stop = active_hwm - atr_trail_distance
    active_stop = math.max(trailing_stop, initial_stop)
    if low <= active_stop
        if close > active_entry
            total_wins := total_wins + 1
            label.new(bar_index, low, "WIN", color=color.green, textcolor=color.white, style=label.style_label_up, size=size.small)
        else
            total_losses := total_losses + 1
            label.new(bar_index, low, "LOSS", color=color.red, textcolor=color.white, style=label.style_label_up, size=size.small)
        active_direction := 0
        active_entry := na

if active_direction == -1
    active_lwm := math.min(active_lwm, low)
    trailing_stop = active_lwm + atr_trail_distance
    active_stop = math.min(trailing_stop, initial_stop)
    if high >= active_stop
        if close < active_entry
            total_wins := total_wins + 1
            label.new(bar_index, high, "WIN", color=color.green, textcolor=color.white, style=label.style_label_down, size=size.small)
        else
            total_losses := total_losses + 1
            label.new(bar_index, high, "LOSS", color=color.red, textcolor=color.white, style=label.style_label_down, size=size.small)
        active_direction := 0
        active_entry := na

// New entries
if long_signal and active_direction == 0
    active_entry := close
    active_hwm := close
    initial_stop := close - atr_initial_distance
    active_direction := 1
    label.new(bar_index, low,
         "LONG\nEntry: $" + str.tostring(close, "#.##") +
         "\nATR Stop: $" + str.tostring(initial_stop, "#.##") +
         "\nVol: " + str.tostring(vol_ratio, "#.#") + "x",
         color=color.new(color.green, 20), textcolor=color.white, style=label.style_label_up)

if short_signal and active_direction == 0
    active_entry := close
    active_lwm := close
    initial_stop := close + atr_initial_distance
    active_direction := -1
    label.new(bar_index, high,
         "SHORT\nEntry: $" + str.tostring(close, "#.##") +
         "\nATR Stop: $" + str.tostring(initial_stop, "#.##") +
         "\nVol: " + str.tostring(vol_ratio, "#.#") + "x",
         color=color.new(color.red, 20), textcolor=color.white, style=label.style_label_down)

// === PLOTTING ===
// EMAs
plot(ema_fast_4h, "EMA 8 (4H)", color.blue, 2)
plot(ema_slow_4h, "EMA 21 (4H)", color.orange, 2)

// Trend background
bgcolor(is_uptrend ? color.new(color.green, 90) : is_downtrend ? color.new(color.red, 90) : na)

// OBV divergence warning (price trending but OBV disagrees)
obv_divergence = (is_uptrend and obv_bearish) or (is_downtrend and obv_bullish)
bgcolor(obv_divergence ? color.new(color.orange, 85) : na, title="OBV Divergence")

// Volume expansion markers
plotshape(vol_expansion and is_uptrend and not long_signal, "Vol Expansion Up", shape.diamond, location.belowbar, color.new(color.green, 50), size=size.tiny)
plotshape(vol_expansion and is_downtrend and not short_signal, "Vol Expansion Down", shape.diamond, location.abovebar, color.new(color.red, 50), size=size.tiny)

// Volume climax warning
plotshape(vol_climax, "Volume Climax", shape.xcross, location.abovebar, color.yellow, size=size.normal)

// Entry signals
plotshape(long_signal, "Long Signal", shape.triangleup, location.belowbar, color.green, size=size.normal)
plotshape(short_signal, "Short Signal", shape.triangledown, location.abovebar, color.red, size=size.normal)

// ATR trailing stop bands (only when in position)
plot(active_direction == 1 ? active_hwm - atr_trail_distance : na, "Long Trail Stop", color.green, 1, plot.style_stepline)
plot(active_direction == -1 ? active_lwm + atr_trail_distance : na, "Short Trail Stop", color.red, 1, plot.style_stepline)

// === INFO TABLE ===
var table info = table.new(position.top_right, 2, 9, bgcolor=color.new(color.black, 80))
if barstate.islast
    table.cell(info, 0, 0, "Trend", text_color=color.white)
    table.cell(info, 1, 0, is_uptrend ? "UP" : is_downtrend ? "DOWN" : "NONE", text_color=is_uptrend ? color.green : is_downtrend ? color.red : color.gray)
    table.cell(info, 0, 1, "Strength", text_color=color.white)
    table.cell(info, 1, 1, str.tostring(trend_diff, "#.##") + "%", text_color=color.white)
    table.cell(info, 0, 2, "Vol Ratio", text_color=color.white)
    table.cell(info, 1, 2, str.tostring(vol_ratio, "#.#") + "x", text_color=vol_expansion ? color.green : color.gray)
    table.cell(info, 0, 3, "OBV", text_color=color.white)
    table.cell(info, 1, 3, obv_bullish ? "BULL" : "BEAR", text_color=obv_bullish ? color.green : color.red)
    table.cell(info, 0, 4, "RSI(14)", text_color=color.white)
    table.cell(info, 1, 4, str.tostring(rsi, "#.#"), text_color=color.white)
    table.cell(info, 0, 5, "ATR", text_color=color.white)
    table.cell(info, 1, 5, str.tostring(atr_4h, "#.##"), text_color=color.white)
    table.cell(info, 0, 6, "Cooldown", text_color=color.white)
    cooldown_remaining = math.max(0, cooldown_bars - bars_since_signal)
    table.cell(info, 1, 6, cooldown_remaining > 0 ? str.tostring(cooldown_remaining) + " bars" : "READY", text_color=cooldown_remaining > 0 ? color.yellow : color.green)
    table.cell(info, 0, 7, "Wins", text_color=color.white)
    table.cell(info, 1, 7, str.tostring(total_wins), text_color=color.green)
    table.cell(info, 0, 8, "Losses", text_color=color.white)
    table.cell(info, 1, 8, str.tostring(total_losses), text_color=color.red)

// === ALERTS ===
alertcondition(long_signal, "V13 Long", "V13 LONG: Volume expansion + uptrend + OBV bullish")
alertcondition(short_signal, "V13 Short", "V13 SHORT: Volume expansion + downtrend + OBV bearish")
alertcondition(vol_climax, "Volume Climax", "V13: Volume climax - potential reversal")
alertcondition(obv_divergence, "OBV Divergence", "V13: OBV diverging from price trend")
```

## V13 Quick Reference

```
LONG ENTRY:
  4H: EMA8 > EMA21 by 0.8%+
  15m: Volume > 1.3x average
  15m: RSI(14) < 55
  4H: OBV > OBV EMA(10)
  EXIT: ATR trailing stop (2.5x ATR from HWM)

SHORT ENTRY:
  4H: EMA8 < EMA21 by 0.8%+
  15m: Volume > 1.3x average
  15m: RSI(14) > 45
  4H: OBV < OBV EMA(10)
  EXIT: ATR trailing stop (2.5x ATR from LWM)

COOLDOWN: 8 bars (~2 hours)
PARTIAL: 33% at 3x ATR gain
```
