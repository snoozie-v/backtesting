# Strategy Development Notes

Reference file for future strategy creation. Documents walk-forward validation results,
why strategies were deleted or failed, what parameters drove performance, and lessons learned.

**READ THIS BEFORE CREATING OR MODIFYING ANY STRATEGY.**

---

## Walk-Forward Validation Results (All Strategies)

Test methodology: 70% train / 30% test split on SOL 15m data (2021-01-01 to 2026-01-12).
50 Optuna trials on training data, then backtest optimized params on both periods.

| Strategy | IS Return | OOS Return | Retained | Trades (IS/OOS) | Assessment |
|----------|-----------|------------|----------|-----------------|------------|
| **v8_fast** | **+625%** | **+465%** | **74%** | **35 / 20** | **GOOD** |
| **v11** | **+14%** | **+5%** | **34%** | **161 / 18** | **FAIR** |
| v13 | +1068% | +136% | 13% | 372 / 194 | POOR |
| v8 | +506% | -1% | 0% | 10 / 3 | FAIL |
| v9 | +169% | +0% | 0% | 57 / 0 | FAIL |
| v14 | +9% | -7% | negative | 564 / 167 | FAIL |
| v16 | +88% | -11% | negative | 118 / 53 | FAIL |
| v15 | +137% | -53% | negative | 144 / ? | FAIL |
| v17 | +16% | -15% | negative | 501 / 228 | FAIL |
| v10 | +90% | +3% | 4% | 137 / 6 | POOR (deleted) |
| v12 | N/A | N/A | N/A | N/A | DELETED (negative expectancy) |
| v6, v7 | — | — | — | — | No optimizer objective |

**Only v8_fast and v11 are validated for out-of-sample use.**

---

## What Makes v8_fast Work (Study This)

v8_fast is the only strategy with GOOD walk-forward results. Understanding WHY it works
should guide all future strategy design.

**Core concept:** Detects large drops followed by gradual recoveries, then rides the
continuation with ATR-based trailing stops and partial profit-taking.

**Why it generalizes:**
1. **ATR-based exits** — stops and targets adapt to current volatility rather than using
   fixed percentages. When vol is high, stops are wider; when low, tighter. This is the
   single most important design choice.
2. **Pattern-based entries** — looks for a structural price pattern (drop + recovery) rather
   than indicator crossovers. Patterns persist across regimes better than indicator signals.
3. **Partial profit-taking** — locks in gains progressively rather than all-or-nothing exits.
   Reduces variance and protects against reversal after initial move.
4. **Moderate trade frequency** — 35 IS / 20 OOS trades. Enough to have statistical
   significance, few enough to avoid commission drag.
5. **Key params that matter:** `drop_window`, `min_drop_pct`, `atr_trailing_mult` are the
   drivers. These define the pattern shape and adaptive exit — not brittle thresholds.

**What v11 does right (FAIR):**
- Consistent win rate across regimes (27% IS and OOS — stable edge)
- Very low OOS drawdown (4.65%)
- Uses position sizing limits (`max_position_pct: 25%`) rather than all-in
- Relies on larger winners to offset frequent small losses (positive skew)

---

## Deleted Strategies

### V12 - High Win Rate Trend Scalper (DELETED)

**Core concept:** 4H EMA trend detection + 15m RSI pullback entries. Used tight take-profit
(1%) with wide stop-loss (3%) to artificially inflate win rate.

**Compare-all results:** -97.4% return, 98% max drawdown, 71% win rate, 2119 trades

**Why deleted:** The high win rate was misleading. Wide SL + tight TP means wins are small
and losses are large. Despite 71% win rate, the strategy lost almost everything due to
negative expectancy per trade. The 2119 trades compounded the negative edge through
commission drag (2119 trades * 0.1% commission = massive friction).

**Key params:**
- `tp_pct`: 1.0 (tight TP)
- `sl_pct`: 3.0 (wide SL, 3:1 loss-to-win ratio)
- `rsi_oversold`: 40, `rsi_overbought`: 60 (loose RSI thresholds = too many entries)
- `cooldown_bars`: 4 (short cooldown = overtrading)

**Optimizer note:** Optimized for win_rate metric, which rewarded the exact behavior
that destroyed returns. Required min 50 trades which pushed toward more entries.

---

### V10 - Trend Trading with Pullbacks (DELETED)

**Core concept:** Multi-day trend detection + pullback entries near previous day's
high/low levels. Targets continuation moves with configurable R:R ratio.

**Compare-all results:** +150.0% return, 14.7% max drawdown, 64% win rate, 58 trades

**Walk-forward results:** POOR — OOS retained only 4% of IS performance.
- In-sample: +90.36% return, 137 trades, 53% win rate, 18.35% max DD
- Out-of-sample: +3.33% return, 6 trades, 50% win rate, 4.87% max DD

**Why deleted:** Severe overfitting. Optimized params narrowed entry conditions so
tightly that only 6 trades fired over 2.5 years of unseen data. The strategy stopped
working when market conditions shifted.

**Key params (optimized):**
- `approach_pct`: 2.5, `target_buffer_pct`: 2.0, `min_range_pct`: 1.5 (all fixed % thresholds)
- `trend_lookback`: 2 (very short trend confirmation)

---

## Failed Walk-Forward Strategies (Annotated, Not Deleted)

### V8 - Drop Recovery (FAIL)

**Core concept:** Same pattern as v8_fast (drop + recovery) but uses daily/weekly
timeframes and fixed percentage stops instead of ATR-based.

**Walk-forward:** IS +506%, OOS -1%, 10 IS trades / 3 OOS trades

**Why it failed where v8_fast succeeded:**
- Fixed percentage stops (`trailing_pct: 19%`, `fixed_stop_pct: 12%`) instead of ATR-based
- Much fewer trades (10 IS) = higher variance, less statistical robustness
- Uses `weekly_ema_period` for trend filter — weekly signals change too slowly to adapt

**Lesson:** v8_fast is the evolved version. ATR-based exits > fixed percentage exits.

---

### V9 - Multi-Timeframe Trend (FAIL)

**Core concept:** Trend trading with pullbacks using multi-timeframe confirmation.

**Walk-forward:** IS +169%, OOS +0%, 57 IS trades / 0 OOS trades

**Key failure:** `min_range_pct: 4.0` means only days with >4% range qualify.
In lower-volatility regimes (2024-2025), this eliminated ALL entry opportunities.
Zero OOS trades = most extreme form of overfitting.

**Lesson:** Fixed volatility thresholds are regime-dependent. Use ATR or percentile-based
thresholds that adapt to current market conditions.

---

### V13 - Volume-Confirmed Trend Follower (POOR)

**Core concept:** EMA trend detection + volume expansion confirmation + RSI filters.
ATR-based trailing stops.

**Walk-forward:** IS +1068%, OOS +136%, 372 IS trades / 194 OOS trades, 13% retained

**Why it degraded:** Despite having ATR-based exits (like v8_fast), the entry conditions
relied on `trend_strength_min` and `vol_expansion_mult` — fixed thresholds that are
regime-sensitive. Win rate dropped from 44% to 31% OOS. Max drawdown worsened to 74%.

**Lesson:** ATR exits help but aren't enough alone. Entry conditions also need to be
regime-adaptive. Volume patterns change significantly across market cycles.

---

### V14 - 4H EMA Trend with 15M Crossover (FAIL)

**Core concept:** 4H EMA trend filter + 15m EMA crossover entries with volume confirmation
and ATR-based stops.

**Walk-forward:** IS +9%, OOS -7%, 564 IS trades / 167 OOS trades

**Why it failed:** Barely profitable even in-sample (+9% over 2.5 years). The 15m crossover
generates too many signals (564 trades) with tiny edge per trade. Commission drag at
0.1% per trade on 564 trades is significant. Win rate held steady (51%) but average
win size was too small.

**Lesson:** High-frequency crossover strategies need extremely tight spreads/commissions
to work. At 0.1% commission, you need meaningful edge per trade. If IS return is only +9%
over 564 trades, the per-trade edge is negligible.

---

### V15 - Zone Trader (FAIL)

**Core concept:** 4H EMA trend filter with deadzone + 1H crossover/pullback entries.
Designed for Mark Douglas "Trading in the Zone" 20-trade exercise.

**Walk-forward:** IS +137%, OOS -53% (lost money on unseen data)

**Parameter importance (fANOVA):**
1. `ema_slow_1h_period` — 41.1% of variance
2. `trend_deadzone_pct` — 18.9%
3. `cooldown_bars` — 8.1%
4. Top 3 params account for 68% of variance
5. 11 params with <5% importance (noise)

**Lesson:** When 1 parameter drives 41% of variance, the strategy is really just that
parameter. The rest is noise dressing. Reducing low-importance params to fixed values
would make optimization faster and reduce overfitting dimensions.

---

### V16 - Multi-Signal Trend Follower (FAIL)

**Core concept:** 4H EMA trend with deadzone + multiple entry signal types (convergence,
RSI divergence, wick rejection) + volume confirmation.

**Walk-forward:** IS +88%, OOS -11%, 118 IS trades / 53 OOS trades

**Why it failed:** Complex entry logic with many parameters creates a large search space
that overfits easily. The multiple entry types (convergence, divergence, rejection) each
have their own thresholds — too many knobs to tune reliably.

**Lesson:** Complexity is the enemy of robustness. Multiple entry types sound good in
theory but each adds parameters that can overfit. Better to have one well-understood
entry signal than three mediocre ones.

---

### V17 - ATR Swing Scalper (FAIL)

**Core concept:** 4H EMA trend scoring + wick rejection entries on 1H (looking for candles
that reject from pullback zones near EMAs) + 15m momentum filter (EMA5) + EMA pullback
entries as a second signal type. ATR-based exits with partial profit-taking (TP1 → breakeven
→ TP2 → trail).

**Walk-forward:** IS +16%, OOS -15%, 501 IS trades / 228 OOS trades

**Why it failed:** Despite having ATR-based exits and partial profit-taking (features that
made v8_fast work), the entry conditions were too numerous and complex:
- Wick rejection with tunable `wick_ratio` threshold
- Pullback zone defined by `pullback_zone_mult * ATR`
- EMA pullback as a second entry type
- 15m momentum confirmation via EMA5
- 10 optimizable parameters

The high trade count (501 IS / 228 OOS) with marginal per-trade edge meant commissions
dominated. The optimizer found params that barely worked in-sample (+16%) and the small
edge didn't survive OOS.

**Lesson:** Multiple entry filters (wick rejection + pullback zone + momentum + trend score)
create complexity without creating edge. The strategy tried to combine ideas from v15
(EMA pullback) with new concepts (wick rejection) but each added parameters that could
overfit. Compare with v8_fast which uses ONE structural pattern entry — simpler is better.

---

## Design Principles for New Strategies

Based on walk-forward testing every strategy in this project, these are the patterns
that separate strategies that work from those that don't:

### DO (What v8_fast and v11 got right)

1. **Use ATR-based exits.** This is the #1 predictor of walk-forward success. ATR adapts
   to current volatility so stops and targets stay proportional to market conditions.
   Fixed percentage stops (v8: 19%, v9: approach_pct) break when volatility regime changes.

2. **Use pattern-based or structural entries** rather than indicator crossovers.
   v8_fast looks for a specific price structure (large drop → gradual recovery). This
   pattern exists in all market regimes. Indicator crossovers (v14's 15m EMA cross) are
   noisy and regime-dependent.

3. **Implement partial profit-taking.** v8_fast's `partial_sell_ratio` locks in gains
   progressively. This reduces max drawdown and improves consistency across regimes.

4. **Keep trade frequency moderate.** Sweet spot appears to be 20-60 trades per year.
   Too few (<10/year like v8, v10) = not enough data points, high variance.
   Too many (>200/year like v12, v14) = commission drag eats the edge.

5. **Use position sizing limits.** v11's `max_position_pct: 25%` survived better than
   strategies using 90-98% of capital per trade. Smaller positions = smaller drawdowns
   = more chances to recover from losing streaks.

6. **Target consistent win rate across regimes.** v11 had 27% win rate in both IS and OOS.
   A stable (even low) win rate with positive skew is more trustworthy than a high IS
   win rate that collapses OOS.

### DON'T (Common failure patterns)

1. **Don't use fixed percentage thresholds for entry filters.** `min_range_pct`,
   `approach_pct`, `min_drop_pct` as fixed values are the #1 cause of OOS failure.
   When volatility shifts, these thresholds either filter out everything (v9: 0 OOS trades)
   or let in everything (v13: degraded win rate).

2. **Don't optimize for win rate.** Always optimize for `final_value` or `expectancy`.
   Win rate optimization (v12) actively selects for tight TP + wide SL = negative expectancy.

3. **Don't add complexity for its own sake.** v16 had 3 entry types with separate params
   each. More entry types = more params = more overfitting dimensions. One good entry
   signal beats three mediocre ones.

4. **Don't trust in-sample results alone.** Every single strategy looked profitable
   in-sample. 8 out of 10 failed or degraded severely out-of-sample. Always run
   `--walk-forward` before considering a strategy viable.

5. **Don't ignore commission drag.** At 0.1% commission, a strategy needs meaningful
   per-trade edge. If 500+ trades produce only +9% return (v14), commissions are eating
   most of the gross profit.

6. **Don't use too many tunable parameters.** Each additional parameter is an additional
   dimension for the optimizer to overfit. If fANOVA shows >50% of params have <5%
   importance, fix those params to sensible defaults and only optimize what matters.

### ALWAYS (Process Requirements)

1. **Run `--walk-forward` on every new strategy** before considering it viable.
2. **Run `--importance` after optimization** to identify which params actually matter.
3. **Check OOS trade count** — if it drops below ~15 trades, the params are too restrictive.
4. **Compare OOS max drawdown** — if it's worse than IS, the strategy degrades under stress.
5. **Verify win rate stability** — large IS→OOS win rate drops indicate regime sensitivity.
