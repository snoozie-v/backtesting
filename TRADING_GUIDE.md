# Complete Trading Guide - V9 (Range) + V10 (Trend)

## Overview

This guide combines two complementary strategies:
- **V9**: Trade bounces in ranging/sideways markets
- **V10**: Trade pullbacks in trending markets

Together they cover all market conditions on the daily timeframe.

---

## Step 1: Identify Market Condition (Daily Chart)

Look at the **last 3 daily candles** and classify the market:

### UPTREND (Use V10)
- 3 consecutive **higher highs** AND **higher lows**
- Each day's high is above the previous day's high
- Each day's low is above the previous day's low

### DOWNTREND (Use V10)
- 3 consecutive **lower highs** AND **lower lows**
- Each day's high is below the previous day's high
- Each day's low is below the previous day's low

### RANGING (Use V9)
- Neither uptrend nor downtrend pattern
- Mixed/choppy price action
- No clear directional bias

---

## Step 2: Check Minimum Range Size

Calculate yesterday's range:
```
Range % = (Yesterday High - Yesterday Low) / Current Price × 100
```

| Strategy | Minimum Range Required |
|----------|------------------------|
| V9 (Range) | >= 4.0% |
| V10 (Trend) | >= 1.5% |

**If range is too small → No trade, wait for next day**

---

## Step 3: Entry Signals (Watch on 1-Hour Chart)

### V9 - RANGING MARKET

| Entry | Condition | Example |
|-------|-----------|---------|
| **LONG** | Price within **0.75%** of yesterday's LOW | Low = $100 → Enter at $100.75 or below |
| **SHORT** | Price within **0.75%** of yesterday's HIGH | High = $110 → Enter at $109.18 or above |

### V10 - TRENDING MARKET

| Trend | Entry | Condition | Example |
|-------|-------|-----------|---------|
| **UPTREND** | LONG | Price pulls back within **0.5%** of yesterday's LOW | Low = $100 → Enter at $100.50 or below |
| **DOWNTREND** | SHORT | Price rallies within **0.5%** of yesterday's HIGH | High = $110 → Enter at $109.45 or above |

**Key Difference:**
- V9 (Range): Trade BOTH directions at extremes
- V10 (Trend): Trade only WITH the trend on pullbacks

---

## Step 4: Calculate TP/SL Levels

### For LONG Trades

```
Effective Target = Yesterday High - (Range × Buffer%)
Effective Range  = Effective Target - Entry Price
Stop Loss        = Entry - (Effective Range / R:R Ratio)
TP1              = Entry + (Effective Range × 1/3)
TP2              = Entry + (Effective Range × 2/3)
TP3              = Effective Target
```

### For SHORT Trades

```
Effective Target = Yesterday Low + (Range × Buffer%)
Effective Range  = Entry Price - Effective Target
Stop Loss        = Entry + (Effective Range / R:R Ratio)
TP1              = Entry - (Effective Range × 1/3)
TP2              = Entry - (Effective Range × 2/3)
TP3              = Effective Target
```

### Strategy-Specific Values

| Parameter | V9 (Range) | V10 (Trend) |
|-----------|------------|-------------|
| Target Buffer | 4.5% | 5.0% |
| R:R Ratio | 2.0 | 2.5 |
| Cooldown | 1 hour | 11 hours |

---

## Step 5: Position Management

Split your position into **3 equal parts** (33.3% each):

| Event | Action | Move Stop Loss To |
|-------|--------|-------------------|
| TP1 Hit | Close 1/3 of position | Entry (breakeven) |
| TP2 Hit | Close 1/3 of position | TP1 level |
| TP3 Hit | Close final 1/3 | — |
| Stop Loss Hit | Close ALL remaining | — |

---

## Worked Example: V9 LONG (Ranging Market)

**Setup:**
- Last 3 days: choppy, no clear trend → RANGING
- Yesterday: High = $110, Low = $100 (Range = 10%)
- Current price: $100.50 (within 0.75% of low) ✓

**Entry:** Buy at $100.50

**Calculations (V9 params):**
```
Target Buffer    = 4.5%
Effective Target = $110 - ($10 × 4.5%) = $109.55
Effective Range  = $109.55 - $100.50 = $9.05
R:R Ratio        = 2.0
Stop Loss        = $100.50 - ($9.05 / 2) = $95.98
TP1              = $100.50 + $3.02 = $103.52
TP2              = $100.50 + $6.03 = $106.53
TP3              = $109.55
```

**Trade Management:**
1. Price hits $103.52 → Sell 1/3, move SL to $100.50 (breakeven)
2. Price hits $106.53 → Sell 1/3, move SL to $103.52
3. Price hits $109.55 → Sell final 1/3, done

---

## Worked Example: V9 SHORT (Ranging Market)

**Setup:**
- Last 3 days: choppy, no clear trend → RANGING
- Yesterday: High = $110, Low = $100 (Range = 10%)
- Current price: $109.20 (within 0.75% of high) ✓

**Entry:** Short at $109.20

**Calculations (V9 params):**
```
Target Buffer    = 4.5%
Effective Target = $100 + ($10 × 4.5%) = $100.45
Effective Range  = $109.20 - $100.45 = $8.75
R:R Ratio        = 2.0
Stop Loss        = $109.20 + ($8.75 / 2) = $113.58
TP1              = $109.20 - $2.92 = $106.28
TP2              = $109.20 - $5.83 = $103.37
TP3              = $100.45
```

**Trade Management:**
1. Price hits $106.28 → Cover 1/3, move SL to $109.20 (breakeven)
2. Price hits $103.37 → Cover 1/3, move SL to $106.28
3. Price hits $100.45 → Cover final 1/3, done

---

## Worked Example: V10 LONG (Uptrend Market)

**Setup:**
- Last 3 days: HH/HL pattern → UPTREND
- Yesterday: High = $115, Low = $108 (Range = 6.1%)
- Current price: $108.40 (within 0.5% of low) ✓

**Entry:** Buy at $108.40

**Calculations (V10 params):**
```
Target Buffer    = 5.0%
Effective Target = $115 - ($7 × 5.0%) = $114.65
Effective Range  = $114.65 - $108.40 = $6.25
R:R Ratio        = 2.5
Stop Loss        = $108.40 - ($6.25 / 2.5) = $105.90
TP1              = $108.40 + $2.08 = $110.48
TP2              = $108.40 + $4.17 = $112.57
TP3              = $114.65
```

**Trade Management:**
1. Price hits $110.48 → Sell 1/3, move SL to $108.40 (breakeven)
2. Price hits $112.57 → Sell 1/3, move SL to $110.48
3. Price hits $114.65 → Sell final 1/3, done

---

## Worked Example: V10 SHORT (Downtrend Market)

**Setup:**
- Last 3 days: LH/LL pattern → DOWNTREND
- Yesterday: High = $95, Low = $88 (Range = 7.6%)
- Current price: $94.60 (within 0.5% of high) ✓

**Entry:** Short at $94.60

**Calculations (V10 params):**
```
Target Buffer    = 5.0%
Effective Target = $88 + ($7 × 5.0%) = $88.35
Effective Range  = $94.60 - $88.35 = $6.25
R:R Ratio        = 2.5
Stop Loss        = $94.60 + ($6.25 / 2.5) = $97.10
TP1              = $94.60 - $2.08 = $92.52
TP2              = $94.60 - $4.17 = $90.43
TP3              = $88.35
```

**Trade Management:**
1. Price hits $92.52 → Cover 1/3, move SL to $94.60 (breakeven)
2. Price hits $90.43 → Cover 1/3, move SL to $92.52
3. Price hits $88.35 → Cover final 1/3, done

---

## Quick Reference Card

### Market Classification (3 Daily Candles)

| Pattern | Classification | Strategy |
|---------|----------------|----------|
| Higher highs + Higher lows | UPTREND | V10 (Long only) |
| Lower highs + Lower lows | DOWNTREND | V10 (Short only) |
| Mixed/No pattern | RANGING | V9 (Both directions) |

### Entry Parameters

| Parameter | V9 (Range) | V10 (Trend) |
|-----------|------------|-------------|
| Trend Lookback | 3 days | 2 days |
| Entry Threshold | 0.75% | 0.5% |
| Min Range | 4.0% | 1.5% |
| Target Buffer | 4.5% | 5.0% |
| R:R Ratio | 2:1 | 2.5:1 |
| Cooldown | 1 hour | 11 hours |
| Position Size | 90% | 94% |

### Backtest Performance (SOL)

| Metric | V9 (Range) | V10 (Trend) |
|--------|------------|-------------|
| Return | +168.5% | +150.0% |
| Win Rate | 64.9% | 63.8% |
| Max Drawdown | 31.6% | 14.7% |
| Trades | 57 | 58 |

---

## Pre-Trade Checklist

### Step 1: Market Condition
- [ ] Checked last 3 daily candles
- [ ] Classified as: UPTREND / DOWNTREND / RANGING

### Step 2: Range Check
- [ ] Calculated yesterday's range %
- [ ] Range meets minimum (V9: 4%, V10: 1.5%)

### Step 3: Entry
- [ ] Price within entry threshold of prev high/low
- [ ] Trade direction matches strategy rules
- [ ] Calculated all TP and SL levels

### Step 4: Execution
- [ ] Position sized correctly
- [ ] Stop loss order placed
- [ ] TP levels noted for manual execution

---

## Key Rules

1. **Identify the market first.** Trend or range determines which strategy to use.

2. **V9 = Mean reversion.** Trade bounces between yesterday's high and low in ranges.

3. **V10 = Trend following.** Buy dips in uptrends, short rallies in downtrends.

4. **Respect the minimum range.** Small ranges = noise. Skip those days.

5. **Scale out, don't go all-or-nothing.** The 3-part exit protects profits.

6. **Move stops as TPs hit.** Never let a winner turn into a loser.

7. **Cooldowns matter.** V10 especially needs patience (11 hours between trades).

---

## Notes

- Both strategies were optimized on SOL. Other assets may need different parameters.
- V10 has much lower drawdown (14.7% vs 31.6%) - trend trading is generally safer.
- Combined, these strategies give you a trade setup for any market condition.
- Average frequency: ~1 trade per week per strategy.
