# fetch_sol_data.py (modified for intraday 15m data)
# Note: yfinance limits 15m historical data to ~60 days max. If you need longer history, consider using 1h interval (up to ~2 years) 
# and adjusting the strategy accordingly, or sourcing data from another provider like Binance API.
import yfinance as yf
import pandas as pd
from datetime import datetime

symbol = "SOL-USD"
start_date = "2020-04-01"  # yfinance will auto-limit to available intraday history (~60d for 15m)
end_date = datetime.now().strftime("%Y-%m-%d")
interval = "15m"  # Changed to 15m for finer-grained data

print(f"Downloading {symbol} from {start_date} to {end_date} at {interval} interval...")

data = yf.download(symbol, start=start_date, end=end_date, interval=interval, progress=True)

# Handle columns
if isinstance(data.columns, pd.MultiIndex):
    data.columns = [col[0].lower() for col in data.columns]
else:
    data.columns = [col.lower() for col in data.columns]

# Add placeholder for openinterest (if needed for futures-like data)
data['openinterest'] = 0

data.to_csv("data/sol_usd_15m.csv")
print("Done! File saved → data/sol_usd_15m.csv")
print("\nLast 5 rows:\n", data.tail())
