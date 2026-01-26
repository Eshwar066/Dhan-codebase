# core/portfolio.py
class Position:
    def __init__(self, symbol, side, entry_price, qty, entry_time, sl):
        self.symbol = symbol
        self.side = side
        self.entry_price = entry_price
        self.qty = qty
        self.entry_time = entry_time
        self.sl = sl


class Portfolio:
    def __init__(self, capital):
        self.capital = capital
        self.positions = {}

    def get_position_size(self, price, risk_pct=0.01):
        risk_amount = self.capital * risk_pct
        return int(risk_amount / price)

    def has_position(self, symbol):
        return symbol in self.positions

    def get_position(self, symbol):
        return self.positions.get(symbol)

    def enter(self, position):
        self.positions[position.symbol] = position
        print(f"ENTRY {position.side} {position.symbol} @ {position.entry_price}")

    def exit(self, symbol, candle):
        pos = self.positions[symbol]
        exit_price = candle["close"]

        pnl = (
            (exit_price - pos.entry_price) * pos.qty
            if pos.side == "BUY"
            else (pos.entry_price - exit_price) * pos.qty
        )

        self.capital += pnl
        print(f"EXIT {pos.side} {symbol} | PnL: {pnl:.2f}")
        del self.positions[symbol]

    def report(self):
        print("\nFinal Capital:", self.capital)
