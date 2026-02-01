# core/risk_manager.py

# Depricated
class RiskManager:
    """
    Simple risk manager for live trading.
    Checks if a new position can be taken based on portfolio and risk rules.
    """

    def __init__(self, portfolio, max_positions=5, max_capital_per_trade=50000):
        """
        Args:
            portfolio: Portfolio object tracking current positions
            max_positions: Maximum concurrent positions allowed
            max_capital_per_trade: Maximum capital to allocate per trade
        """
        self.portfolio = portfolio
        self.max_positions = max_positions
        self.max_capital_per_trade = max_capital_per_trade

    def allow_trade(self, position):
        """
        Decide if a new trade is allowed.

        Args:
            position: Position object with 'symbol', 'side', 'quantity', 'price', etc.

        Returns:
            bool: True if trade can be placed, False otherwise
        """
        # 1️⃣ Check max open positions
        if len(self.portfolio.positions) >= self.max_positions:
            print(
                f"RiskManager: Max positions reached ({self.max_positions}). Trade denied."
            )
            return False

        # 2️⃣ Check capital allocation per trade
        required_capital = position.quantity * position.price
        if required_capital > self.max_capital_per_trade:
            print(
                f"RiskManager: Trade requires {required_capital}, "
                f"exceeds max allowed {self.max_capital_per_trade}. Trade denied."
            )
            return False

        # 3️⃣ Optionally, add symbol-specific or other custom rules here
        # e.g., avoid trading if already holding the same symbol
        if position.symbol in self.portfolio.positions:
            print(f"RiskManager: Already holding {position.symbol}. Trade denied.")
            return False

        return True
