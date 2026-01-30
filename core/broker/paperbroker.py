from core.portfolio import PositionManager


class PaperBroker:
    def __init__(self, portfolio):
        self.portfolio = portfolio

    def place_order(self, intent):
        # Log order creation
        print(
            f"[PAPER] ORDER CREATED: {intent.symbol} {intent.side} {intent.qty} @ {intent.price}"
        )
        intent.status = "ACKNOWLEDGED"

        # Simulate slippage
        fill_price = self.simulate_slippage(intent)
        # Update positions
        PositionManager.update(intent, fill_price)
        intent.status = "FILLED"

        # Log fill
        print(
            f"[PAPER] ORDER FILLED: {intent.symbol} {intent.side} {intent.qty} @ {fill_price}"
        )

    def simulate_slippage(self, intent):
        # Optional: add realistic slippage
        return intent.price * (1 + 0.0005)  # 5bps slippage
