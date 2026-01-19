#!/usr/bin/env python3
# fetch_data.py - Fetch historical 15m data from Binance for any symbol
"""
Usage:
    python fetch_data.py SOL/USD          # Fetch SOL/USD
    python fetch_data.py SUI/USD          # Fetch SUI/USD
    python fetch_data.py VET/USD          # Fetch VET/USD
    python fetch_data.py BTC/USD          # Fetch BTC/USD
    python fetch_data.py --list           # List available USD pairs
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import ccxt
import pandas as pd


def get_exchange():
    """Initialize Binance US exchange."""
    return ccxt.binanceus({
        'enableRateLimit': True,
    })


def list_usd_pairs():
    """List all available USD trading pairs on Binance US."""
    exchange = get_exchange()
    exchange.load_markets()

    usd_pairs = [s for s in exchange.symbols if s.endswith('/USD')]
    usd_pairs.sort()

    print(f"\nAvailable USD pairs on Binance US ({len(usd_pairs)} total):\n")

    # Print in columns
    cols = 4
    for i in range(0, len(usd_pairs), cols):
        row = usd_pairs[i:i+cols]
        print("  " + "  ".join(f"{p:<12}" for p in row))

    return usd_pairs


def fetch_ohlcv(symbol: str, timeframe: str = '15m', start_date: str = '2020-01-01'):
    """
    Fetch all historical OHLCV data for a symbol.

    Args:
        symbol: Trading pair (e.g., 'SOL/USD', 'SUI/USD')
        timeframe: Candle timeframe (default: 15m)
        start_date: Start date in YYYY-MM-DD format

    Returns:
        DataFrame with OHLCV data
    """
    exchange = get_exchange()

    # Verify symbol exists
    exchange.load_markets()
    if symbol not in exchange.symbols:
        print(f"Error: {symbol} not found on Binance US")
        print(f"Try running: python fetch_data.py --list")
        return None

    since = exchange.parse8601(f'{start_date}T00:00:00Z')
    limit = 1000  # Binance max per request

    all_ohlcv = []
    print(f"\nFetching {symbol} {timeframe} from {start_date}...")
    print("-" * 50)

    while True:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        except Exception as e:
            print(f"Error fetching data: {e}")
            break

        if not ohlcv:
            break

        all_ohlcv.extend(ohlcv)
        since = ohlcv[-1][0] + 1  # Next batch after last timestamp

        latest_date = exchange.iso8601(ohlcv[-1][0])[:10]
        print(f"Fetched {len(ohlcv):4d} candles | Total: {len(all_ohlcv):>7,} | Latest: {latest_date}")

        time.sleep(0.5)  # Respect rate limits

    if not all_ohlcv:
        print("No data fetched.")
        return None

    # Create DataFrame
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)

    # Remove duplicates (can happen at batch boundaries)
    df = df[~df.index.duplicated(keep='first')]

    return df


def save_data(df: pd.DataFrame, symbol: str, timeframe: str = '15m'):
    """Save DataFrame to CSV in the data directory."""
    Path('data').mkdir(exist_ok=True)

    # Create filename from symbol (e.g., SOL/USD -> sol_usd_15m_binance.csv)
    symbol_clean = symbol.lower().replace('/', '_')
    filename = f"data/{symbol_clean}_{timeframe}_binance.csv"

    # Add columns for backtrader compatibility
    df_out = df[['open', 'high', 'low', 'close', 'volume']].copy()
    df_out['adj close'] = df_out['close']
    df_out['openinterest'] = 0

    df_out.to_csv(filename)

    return filename


def main():
    parser = argparse.ArgumentParser(
        description="Fetch historical OHLCV data from Binance US",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fetch_data.py SOL/USD          # Fetch SOL data
  python fetch_data.py SUI/USD          # Fetch SUI data
  python fetch_data.py VET/USD          # Fetch VET data
  python fetch_data.py --list           # List all available pairs
  python fetch_data.py SOL/USD --start 2023-01-01  # Fetch from specific date
        """
    )

    parser.add_argument(
        'symbol',
        nargs='?',
        help="Trading pair to fetch (e.g., SOL/USD, SUI/USD)"
    )

    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help="List all available USD pairs"
    )

    parser.add_argument(
        '--start', '-s',
        default='2020-01-01',
        help="Start date in YYYY-MM-DD format (default: 2020-01-01)"
    )

    parser.add_argument(
        '--timeframe', '-t',
        default='15m',
        help="Candle timeframe (default: 15m)"
    )

    args = parser.parse_args()

    if args.list:
        list_usd_pairs()
        return 0

    if not args.symbol:
        parser.print_help()
        return 1

    # Normalize symbol format
    symbol = args.symbol.upper()
    if '/' not in symbol:
        symbol = f"{symbol}/USD"

    # Fetch data
    df = fetch_ohlcv(symbol, args.timeframe, args.start)

    if df is None:
        return 1

    # Save to file
    filename = save_data(df, symbol, args.timeframe)

    print("-" * 50)
    print(f"\nSaved {len(df):,} candles to {filename}")
    print(f"Date range: {df.index.min().date()} to {df.index.max().date()}")
    print(f"\nFirst few rows:")
    print(df.head())
    print(f"\nLast few rows:")
    print(df.tail())

    return 0


if __name__ == "__main__":
    sys.exit(main())
