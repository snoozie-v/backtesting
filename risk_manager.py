# risk_manager.py
"""
R-Based Risk Management Module
-------------------------------
Shared module for position sizing and R-based partial profit exits.

Trading model:
- Risk a fixed % of account (default 3%) at the stop loss
- Position size = risk_amount / stop_distance
- Take profits at R-multiples: 30% at 1R, 30% at 2R, 30% at 3R
- Trail remaining 10% (runner) with ATR-based stop
- Ratchet stop up at each R-level hit

Where 1R = the distance from entry to initial stop loss.
"""


class RiskManager:
    """R-based position sizing and exit management."""

    # Default partial schedule: (R-multiple, fraction of ORIGINAL position to sell)
    DEFAULT_SCHEDULE = [(1.0, 0.30), (2.0, 0.30), (3.0, 0.30)]
    # Remaining 10% is the runner

    def __init__(self, risk_pct=3.0, partial_schedule=None):
        self.risk_pct = risk_pct / 100.0  # Convert to decimal
        self.partial_schedule = partial_schedule or self.DEFAULT_SCHEDULE

    def calculate_position_size(self, equity, stop_distance):
        """
        Size position so that hitting the stop loss = risk_pct of equity.

        Args:
            equity: Current account value
            stop_distance: Price distance from entry to stop (absolute, positive)

        Returns:
            Position size in units (can exceed cash with leverage)
        """
        if stop_distance <= 0:
            return 0
        risk_amount = equity * self.risk_pct
        return risk_amount / stop_distance

    def calculate_r_targets(self, entry_price, stop_distance, direction='long'):
        """
        Calculate R-multiple price targets.

        Args:
            entry_price: Entry price
            stop_distance: Absolute distance to stop (positive)
            direction: 'long' or 'short'

        Returns:
            dict with R-levels as keys and prices as values
            e.g. {-1: stop_price, 1: target_1R, 2: target_2R, 3: target_3R}
        """
        targets = {}
        if direction == 'long':
            targets[-1] = entry_price - stop_distance  # Stop loss
            for r_mult, _ in self.partial_schedule:
                targets[r_mult] = entry_price + (stop_distance * r_mult)
        else:  # short
            targets[-1] = entry_price + stop_distance  # Stop loss
            for r_mult, _ in self.partial_schedule:
                targets[r_mult] = entry_price - (stop_distance * r_mult)
        return targets

    def get_stop_for_level(self, entry_price, stop_distance, partials_taken, direction='long'):
        """
        Get the current stop price based on how many partials have been taken.

        Stop ratcheting:
        - Before 1R: initial stop (-1R)
        - After 1R taken: breakeven (entry)
        - After 2R taken: +1R
        - After 3R taken: +2R

        Args:
            entry_price: Entry price
            stop_distance: Absolute distance to stop (positive)
            partials_taken: Number of partial exits completed (0, 1, 2, 3)
            direction: 'long' or 'short'

        Returns:
            Current stop price
        """
        if direction == 'long':
            if partials_taken >= 3:
                return entry_price + (stop_distance * 2)  # +2R
            elif partials_taken >= 2:
                return entry_price + stop_distance          # +1R
            elif partials_taken >= 1:
                return entry_price                          # Breakeven
            else:
                return entry_price - stop_distance          # -1R
        else:  # short
            if partials_taken >= 3:
                return entry_price - (stop_distance * 2)  # +2R
            elif partials_taken >= 2:
                return entry_price - stop_distance          # +1R
            elif partials_taken >= 1:
                return entry_price                          # Breakeven
            else:
                return entry_price + stop_distance          # -1R

    def calculate_r_multiple(self, entry_price, exit_price, stop_distance, direction='long'):
        """
        Calculate the R-multiple of a completed trade.

        Args:
            entry_price: Entry price
            exit_price: Exit price
            stop_distance: Original stop distance (defines 1R)
            direction: 'long' or 'short'

        Returns:
            R-multiple (e.g., -1.0 for full stop, +2.5 for 2.5R winner)
        """
        if stop_distance <= 0:
            return 0.0
        if direction == 'long':
            return (exit_price - entry_price) / stop_distance
        else:
            return (entry_price - exit_price) / stop_distance
