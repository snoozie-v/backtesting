# fetch_sol_binance_15m.py - Full historical 15m from Binance via CCXT
import ccxt
import pandas as pd
from datetime import datetime
import time

exchange = ccxt.binanceus({   # ← Use binanceus instead of binance
    'enableRateLimit': True,
})

symbol = 'SOL/USD'   # Binance.US uses USD pairs, not USDT (check exact symbol)
timeframe = '15m'
since = exchange.parse8601('2021-01-01T00:00:00Z')  # Start from ~SOL listing time
limit = 1000  # Binance max per request

all_ohlcv = []
print(f"Fetching {symbol} {timeframe} from {exchange.iso8601(since)} ...")

while True:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
    if not ohlcv:
        break
    all_ohlcv.extend(ohlcv)
    since = ohlcv[-1][0] + 1  # Next batch after last timestamp
    print(f"Fetched {len(ohlcv)} candles | Total: {len(all_ohlcv)} | Latest: {exchange.iso8601(ohlcv[-1][0])}")
    time.sleep(1)  # Avoid rate limit

if all_ohlcv:
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    
    # Match backtrader expected columns (lowercase)
    df = df[['open', 'high', 'low', 'close', 'volume']]
    df['adj close'] = df['close']  # Dummy for compatibility
    df['openinterest'] = 0
    
    output_file = "data/sol_usdt_15m_binance.csv"
    df.to_csv(output_file)
    print(f"\nDone! Saved {len(df)} rows → {output_file}")
    print(df.tail())
else:
    print("No data fetched.")
