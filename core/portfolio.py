# core/portfolio.py


# Depricated
class Position:
    def __init__(
        self,
        symbol,
        side,  # "BUY" or "SELL"
        entry_price,
        qty,
        entry_time,
        sl=None,
        option_type=None,
    ):
        self.symbol = symbol
        self.side = side
        self.entry_price = entry_price
        self.qty = qty
        self.entry_time = entry_time
        self.sl = sl
        self.option_type = option_type


class Portfolio:
    def __init__(self, capital):
        self.initial_capital = capital
        self.capital = capital
        self.positions = {}

    # ---------- POSITION SIZING ----------
    def get_position_size(self, price, risk_pct=0.01):
        risk_amount = self.capital * risk_pct
        qty = int(risk_amount / price)
        return max(qty, 1)

    # ---------- POSITION STATE ----------
    def has_position(self, symbol):
        return symbol in self.positions

    def get_position(self, symbol):
        return self.positions.get(symbol)

    # ---------- ENTRY ----------
    def enter(self, position):
        self.positions[position.symbol] = position
        print(
            f"ENTRY | {position.side} {position.symbol} "
            f"@ {position.entry_price} | Qty: {position.qty}"
        )

    # ---------- EXIT ----------
    def exit(self, symbol, candle):
        pos = self.positions[symbol]
        exit_price = candle["close"]

        if pos.side == "BUY":
            pnl = (exit_price - pos.entry_price) * pos.qty
        else:  # SELL
            pnl = (pos.entry_price - exit_price) * pos.qty

        self.capital += pnl

        print(f"EXIT | {pos.side} {symbol} " f"@ {exit_price} | PnL: {pnl:.2f}")

        del self.positions[symbol]

    # ---------- LIVE EXIT ----------
    def exit_live(self, symbol):
        """
        Used only in LIVE mode.
        Capital & PnL come from broker reports, not candles.
        """
        if symbol in self.positions:
            del self.positions[symbol]
            print(f"EXIT (LIVE CONFIRMED) | {symbol}")

    # ---------- REPORT ----------
    def report(self):
        print("\n===== PORTFOLIO REPORT =====")
        print(f"Initial Capital: {self.initial_capital}")
        print(f"Final Capital  : {self.capital}")
        print(f"Net PnL        : {self.capital - self.initial_capital}")
