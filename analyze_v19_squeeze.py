#!/usr/bin/env python3
"""
Analyze correlation between squeeze length and trade outcomes for V19.

Reconstructs squeeze length for each trade by replaying the 1H ATR percentile
rank from the raw price data, matching the exact logic in sol_strategy_v19.py.
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path


# === Config (must match v19 strategy params) ===
ATR_PERIOD = 14
LOOKBACK = 102
SQUEEZE_PCTILE = 25


def compute_atr(df_1h: pd.DataFrame) -> pd.Series:
    """
    Compute ATR(14) using Wilder's smoothing (matches backtrader's btind.ATR).
    Wilder's: seed = SMA of first `period` TRs, then (prev*(n-1) + cur) / n
    """
    high = df_1h['high']
    low = df_1h['low']
    close = df_1h['close']
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    n = ATR_PERIOD
    atr = np.full(len(tr), np.nan)

    # Seed: simple mean of first n TRs
    seed_end = n  # index n (inclusive), i.e., positions 0..n-1
    valid_start = tr.first_valid_index()
    if valid_start is None:
        return pd.Series(atr, index=df_1h.index)

    start_i = df_1h.index.get_loc(valid_start)
    seed_end_i = start_i + n - 1

    if seed_end_i >= len(tr):
        return pd.Series(atr, index=df_1h.index)

    tr_vals = tr.values
    atr[seed_end_i] = np.mean(tr_vals[start_i:seed_end_i + 1])

    for i in range(seed_end_i + 1, len(tr_vals)):
        if not np.isnan(tr_vals[i]) and not np.isnan(atr[i - 1]):
            atr[i] = (atr[i - 1] * (n - 1) + tr_vals[i]) / n

    return pd.Series(atr, index=df_1h.index)


def compute_pctile_rank(atr_series: pd.Series, idx: int, lookback: int) -> float:
    """
    Compute ATR percentile rank at position `idx` over prior `lookback` bars.
    Matches _atr_percentile_rank() in v19 exactly:
      count bars in [idx-lookback, idx-1] where ATR < ATR[idx]
    """
    current = atr_series.iloc[idx]
    if pd.isna(current) or current <= 0:
        return 50.0
    window = atr_series.iloc[max(0, idx - lookback):idx]
    count_below = (window < current).sum()
    return (count_below / lookback) * 100.0


def compute_squeeze_lengths(df_1h: pd.DataFrame) -> pd.Series:
    """
    For every 1H bar, compute how many consecutive prior bars were in squeeze
    (pctile_rank < SQUEEZE_PCTILE) ending at that bar. Returns 0 if the bar
    itself is not a squeeze-exit (i.e., pctile_rank >= SQUEEZE_PCTILE while
    the prior bar was in squeeze).

    Returns a Series indexed by datetime with:
      -1  = bar is IN squeeze (not a breakout bar)
       0  = bar is not in squeeze and prior bar was also not in squeeze
      N>0 = bar is the squeeze breakout bar, squeeze lasted N 1H bars
    """
    atr = compute_atr(df_1h)
    n = len(df_1h)
    min_idx = ATR_PERIOD + LOOKBACK + 2

    results = {}
    in_squeeze = False
    squeeze_start_idx = None
    squeeze_bars = 0

    for i in range(n):
        dt = df_1h.index[i]
        if i < min_idx:
            results[dt] = 0
            continue

        rank = compute_pctile_rank(atr, i, LOOKBACK)

        if rank < SQUEEZE_PCTILE:
            # In squeeze
            if not in_squeeze:
                in_squeeze = True
                squeeze_start_idx = i
                squeeze_bars = 1
            else:
                squeeze_bars += 1
            results[dt] = -1  # squeeze bar
        else:
            if in_squeeze:
                # Squeeze just ended - this is a potential entry bar
                results[dt] = squeeze_bars
                in_squeeze = False
                squeeze_bars = 0
                squeeze_start_idx = None
            else:
                results[dt] = 0

    return pd.Series(results)


def load_results(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def load_1h_data(csv_path: str) -> pd.DataFrame:
    """Load 15m data and resample to 1H (matching backtrader's right-edge resampling)."""
    df = pd.read_csv(csv_path, parse_dates=True, index_col='timestamp')
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    # Resample to 1H using right-edge closed (matching backtrader bar2edge=True, rightedge=True)
    df_1h = df.resample('1h', closed='right', label='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).dropna()

    return df_1h


def find_entry_bar(entry_dt_str: str, squeeze_map: pd.Series, debug: bool = False) -> tuple:
    """
    Find which 1H bar corresponds to an entry.
    The entry happens on the breakout 1H bar. We look for the nearest
    squeeze breakout bar (squeeze_length > 0) at or just before entry_dt.
    Returns (squeeze_length, matched_1h_dt) or (None, None).
    """
    entry_dt = pd.to_datetime(entry_dt_str)

    # Look for breakout bars within a window around entry.
    # The 1H bar fires the signal; the 15m order executes shortly after.
    # Use a generous window: 6H before to 1H after entry.
    window_start = entry_dt - pd.Timedelta(hours=6)
    window_end = entry_dt + pd.Timedelta(hours=1)

    candidates = squeeze_map[
        (squeeze_map.index >= window_start) &
        (squeeze_map.index <= window_end) &
        (squeeze_map > 0)
    ]

    if debug:
        nearby = squeeze_map[
            (squeeze_map.index >= entry_dt - pd.Timedelta(hours=8)) &
            (squeeze_map.index <= entry_dt + pd.Timedelta(hours=2))
        ]
        print(f"  entry={entry_dt_str}, window=[{window_start}, {window_end}]")
        print(f"  nearby squeeze_map values:\n{nearby[nearby != -1].head(20)}")

    if candidates.empty:
        return None, None

    # Prefer bars AT OR BEFORE the entry (signal before execution)
    before = candidates[candidates.index <= entry_dt]
    if not before.empty:
        matched_dt = before.index[-1]  # most recent before entry
    else:
        matched_dt = candidates.index[0]  # fallback: first after

    sq_len = squeeze_map[matched_dt]
    return int(sq_len), matched_dt


def bucket_squeeze(sq_len: int) -> str:
    if sq_len <= 5:
        return "Short (1-5)"
    elif sq_len <= 12:
        return "Medium (6-12)"
    elif sq_len <= 24:
        return "Long (13-24)"
    else:
        return "Very Long (25+)"


def run_fresh_backtest() -> list:
    """Re-run v19 with squeeze_bars tracking to get exact data."""
    import sys, io, contextlib
    sys.path.insert(0, '.')
    from backtest import run_backtest

    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        result = run_backtest(
            strategy_name='v19',
            params_override={
                'lookback': 102,
                'squeeze_pctile': 25,
                'atr_mult_long': 3.25,
                'atr_mult_short': 8.0,
                'early_be_trig': 0.3,
                'early_be_dest': -0.5,
            },
            notes='squeeze_bars analysis run',
            verbose=False,
            save=False,
        )
    return result.trades or []


def main():
    print("Running v19 backtest with squeeze_bars tracking...")
    trades = run_fresh_backtest()
    print(f"  {len(trades)} trades loaded with squeeze_bars")

    matched = []
    for t in trades:
        sq_len = t["market_context"].get("squeeze_bars")
        if sq_len is None:
            continue
        matched.append({
            "entry_dt": t["entry_dt"],
            "exit_dt": t["exit_dt"],
            "direction": t["direction"],
            "r_multiple": t["r_multiple"],
            "pnl_net": t["pnl_net"],
            "bars_held": t["bars_held"],
            "squeeze_length": sq_len,
            "squeeze_bucket": bucket_squeeze(sq_len),
            "winner": t["r_multiple"] is not None and t["r_multiple"] > 0,
            "mfe_r": t["market_context"].get("mfe_r", None),
            "volatility": t["market_context"].get("volatility", ""),
            "regime": t["market_context"].get("regime", ""),
            "atr_percentile": t["market_context"].get("atr_percentile", None),
        })

    df = pd.DataFrame(matched)
    df = df.sort_values("squeeze_length")

    print("\n" + "=" * 70)
    print("V19 SQUEEZE LENGTH vs TRADE OUTCOME ANALYSIS")
    print("=" * 70)

    # --- Overall stats ---
    print(f"\nTotal matched trades: {len(df)}")
    print(f"Overall win rate: {df['winner'].mean()*100:.1f}%")
    print(f"Overall avg R: {df['r_multiple'].mean():.2f}")
    print(f"Overall avg MFE: {df['mfe_r'].mean():.2f}")

    # --- Correlation ---
    print("\n--- Pearson Correlation (squeeze_length vs ...) ---")
    for col in ["r_multiple", "winner", "mfe_r", "bars_held"]:
        valid = df[["squeeze_length", col]].dropna()
        if len(valid) > 5:
            corr = valid["squeeze_length"].corr(valid[col])
            print(f"  vs {col:15s}: r = {corr:+.3f}")

    # --- By squeeze bucket ---
    print("\n--- By Squeeze Length Bucket ---")
    bucket_order = ["Short (1-5)", "Medium (6-12)", "Long (13-24)", "Very Long (25+)"]
    bucket_stats = []
    for bucket in bucket_order:
        sub = df[df["squeeze_bucket"] == bucket]
        if len(sub) == 0:
            continue
        stats = {
            "Bucket": bucket,
            "N": len(sub),
            "Win%": f"{sub['winner'].mean()*100:.0f}%",
            "Avg R": f"{sub['r_multiple'].mean():.2f}",
            "Best R": f"{sub['r_multiple'].max():.2f}",
            "Worst R": f"{sub['r_multiple'].min():.2f}",
            "Avg MFE": f"{sub['mfe_r'].mean():.2f}",
            "Avg Hold(bars)": f"{sub['bars_held'].mean():.0f}",
        }
        bucket_stats.append(stats)

    if bucket_stats:
        bdf = pd.DataFrame(bucket_stats).set_index("Bucket")
        print(bdf.to_string())

    # --- Detailed breakdown by squeeze length (1-bar granularity, top ranges) ---
    print("\n--- Avg R by Exact Squeeze Length ---")
    by_len = df.groupby("squeeze_length").agg(
        N=("r_multiple", "count"),
        win_pct=("winner", lambda x: x.mean() * 100),
        avg_r=("r_multiple", "mean"),
        avg_mfe=("mfe_r", "mean"),
    ).reset_index()
    by_len.columns = ["sq_len", "N", "Win%", "Avg R", "Avg MFE"]

    print(f"\n{'sq_len':>6} {'N':>4} {'Win%':>6} {'Avg R':>7} {'Avg MFE':>8}")
    print("-" * 40)
    for _, row in by_len.iterrows():
        print(f"{row['sq_len']:>6.0f} {row['N']:>4.0f} {row['Win%']:>5.0f}% {row['Avg R']:>7.2f} {row['Avg MFE']:>8.2f}")

    # --- Direction breakdown ---
    print("\n--- By Direction and Squeeze Bucket ---")
    for direction in ["long", "short"]:
        sub = df[df["direction"] == direction]
        if len(sub) == 0:
            continue
        print(f"\n  {direction.upper()} trades ({len(sub)} total, {sub['winner'].mean()*100:.0f}% win rate):")
        for bucket in bucket_order:
            bsub = sub[sub["squeeze_bucket"] == bucket]
            if len(bsub) == 0:
                continue
            print(f"    {bucket}: N={len(bsub)}, Win={bsub['winner'].mean()*100:.0f}%, "
                  f"Avg R={bsub['r_multiple'].mean():.2f}, Avg MFE={bsub['mfe_r'].mean():.2f}")

    # --- Regime breakdown ---
    print("\n--- By Regime and Squeeze Bucket ---")
    for regime in df["volatility"].unique():
        sub = df[df["volatility"] == regime]
        print(f"\n  {regime} ({len(sub)} trades):")
        for bucket in bucket_order:
            bsub = sub[sub["squeeze_bucket"] == bucket]
            if len(bsub) == 0:
                continue
            print(f"    {bucket}: N={len(bsub)}, Win={bsub['winner'].mean()*100:.0f}%, "
                  f"Avg R={bsub['r_multiple'].mean():.2f}")

    # --- Top and bottom performers by squeeze length ---
    print("\n--- Best squeeze lengths (min 3 trades, ranked by Avg R) ---")
    best = by_len[by_len["N"] >= 3].sort_values("Avg R", ascending=False).head(10)
    print(best.to_string(index=False))

    print("\n--- Worst squeeze lengths (min 3 trades, ranked by Avg R) ---")
    worst = by_len[by_len["N"] >= 3].sort_values("Avg R", ascending=True).head(10)
    print(worst.to_string(index=False))

    # --- Threshold analysis: what min squeeze length maximizes win rate / avg R? ---
    print("\n--- Min Squeeze Threshold Analysis (trades with sq_len >= threshold) ---")
    print(f"{'min_sq':>6} {'N':>4} {'Win%':>6} {'Avg R':>7} {'Avg MFE':>8}")
    print("-" * 40)
    for threshold in [1, 3, 5, 8, 10, 12, 15, 20, 25]:
        sub = df[df["squeeze_length"] >= threshold]
        if len(sub) < 3:
            break
        print(f"{threshold:>6} {len(sub):>4} {sub['winner'].mean()*100:>5.0f}% "
              f"{sub['r_multiple'].mean():>7.2f} {sub['mfe_r'].mean():>8.2f}")

    # --- Save enriched trade list ---
    out_path = "results/v19_squeeze_analysis.csv"
    df.to_csv(out_path, index=False)
    print(f"\nEnriched trade data saved to: {out_path}")


if __name__ == "__main__":
    main()
