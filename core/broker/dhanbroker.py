from core.data.sources.dhan_source import DhanSource
from core.portfolio import Portfolio


class DhanBroker:
    def __init__(self, dhan_source, portfolio):
        self.source = dhan_source
        self.portfolio = portfolio

    def place_order(self, position):
        """
        Convert Position → Dhan order
        """

        tradingsymbol = position.symbol
        exchange = "NFO" if position.option_type else "NSE"

        quantity = position.qty
        transaction_type = position.side  # BUY / SELL

        # ---- Pricing ----
        price = 0
        trigger_price = 0
        order_type = "MARKET"  # live default

        trade_type = "MARGIN"  # or MIS / CNC

        order_id = self.source.place_order(
            tradingsymbol=tradingsymbol,
            exchange=exchange,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            order_type=order_type,
            transaction_type=transaction_type,
            trade_type=trade_type,
            tag="LIVE_STRATEGY",
        )

        if order_id:
            self.portfolio.enter(position)

        return order_id

    def get_positions(self, symbol: str | None = None):
        """
        Returns list[Position] for LIVE trades
        """
        df = self.source.get_positions()

        if df is None or df.empty:
            return []

        positions = []

        for _, row in df.iterrows():
            tradingsymbol = row["tradingSymbol"]

            if symbol and tradingsymbol != symbol:
                continue

            side = "BUY" if row["buySell"] == "BUY" else "SELL"
            qty = abs(int(row["netQty"]))
            entry_price = float(row["avgPrice"])

            if qty == 0:
                continue  # closed position

            pos = Position(
                symbol=tradingsymbol,
                side=side,
                entry_price=entry_price,
                qty=qty,
                exchange=row["exchange"],
                order_id=row.get("orderId"),
            )

            positions.append(pos)

        return positions

    def exit_position(self, position, exit_signal):
        """
        Exit a live position using MARKET or SL
        """

        tradingsymbol = position.symbol
        exchange = position.exchange
        quantity = position.qty

        # ---- Reverse side ----
        transaction_type = "SELL" if position.side == "BUY" else "BUY"

        # ---- Defaults ----
        order_type = "MARKET"
        price = 0
        trigger_price = 0

        # ---- SL Exit ----
        if exit_signal["type"] == "SL":
            order_type = "STOPMARKET"  # SLM
            trigger_price = exit_signal["price"]

        order_id = self.source.place_order(
            tradingsymbol=tradingsymbol,
            exchange=exchange,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            order_type=order_type,
            transaction_type=transaction_type,
            trade_type="MARGIN",  # or MIS / CNC
            tag="EXIT",
        )

        if order_id:
            print(
                f"EXIT ORDER PLACED | {tradingsymbol} | "
                f"{order_type} | Qty {quantity}"
            )
            self.portfolio.exit_live(tradingsymbol)

        return order_id
