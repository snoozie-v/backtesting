#!/usr/bin/env python3
# test_trader.py
"""
Test Trading Bot - Guaranteed to trigger trades for testing purposes.

This is NOT a real strategy - it's just for testing that the paper trading
infrastructure works correctly.

Strategy:
- Buys immediately if not in position
- Sells after 0.5% profit OR 0.3% loss OR 5 minutes (whichever comes first)
- Repeats

Usage:
    python test_trader.py                    # Run test trades
    python test_trader.py --asset VET        # Test with VET
    python test_trader.py --duration 15      # Run for 15 minutes then stop
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

import ccxt
import pandas as pd

# ============================================================================
# CONFIGURATION
# ============================================================================

STATE_FILE = Path("data/test_trader_state.json")
LOG_FILE = Path("data/test_trader.log")

@dataclass
class TestConfig:
    """Configuration for test trader."""
    exchange_id: str = "binanceus"
    asset: str = "SOL"
    quote: str = "USD"

    # Position sizing
    position_size_pct: float = 0.98

    # Paper trading
    paper_balance: float = 10000.0

    # Exit conditions (very tight for testing)
    take_profit_pct: float = 0.5   # Exit at 0.5% profit
    stop_loss_pct: float = 0.3     # Exit at 0.3% loss
    max_hold_minutes: int = 5      # Exit after 5 minutes regardless

    # Polling
    poll_interval: int = 10  # Check every 10 seconds

    @property
    def symbol(self) -> str:
        return f"{self.asset}/{self.quote}"


@dataclass
class TestState:
    """State for test trader."""
    in_position: bool = False
    entry_price: Optional[float] = None
    entry_time: Optional[str] = None
    position_size: float = 0.0

    paper_balance: float = 10000.0
    paper_position_size: float = 0.0

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0


def load_state() -> TestState:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                return TestState(**json.load(f))
        except:
            pass
    return TestState()


def save_state(state: TestState):
    STATE_FILE.parent.mkdir(exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(asdict(state), f, indent=2)


# ============================================================================
# TEST TRADER
# ============================================================================

class TestTrader:
    """Simple test trader that guarantees trades."""

    def __init__(self, config: TestConfig):
        self.config = config
        self.state = load_state()
        self.state.paper_balance = config.paper_balance

        # Initialize exchange
        self.exchange = ccxt.binanceus({'enableRateLimit': True})

        logging.info(f"Test Trader initialized for {config.symbol}")
        logging.info(f"Take profit: {config.take_profit_pct}%")
        logging.info(f"Stop loss: {config.stop_loss_pct}%")
        logging.info(f"Max hold: {config.max_hold_minutes} minutes")

    def get_price(self) -> float:
        ticker = self.exchange.fetch_ticker(self.config.symbol)
        return ticker['last']

    def buy(self, price: float):
        """Execute paper buy."""
        amount = (self.state.paper_balance * self.config.position_size_pct) / price
        cost = amount * price

        self.state.paper_balance -= cost
        self.state.paper_position_size = amount
        self.state.in_position = True
        self.state.entry_price = price
        self.state.entry_time = datetime.now().isoformat()
        self.state.position_size = amount

        logging.info(f"BUY {amount:.6f} {self.config.asset} @ ${price:.4f} (cost: ${cost:.2f})")
        save_state(self.state)

    def sell(self, price: float, reason: str):
        """Execute paper sell."""
        amount = self.state.paper_position_size
        proceeds = amount * price

        pnl_pct = (price - self.state.entry_price) / self.state.entry_price * 100
        pnl_value = proceeds - (amount * self.state.entry_price)

        self.state.paper_balance += proceeds
        self.state.paper_position_size = 0.0
        self.state.in_position = False
        self.state.total_trades += 1
        self.state.total_pnl += pnl_value

        if pnl_pct > 0:
            self.state.winning_trades += 1
        else:
            self.state.losing_trades += 1

        logging.info(f"SELL {amount:.6f} {self.config.asset} @ ${price:.4f} ({reason})")
        logging.info(f"PnL: {pnl_pct:+.2f}% (${pnl_value:+.2f})")
        logging.info(f"New balance: ${self.state.paper_balance:.2f}")

        self.state.entry_price = None
        self.state.entry_time = None
        self.state.position_size = 0.0

        save_state(self.state)

    def check_exit(self, price: float) -> tuple[bool, str]:
        """Check if should exit position."""
        if not self.state.in_position:
            return False, ""

        # Check profit target
        pnl_pct = (price - self.state.entry_price) / self.state.entry_price * 100

        if pnl_pct >= self.config.take_profit_pct:
            return True, f"TAKE PROFIT ({pnl_pct:+.2f}%)"

        if pnl_pct <= -self.config.stop_loss_pct:
            return True, f"STOP LOSS ({pnl_pct:+.2f}%)"

        # Check time limit
        entry_time = datetime.fromisoformat(self.state.entry_time)
        hold_duration = datetime.now() - entry_time

        if hold_duration >= timedelta(minutes=self.config.max_hold_minutes):
            return True, f"TIME LIMIT ({hold_duration.seconds // 60}m)"

        return False, ""

    def run_once(self):
        """Run one iteration."""
        price = self.get_price()

        if self.state.in_position:
            # Check for exit
            should_exit, reason = self.check_exit(price)
            if should_exit:
                self.sell(price, reason)
        else:
            # Buy immediately
            logging.info(f"No position - buying at ${price:.4f}")
            self.buy(price)

        self.print_status(price)

    def print_status(self, price: float):
        """Print current status."""
        status = f"[{datetime.now().strftime('%H:%M:%S')}] "
        status += f"{self.config.symbol}: ${price:.4f} | "
        status += f"Balance: ${self.state.paper_balance:.2f} | "

        if self.state.in_position:
            pnl_pct = (price - self.state.entry_price) / self.state.entry_price * 100
            entry_time = datetime.fromisoformat(self.state.entry_time)
            hold_mins = (datetime.now() - entry_time).seconds // 60
            status += f"IN POSITION | Entry: ${self.state.entry_price:.4f} | PnL: {pnl_pct:+.2f}% | Hold: {hold_mins}m"
        else:
            status += "NO POSITION"

        status += f" | Trades: {self.state.total_trades} (W:{self.state.winning_trades}/L:{self.state.losing_trades})"
        status += f" | Total PnL: ${self.state.total_pnl:+.2f}"

        print(status)

    def run(self, duration_minutes: int = None):
        """Main loop."""
        start_time = datetime.now()

        logging.info("=" * 60)
        logging.info("TEST TRADER STARTED")
        logging.info(f"This will make trades every ~{self.config.max_hold_minutes} minutes")
        logging.info("=" * 60)

        while True:
            try:
                self.run_once()

                # Check duration limit
                if duration_minutes:
                    elapsed = (datetime.now() - start_time).seconds / 60
                    if elapsed >= duration_minutes:
                        logging.info(f"Duration limit reached ({duration_minutes} minutes)")
                        break

                time.sleep(self.config.poll_interval)

            except KeyboardInterrupt:
                logging.info("Shutting down...")
                save_state(self.state)
                break
            except Exception as e:
                logging.error(f"Error: {e}")
                time.sleep(30)

        # Final summary
        self.print_summary()

    def print_summary(self):
        """Print final summary."""
        print("\n" + "=" * 60)
        print("TEST TRADER SUMMARY")
        print("=" * 60)
        print(f"Final Balance: ${self.state.paper_balance:.2f}")
        print(f"Total Trades: {self.state.total_trades}")
        print(f"Winning: {self.state.winning_trades}")
        print(f"Losing: {self.state.losing_trades}")
        if self.state.total_trades > 0:
            win_rate = self.state.winning_trades / self.state.total_trades * 100
            print(f"Win Rate: {win_rate:.1f}%")
        print(f"Total PnL: ${self.state.total_pnl:+.2f}")
        print("=" * 60)


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Test Trading Bot")
    parser.add_argument('--asset', '-a', default='SOL', help="Asset to trade")
    parser.add_argument('--duration', '-d', type=int, default=None,
                        help="Duration in minutes (default: run forever)")
    parser.add_argument('--balance', '-b', type=float, default=10000.0,
                        help="Starting balance")
    parser.add_argument('--reset', action='store_true', help="Reset state")

    args = parser.parse_args()

    # Setup logging
    LOG_FILE.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout)
        ]
    )

    if args.reset:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        print("State reset.")
        return 0

    config = TestConfig(
        asset=args.asset.upper(),
        paper_balance=args.balance,
    )

    trader = TestTrader(config)
    trader.run(duration_minutes=args.duration)

    return 0


if __name__ == "__main__":
    sys.exit(main())
