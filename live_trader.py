#!/usr/bin/env python3
# live_trader.py
"""
Live/Paper Trading Bot for V8 Fast Strategy

Usage:
    python live_trader.py --paper                    # Paper trading (default)
    python live_trader.py --paper --asset SOL        # Paper trade SOL
    python live_trader.py --paper --asset VET        # Paper trade VET
    python live_trader.py --live                     # LIVE trading (real money!)

IMPORTANT: Always test with --paper first!
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

import ccxt
import pandas as pd

from config import V8_FAST_SOL_PARAMS, BROKER

# ============================================================================
# CONFIGURATION
# ============================================================================

STATE_FILE = Path("data/trader_state.json")
LOG_FILE = Path("data/trader.log")

@dataclass
class TraderConfig:
    """Configuration for the live trader."""
    # Exchange settings
    exchange_id: str = "binanceus"

    # Trading settings
    asset: str = "SOL"
    quote: str = "USD"
    timeframe_15m: str = "15m"  # For entry/exit execution
    timeframe_4h: str = "4h"     # For drop/rise detection
    timeframe_daily: str = "1d"  # For EMA filter

    # Position sizing
    position_size_pct: float = 0.98  # Use 98% of available balance

    # Paper trading
    paper_mode: bool = True
    paper_balance: float = 10000.0

    # Polling interval (seconds)
    poll_interval: int = 60  # Check every minute (exits checked on 15m bars)

    @property
    def symbol(self) -> str:
        return f"{self.asset}/{self.quote}"


# ============================================================================
# STATE MANAGEMENT
# ============================================================================

@dataclass
class TraderState:
    """Persistent state for the trader."""
    # Position info
    in_position: bool = False
    entry_price: Optional[float] = None
    entry_time: Optional[str] = None
    position_size: float = 0.0
    entry_atr: Optional[float] = None

    # Tracking
    high_water_mark: Optional[float] = None
    partial_taken: bool = False

    # Strategy state
    drop_detected: bool = False
    rise_window_data: List[Dict] = None
    last_4h_bar_time: Optional[str] = None

    # Paper trading
    paper_balance: float = 10000.0
    paper_position_size: float = 0.0

    # Stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0

    def __post_init__(self):
        if self.rise_window_data is None:
            self.rise_window_data = []


def load_state() -> TraderState:
    """Load state from file or return default."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
            return TraderState(**data)
        except Exception as e:
            logging.warning(f"Could not load state: {e}")
    return TraderState()


def save_state(state: TraderState):
    """Save state to file."""
    STATE_FILE.parent.mkdir(exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(asdict(state), f, indent=2, default=str)


# ============================================================================
# EXCHANGE INTERFACE
# ============================================================================

class ExchangeInterface:
    """Handles all exchange communication."""

    def __init__(self, config: TraderConfig, api_key: str = None, secret: str = None):
        self.config = config

        exchange_class = getattr(ccxt, config.exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True,
        })

        if config.paper_mode:
            logging.info("Running in PAPER TRADING mode")
        else:
            logging.warning("Running in LIVE TRADING mode - REAL MONEY AT RISK!")

    def fetch_ohlcv(self, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """Fetch OHLCV data."""
        ohlcv = self.exchange.fetch_ohlcv(
            self.config.symbol,
            timeframe,
            limit=limit
        )

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df

    def get_current_price(self) -> float:
        """Get current price."""
        ticker = self.exchange.fetch_ticker(self.config.symbol)
        return ticker['last']

    def get_balance(self) -> float:
        """Get available quote balance."""
        if self.config.paper_mode:
            return self.config.paper_balance

        balance = self.exchange.fetch_balance()
        return balance[self.config.quote]['free']

    def place_market_buy(self, amount: float, state: TraderState) -> Dict:
        """Place market buy order."""
        if self.config.paper_mode:
            price = self.get_current_price()
            cost = amount * price
            state.paper_balance -= cost
            state.paper_position_size = amount
            logging.info(f"[PAPER] BUY {amount:.6f} {self.config.asset} @ ${price:.4f} (cost: ${cost:.2f})")
            return {'price': price, 'amount': amount, 'cost': cost}

        order = self.exchange.create_market_buy_order(self.config.symbol, amount)
        logging.info(f"[LIVE] BUY {amount:.6f} {self.config.asset} - Order: {order['id']}")
        return order

    def place_market_sell(self, amount: float, state: TraderState) -> Dict:
        """Place market sell order."""
        if self.config.paper_mode:
            price = self.get_current_price()
            proceeds = amount * price
            state.paper_balance += proceeds
            state.paper_position_size -= amount
            logging.info(f"[PAPER] SELL {amount:.6f} {self.config.asset} @ ${price:.4f} (proceeds: ${proceeds:.2f})")
            return {'price': price, 'amount': amount, 'proceeds': proceeds}

        order = self.exchange.create_market_sell_order(self.config.symbol, amount)
        logging.info(f"[LIVE] SELL {amount:.6f} {self.config.asset} - Order: {order['id']}")
        return order


# ============================================================================
# STRATEGY LOGIC
# ============================================================================

class V8FastStrategy:
    """V8 Fast strategy logic for live trading."""

    def __init__(self, params: Dict[str, Any]):
        self.params = params

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate ATR from OHLCV data."""
        high = df['high']
        low = df['low']
        close = df['close']

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()

        return atr.iloc[-1]

    def calculate_daily_ema(self, df: pd.DataFrame, period: int = 5) -> float:
        """Calculate EMA on daily data."""
        ema = df['close'].ewm(span=period, adjust=False).mean()
        return ema.iloc[-1]

    def check_drop_condition(self, df_4h: pd.DataFrame, state: TraderState) -> bool:
        """Check if fast drop condition is met."""
        if state.drop_detected:
            return True

        closes = df_4h['close'].tail(self.params['drop_window']).values
        if len(closes) < self.params['drop_window']:
            return False

        peak = max(closes)
        trough = min(closes)
        drop_pct = (trough - peak) / peak * 100

        if drop_pct <= -self.params['min_drop_pct']:
            logging.info(f"FAST DROP DETECTED: {-drop_pct:.1f}% over {self.params['drop_window']} 4H bars")
            return True

        return False

    def update_rise_window(self, df_4h: pd.DataFrame, state: TraderState) -> bool:
        """Update sliding window and check entry conditions."""
        current_close = df_4h['close'].iloc[-1]
        prev_close = df_4h['close'].iloc[-2]
        current_volume = df_4h['volume'].iloc[-1]

        bar_change_pct = (current_close - prev_close) / prev_close * 100

        # Check for disqualifying bars
        if bar_change_pct > self.params['max_single_up_bar']:
            logging.debug(f"Skipping explosive bar: +{bar_change_pct:.1f}%")
            return False

        if bar_change_pct < self.params['max_single_down_bar']:
            logging.debug(f"Skipping panic bar: {bar_change_pct:.1f}%")
            return False

        # Add to sliding window
        state.rise_window_data.append({
            'close': current_close,
            'volume': current_volume,
            'bar_change_pct': bar_change_pct,
        })

        # Trim window
        while len(state.rise_window_data) > self.params['rise_window']:
            state.rise_window_data.pop(0)

        # Need minimum bars
        if len(state.rise_window_data) < self.params['rise_window'] // 2:
            return False

        return self._evaluate_rise_window(df_4h, state)

    def _evaluate_rise_window(self, df_4h: pd.DataFrame, state: TraderState) -> bool:
        """Evaluate if entry conditions are met."""
        window = state.rise_window_data

        if len(window) < 2:
            return False

        # Calculate total rise
        start_price = window[0]['close']
        end_price = window[-1]['close']
        total_rise_pct = (end_price - start_price) / start_price * 100

        # Count up bars
        up_bars = sum(1 for d in window if d['bar_change_pct'] > 0)
        up_ratio = up_bars / len(window)

        # Check conditions
        conditions = {
            'up_ratio': up_ratio >= self.params['min_up_bars_ratio'],
            'total_rise': total_rise_pct >= self.params['min_rise_pct'],
        }

        if all(conditions.values()):
            logging.info(f"ENTRY CONDITIONS MET! Rise: {total_rise_pct:.1f}%, Up ratio: {up_ratio:.2%}")
            return True

        return False

    def check_exit_conditions(self, current_price: float, state: TraderState) -> tuple[bool, str]:
        """Check if exit conditions are met. Returns (should_exit, reason)."""
        if not state.in_position:
            return False, ""

        # Update high water mark
        if current_price > state.high_water_mark:
            state.high_water_mark = current_price

        # Calculate stops
        if state.entry_atr and state.entry_atr > 0:
            trailing_distance = state.entry_atr * self.params['atr_trailing_mult']
            fixed_distance = state.entry_atr * self.params['atr_fixed_mult']
            trailing_stop = state.high_water_mark - trailing_distance
            fixed_stop = state.entry_price - fixed_distance
        else:
            trailing_stop = state.high_water_mark * (1 - self.params['trailing_pct'] / 100)
            fixed_stop = state.entry_price * (1 - self.params['fixed_stop_pct'] / 100)

        effective_stop = max(trailing_stop, fixed_stop)

        if current_price <= effective_stop:
            reason = "TRAILING" if current_price <= trailing_stop else "FIXED"
            return True, reason

        return False, ""


# ============================================================================
# MAIN TRADER
# ============================================================================

class LiveTrader:
    """Main trading bot."""

    def __init__(self, config: TraderConfig, params: Dict[str, Any]):
        self.config = config
        self.strategy = V8FastStrategy(params)
        self.exchange = ExchangeInterface(config)
        self.state = load_state()

        # Restore paper balance if in paper mode
        if config.paper_mode and self.state.paper_balance == 10000.0:
            self.state.paper_balance = config.paper_balance

    def run_once(self):
        """Run one iteration of the trading loop."""
        try:
            # Fetch all timeframes
            df_15m = self.exchange.fetch_ohlcv(self.config.timeframe_15m, limit=100)
            df_4h = self.exchange.fetch_ohlcv(self.config.timeframe_4h, limit=200)
            df_daily = self.exchange.fetch_ohlcv(self.config.timeframe_daily, limit=50)

            # Use 15m close as current price (more accurate than ticker)
            current_price = df_15m['close'].iloc[-1]
            current_15m_bar = str(df_15m.index[-1])
            current_4h_bar = str(df_4h.index[-1])

            # EXIT CHECKS: Run on every 15m bar (if in position)
            if self.state.in_position:
                should_exit, reason = self.strategy.check_exit_conditions(current_price, self.state)

                if should_exit:
                    self._execute_exit(current_price, reason)
                    return

            # ENTRY LOGIC: Only run on new 4H bars
            if current_4h_bar == self.state.last_4h_bar_time:
                # Same 4H bar - skip entry logic but still save state
                save_state(self.state)
                return

            self.state.last_4h_bar_time = current_4h_bar
            logging.debug(f"New 4H bar: {current_4h_bar}")

            # Entry logic (if not in position)
            if not self.state.in_position:
                # Check for drop on 4H timeframe
                if not self.state.drop_detected:
                    self.state.drop_detected = self.strategy.check_drop_condition(df_4h, self.state)

                # Check for entry using sliding window on 4H
                if self.state.drop_detected:
                    if self.strategy.update_rise_window(df_4h, self.state):
                        # Check daily EMA filter
                        daily_ema = self.strategy.calculate_daily_ema(
                            df_daily,
                            self.strategy.params['daily_ema_period']
                        )

                        if current_price > daily_ema:
                            # Entry uses 15m close price for precision
                            self._execute_entry(current_price, df_4h)
                        else:
                            logging.debug(f"Entry blocked - price {current_price:.4f} below daily EMA {daily_ema:.4f}")

            # Save state
            save_state(self.state)

        except Exception as e:
            logging.error(f"Error in trading loop: {e}")
            raise

    def _execute_entry(self, price: float, df_4h: pd.DataFrame):
        """Execute entry order."""
        balance = self.exchange.get_balance() if not self.config.paper_mode else self.state.paper_balance
        position_value = balance * self.config.position_size_pct
        amount = position_value / price

        # Calculate ATR at entry
        atr = self.strategy.calculate_atr(df_4h, self.strategy.params['atr_period'])

        # Execute order
        order = self.exchange.place_market_buy(amount, self.state)

        # Update state
        self.state.in_position = True
        self.state.entry_price = price
        self.state.entry_time = datetime.now().isoformat()
        self.state.position_size = amount
        self.state.entry_atr = atr
        self.state.high_water_mark = price
        self.state.partial_taken = False
        self.state.drop_detected = False
        self.state.rise_window_data = []

        logging.info(f"ENTRY @ ${price:.4f} | Size: {amount:.6f} | ATR: {atr:.4f}")
        save_state(self.state)

    def _execute_exit(self, price: float, reason: str):
        """Execute exit order."""
        amount = self.state.position_size if not self.config.paper_mode else self.state.paper_position_size

        # Execute order
        order = self.exchange.place_market_sell(amount, self.state)

        # Calculate P&L
        pnl_pct = (price - self.state.entry_price) / self.state.entry_price * 100
        pnl_value = (price - self.state.entry_price) * amount

        # Update stats
        self.state.total_trades += 1
        self.state.total_pnl += pnl_value
        if pnl_pct > 0:
            self.state.winning_trades += 1
        else:
            self.state.losing_trades += 1

        logging.info(f"EXIT ({reason}) @ ${price:.4f} | PnL: {pnl_pct:+.2f}% (${pnl_value:+.2f})")

        # Reset position state
        self.state.in_position = False
        self.state.entry_price = None
        self.state.entry_time = None
        self.state.position_size = 0.0
        self.state.entry_atr = None
        self.state.high_water_mark = None
        self.state.partial_taken = False

        save_state(self.state)

    def run(self):
        """Main trading loop."""
        logging.info(f"Starting trader for {self.config.symbol}")
        logging.info(f"Mode: {'PAPER' if self.config.paper_mode else 'LIVE'}")
        logging.info(f"Poll interval: {self.config.poll_interval}s")

        while True:
            try:
                self.run_once()
                self._print_status()
                time.sleep(self.config.poll_interval)

            except KeyboardInterrupt:
                logging.info("Shutting down...")
                save_state(self.state)
                break
            except Exception as e:
                logging.error(f"Error: {e}")
                time.sleep(60)  # Wait before retry

    def _print_status(self):
        """Print current status."""
        balance = self.state.paper_balance if self.config.paper_mode else self.exchange.get_balance()
        price = self.exchange.get_current_price()

        status = f"[{datetime.now().strftime('%H:%M:%S')}] "
        status += f"{self.config.symbol}: ${price:.4f} | "
        status += f"Balance: ${balance:.2f} | "
        status += f"Position: {'YES' if self.state.in_position else 'NO'}"

        if self.state.in_position:
            pnl_pct = (price - self.state.entry_price) / self.state.entry_price * 100
            status += f" | Entry: ${self.state.entry_price:.4f} | PnL: {pnl_pct:+.2f}%"

        status += f" | Trades: {self.state.total_trades} (W:{self.state.winning_trades}/L:{self.state.losing_trades})"

        print(status, end='\r')


# ============================================================================
# MAIN
# ============================================================================

def setup_logging(verbose: bool = False):
    """Configure logging."""
    LOG_FILE.parent.mkdir(exist_ok=True)

    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout)
        ]
    )


def main():
    parser = argparse.ArgumentParser(
        description="Live/Paper Trading Bot for V8 Fast Strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python live_trader.py --paper                  # Paper trade SOL (default)
  python live_trader.py --paper --asset VET      # Paper trade VET
  python live_trader.py --live --asset SOL       # LIVE trade SOL (real money!)
  python live_trader.py --status                 # Show current state
  python live_trader.py --reset                  # Reset state file
        """
    )

    parser.add_argument('--paper', action='store_true', default=True,
                        help="Paper trading mode (default)")
    parser.add_argument('--live', action='store_true',
                        help="Live trading mode (REAL MONEY!)")
    parser.add_argument('--asset', '-a', default='SOL',
                        help="Asset to trade (default: SOL)")
    parser.add_argument('--balance', '-b', type=float, default=10000.0,
                        help="Starting paper balance (default: 10000)")
    parser.add_argument('--interval', '-i', type=int, default=60,
                        help="Poll interval in seconds (default: 60)")
    parser.add_argument('--status', action='store_true',
                        help="Show current state and exit")
    parser.add_argument('--reset', action='store_true',
                        help="Reset state file")
    parser.add_argument('--verbose', '-v', action='store_true',
                        help="Verbose logging")

    args = parser.parse_args()

    setup_logging(args.verbose)

    # Handle reset
    if args.reset:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
            print("State file reset.")
        else:
            print("No state file to reset.")
        return 0

    # Handle status
    if args.status:
        state = load_state()
        print("\n=== Trader State ===")
        print(f"In Position: {state.in_position}")
        if state.in_position:
            print(f"  Entry Price: ${state.entry_price:.4f}")
            print(f"  Entry Time: {state.entry_time}")
            print(f"  Position Size: {state.position_size:.6f}")
            print(f"  HWM: ${state.high_water_mark:.4f}")
        print(f"Drop Detected: {state.drop_detected}")
        print(f"Rise Window Size: {len(state.rise_window_data)}")
        print(f"\n=== Stats ===")
        print(f"Paper Balance: ${state.paper_balance:.2f}")
        print(f"Total Trades: {state.total_trades}")
        print(f"Winning: {state.winning_trades}")
        print(f"Losing: {state.losing_trades}")
        print(f"Total PnL: ${state.total_pnl:.2f}")
        return 0

    # Create config
    config = TraderConfig(
        asset=args.asset.upper(),
        paper_mode=not args.live,
        paper_balance=args.balance,
        poll_interval=args.interval,
    )

    # Safety check for live trading
    if args.live:
        print("\n" + "="*60)
        print("WARNING: LIVE TRADING MODE")
        print("This will use REAL MONEY on Binance US!")
        print("="*60)
        confirm = input("Type 'YES' to confirm: ")
        if confirm != 'YES':
            print("Aborted.")
            return 1

    # Create and run trader
    trader = LiveTrader(config, V8_FAST_SOL_PARAMS)
    trader.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
