# Zone Trader Exercise – V15 Strategy  
Mark Douglas 20-Trade Discipline Challenge

From *Trading in the Zone* by Mark Douglas  
**Purpose**: Prove that trading is a probability game and that you can execute your system mechanically without emotional interference.

## Core Rules of the 20-Trade Exercise

1. Pick **ONE edge** only (V15 Zone Trader rules below)  
2. Execute it **exactly 20 times** — no skipping, no modifying rules, no “bad feeling” overrides  
3. Risk the **same dollar amount** on every trade (1% of starting capital)  
4. Take **every valid signal** the system produces  
5. Do **not** evaluate or judge results until all 20 trades are finished  
6. No revenge trading, no doubling up, no “making back” losses

## What You Are Proving to Yourself

- The edge performs over a meaningful sample size (not every trade wins)  
- You can follow rules mechanically without emotional hijacking  
- Losses are a normal, expected cost of doing business  
- The outcome of any single trade is statistically irrelevant  

---

## V15 Mechanical Trading Rules

### Pre-Session Checklist

Before each session:  
- Determine 4H trend: Is EMA9 clearly above or below EMA21?  
- If EMAs are within **0.1%** of each other → **NO TRADE** (deadzone)  
- Classify trend: **UPTREND** / **DOWNTREND** / **FLAT**  
- Check 1H chart EMA9 vs EMA21 position  
- Confirm cooldown: ≥ **6 hours** (6+ full 1H bars) since last trade exit  

### Entry Type A – EMA Crossover (1H Chart)

**Long**  
- 4H = UPTREND (EMA9 > EMA21 + deadzone clearance)  
- 1H EMA9 crosses **above** EMA21 on current closed bar  
- 1H volume > 20-period volume SMA  
- No open position  
- Cooldown elapsed  

**Short**  
- 4H = DOWNTREND (EMA9 < EMA21 + deadzone clearance)  
- 1H EMA9 crosses **below** EMA21 on current closed bar  
- 1H volume > 20-period volume SMA  
- No open position  
- Cooldown elapsed  

### Entry Type B – EMA Pullback (1H Chart)

**Long**  
- 4H = UPTREND  
- 1H EMA9 > EMA21 (trend confirmed on 1H)  
- Current 1H bar low touches or dips below EMA9  
- Current 1H bar **closes above** EMA9  
- 1H volume > 20-period volume SMA  
- No open position  
- Cooldown elapsed  

**Short**  
- 4H = DOWNTREND  
- 1H EMA9 < EMA21 (trend confirmed on 1H)  
- Current 1H bar high touches or pokes above EMA9  
- Current 1H bar **closes below** EMA9  
- 1H volume > 20-period volume SMA  
- No open position  
- Cooldown elapsed  

### Position Sizing (100× Leverage)

1. Risk per trade = Account equity × **1%** (e.g. $10,000 → $100 risk)  
2. Stop distance = **1.5 × ATR(14)** on 1H chart  
3. Position size = Risk amount ÷ Stop distance  
   Example: $100 risk ÷ $1.50 stop distance = **66.67 SOL**

### Exit Rules (Monitor every 15 minutes)

1. **Take Profit** — Price reaches:  
   Long: entry + **3.0 × ATR**  
   Short: entry – **3.0 × ATR**  
2. **Stop Loss** — Price reaches:  
   Long: entry – **1.5 × ATR**  
   Short: entry + **1.5 × ATR**  
3. **Breakeven Stop** — When price moves **+1R** (halfway to TP), move stop to entry price  
4. **Trend Reversal Exit** — 4H EMA9 crosses to opposite side of EMA21  
5. **Time Exit** — **48 hours** (48 full 1H bars) pass without TP/SL hit  

### Stop Management Philosophy

- **Never widen** a stop (classic emotional error)  
- Move stops **only toward profit** (one direction only)  
- Mandatory: Move to **breakeven** at +1R  
- Optional trailing: e.g. move stop to +1R profit level once price reaches +2R  
- **TP remains fixed** — let winners run to target mechanically  

### After Entry Checklist

- Record: entry price, SL, TP  
- Place exchange **stop-loss** order  
- Place exchange **take-profit** order  
- Set alert for breakeven trigger (price reaches +1R)  
- Set 48-hour time-exit reminder  

---

## Risk & Money Management Rules

- Max **1% risk per trade** (can increase to 2% after proving consistency)  
- **One open position** maximum per pair  
- **Daily stop**: cease trading after **–3%** loss in a day  
- **Weekly stop**: cease trading after **–6%** loss in a week  
- Stops move **only toward profit**, never away  
- Move to breakeven at **+1R**  
- Let TP hit mechanically — do not exit early out of fear  

---

## Trading Schedule (UTC – adjust to local time)

Check 4H bar close and scan for signals at:  
- 00:00  
- 04:00  
- 08:00  
- 12:00  
- 16:00  
- 20:00  

Between 4H checks: monitor 1H bar closes for entries.  
If in a trade: check 15-minute bars for exit conditions.

### Pairs to Monitor

- **SOL/USD** – primary focus  
- **BTC/USD** – highest liquidity  
- **ETH/USD** – strong secondary  

Expected frequency: ~0.5–1 trade per pair per day → **1–2 signals/day total**

---

## Trade Journal – 20-Trade Exercise

### Exercise Summary

| Field              | Value          |
|--------------------|----------------|
| Start Date         |                |
| Starting Capital   |                |
| Risk Per Trade     | 1%             |
| Pairs Traded       | SOL, BTC, ETH  |

### Trade Log

| #  | Date/Time       | Pair | Dir | Entry Type | Entry   | SL     | TP     | Exit Price | Exit Type | PnL ($) | PnL (R) | Notes |
|----|-----------------|------|-----|------------|---------|--------|--------|------------|-----------|---------|---------|-------|
| 1  |                 |      |     |            |         |        |        |            |           |         |         |       |
| 2  |                 |      |     |            |         |        |        |            |           |         |         |       |
| 3  |                 |      |     |            |         |        |        |            |           |         |         |       |
| 4  |                 |      |     |            |         |        |        |            |           |         |         |       |
| 5  |                 |      |     |            |         |        |        |            |           |         |         |       |
| 6  |                 |      |     |            |         |        |        |            |           |         |         |       |
| 7  |                 |      |     |            |         |        |        |            |           |         |         |       |
| 8  |                 |      |     |            |         |        |        |            |           |         |         |       |
| 9  |                 |      |     |            |         |        |        |            |           |         |         |       |
| 10 |                 |      |     |            |         |        |        |            |           |         |         |       |
| 11 |                 |      |     |            |         |        |        |            |           |         |         |       |
| 12 |                 |      |     |            |         |        |        |            |           |         |         |       |
| 13 |                 |      |     |            |         |        |        |            |           |         |         |       |
| 14 |                 |      |     |            |         |        |        |            |           |         |         |       |
| 15 |                 |      |     |            |         |        |        |            |           |         |         |       |
| 16 |                 |      |     |            |         |        |        |            |           |         |         |       |
| 17 |                 |      |     |            |         |        |        |            |           |         |         |       |
| 18 |                 |      |     |            |         |        |        |            |           |         |         |       |
| 19 |                 |      |     |            |         |        |        |            |           |         |         |       |
| 20 |                 |      |     |            |         |        |        |            |           |         |         |       |

**Legend**  
- Dir: L = Long, S = Short  
- Entry Type: CROSS = Crossover, PULL = Pullback  
- Exit Type: TP, SL, TR (Trend Reversal), TE (Time Exit)  
- PnL (R): profit/loss in multiples of risk (TP = +2R, SL = –1R, etc.)

### Post-Exercise Review

| Metric                     | Value |
|----------------------------|-------|
| Total Trades               | 20    |
| Wins / Losses              |       |
| Win Rate                   |       |
| Total PnL ($)              |       |
| Total PnL (R)              |       |
| Average Win (R)            |       |
| Average Loss (R)           |       |
| Expectancy (R per trade)   |       |
| Largest Win (R)            |       |
| Largest Loss (R)           |       |
| Max Consecutive Wins       |       |
| Max Consecutive Losses     |       |
| Crossover Trades (W/L)     |       |
| Pullback Trades (W/L)      |       |

### Reflection Questions

1. Did I take every signal without hesitation?  
2. Did I ever consider skipping/modifying a trade? Why?  
3. Did I move any stops incorrectly? What happened?  
4. What was the emotionally hardest moment?  
5. Did live results align with backtested expectancy?  
6. What did this exercise teach me about myself as a trader?

Good luck with the 20-trade challenge — stay mechanical!
