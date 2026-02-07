#!/usr/bin/env python3
# fetch_crypto_15m.py - Fetch 15m OHLCV data from Binance.US for any crypto pair
"""
Usage:
    python fetch_crypto_15m.py                    # Fetch SOL/USD (default)
    python fetch_crypto_15m.py --symbol BTC/USD   # Fetch BTC/USD
    python fetch_crypto_15m.py --symbol ETH/USD   # Fetch ETH/USD
    python fetch_crypto_15m.py --symbol SOL/USD --since 2023-01-01
"""

import argparse
import ccxt
import pandas as pd
from datetime import datetime
import time
from pathlib import Path


# Default start dates per symbol (approximate listing/availability dates)
DEFAULT_SINCE = {
    "SOL/USD": "2021-01-01T00:00:00Z",
    "BTC/USD": "2019-01-01T00:00:00Z",
    "ETH/USD": "2019-01-01T00:00:00Z",
}


def fetch_15m_data(symbol: str, since_iso: str, output_dir: str = "data"):
    """Fetch 15m OHLCV data from Binance.US and save to CSV."""
    exchange = ccxt.binanceus({
        'enableRateLimit': True,
    })

    since = exchange.parse8601(since_iso)
    limit = 1000

    all_ohlcv = []
    print(f"Fetching {symbol} 15m from {exchange.iso8601(since)} ...")

    while True:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, '15m', since=since, limit=limit)
        except Exception as e:
            print(f"Error fetching: {e}")
            time.sleep(5)
            continue

        if not ohlcv:
            break

        all_ohlcv.extend(ohlcv)
        since = ohlcv[-1][0] + 1
        print(f"Fetched {len(ohlcv)} candles | Total: {len(all_ohlcv)} | "
              f"Latest: {exchange.iso8601(ohlcv[-1][0])}")
        time.sleep(1)

    if not all_ohlcv:
        print("No data fetched.")
        return None

    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)

    # Match backtrader expected columns
    df = df[['open', 'high', 'low', 'close', 'volume']]
    df['adj close'] = df['close']
    df['openinterest'] = 0

    # Generate output filename: e.g., sol_usd_15m_binance.csv
    ticker = symbol.replace("/", "_").lower()
    Path(output_dir).mkdir(exist_ok=True)
    output_file = f"{output_dir}/{ticker}_15m_binance.csv"
    df.to_csv(output_file)

    print(f"\nDone! Saved {len(df)} rows -> {output_file}")
    print(df.tail())
    return output_file


def main():
    parser = argparse.ArgumentParser(
        description="Fetch 15m OHLCV data from Binance.US",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fetch_crypto_15m.py                       # SOL/USD
  python fetch_crypto_15m.py --symbol BTC/USD      # BTC/USD
  python fetch_crypto_15m.py --symbol ETH/USD      # ETH/USD
  python fetch_crypto_15m.py -s SOL/USD --since 2023-01-01
        """,
    )

    parser.add_argument(
        "--symbol", "-s",
        default="SOL/USD",
        help="Trading pair (default: SOL/USD). Examples: BTC/USD, ETH/USD"
    )

    parser.add_argument(
        "--since",
        default=None,
        help="Start date (YYYY-MM-DD). Defaults vary by symbol."
    )

    parser.add_argument(
        "--output-dir", "-o",
        default="data",
        help="Output directory (default: data/)"
    )

    args = parser.parse_args()

    # Determine start date
    if args.since:
        since_iso = f"{args.since}T00:00:00Z"
    else:
        since_iso = DEFAULT_SINCE.get(args.symbol, "2021-01-01T00:00:00Z")

    fetch_15m_data(args.symbol, since_iso, args.output_dir)


if __name__ == "__main__":
    main()
