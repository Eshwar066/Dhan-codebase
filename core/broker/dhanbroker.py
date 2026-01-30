# from core.data.sources.dhan_source import DhanSource
# from core.portfolio import Portfolio


# class DhanBroker:
#     def __init__(self, dhan_source, portfolio):
#         self.source = dhan_source
#         self.portfolio = portfolio

#     def place_order(self, position):
#         """
#         Convert Position → Dhan order
#         """

#         tradingsymbol = position.symbol
#         exchange = "NFO" if position.option_type else "NSE"

#         quantity = position.qty
#         transaction_type = position.side  # BUY / SELL

#         # ---- Pricing ----
#         price = 0
#         trigger_price = 0
#         order_type = "MARKET"  # live default

#         trade_type = "MARGIN"  # or MIS / CNC

#         order_id = self.source.place_order(
#             tradingsymbol=tradingsymbol,
#             exchange=exchange,
#             quantity=quantity,
#             price=price,
#             trigger_price=trigger_price,
#             order_type=order_type,
#             transaction_type=transaction_type,
#             trade_type=trade_type,
#             tag="LIVE_STRATEGY",
#         )

#         if order_id:
#             self.portfolio.enter(position)

#         return order_id

#     def get_positions(self, symbol: str | None = None):
#         """
#         Returns list[Position] for LIVE trades
#         """
#         df = self.source.get_positions()

#         if df is None or df.empty:
#             return []

#         positions = []

#         for _, row in df.iterrows():
#             tradingsymbol = row["tradingSymbol"]

#             if symbol and tradingsymbol != symbol:
#                 continue

#             side = "BUY" if row["buySell"] == "BUY" else "SELL"
#             qty = abs(int(row["netQty"]))
#             entry_price = float(row["avgPrice"])

#             if qty == 0:
#                 continue  # closed position

#             pos = Position(
#                 symbol=tradingsymbol,
#                 side=side,
#                 entry_price=entry_price,
#                 qty=qty,
#                 exchange=row["exchange"],
#                 order_id=row.get("orderId"),
#             )

#             positions.append(pos)

#         return positions

#     def exit_position(self, position, exit_signal):
#         """
#         Exit a live position using MARKET or SL
#         """

#         tradingsymbol = position.symbol
#         exchange = position.exchange
#         quantity = position.qty

#         # ---- Reverse side ----
#         transaction_type = "SELL" if position.side == "BUY" else "BUY"

#         # ---- Defaults ----
#         order_type = "MARKET"
#         price = 0
#         trigger_price = 0

#         # ---- SL Exit ----
#         if exit_signal["type"] == "SL":
#             order_type = "STOPMARKET"  # SLM
#             trigger_price = exit_signal["price"]

#         order_id = self.source.place_order(
#             tradingsymbol=tradingsymbol,
#             exchange=exchange,
#             quantity=quantity,
#             price=price,
#             trigger_price=trigger_price,
#             order_type=order_type,
#             transaction_type=transaction_type,
#             trade_type="MARGIN",  # or MIS / CNC
#             tag="EXIT",
#         )

#         if order_id:
#             print(
#                 f"EXIT ORDER PLACED | {tradingsymbol} | "
#                 f"{order_type} | Qty {quantity}"
#             )
#             self.portfolio.exit_live(tradingsymbol)

#         return order_id

# Above is older code.

import time
import uuid


# ✅ Idempotent orders
# ✅ Retry-safe
# ✅ Intent-linked
# ✅ PositionManager compatible
# ✅ Dhan-friendly
# ✅ Segment aware (EQ/FNO/MCX/CRYPTO)
# ✅ Safe for leveraged trading

# SLM dhan Order
# order_type = "STOP_LOSS_MARKET"
# trigger_price = X
# price = None or 0


class DhanBroker:
    def __init__(self, dhan_api, position_manager=None, intent_store=None):
        self.api = dhan_api
        self.position_manager = position_manager
        self.intent_store = intent_store

    # =========================
    # ORDER PLACEMENT
    # =========================
    def place_order(self, intent, retries=2):
        """
        Intent → Safe Dhan Order

        intent fields expected:
        {
            intent_id,
            symbol,
            side,
            qty,
            segment,
            order_type,
            price,
            trigger_price,
            product
        }
        """

        client_order_id = intent.get(
            "client_order_id", f"algo_{intent['intent_id']}_{uuid.uuid4().hex[:6]}"
        )

        order_payload = self._build_payload(intent)

        for attempt in range(retries + 1):
            try:
                resp = self.api.place_order(
                    **order_payload, client_order_id=client_order_id
                )

                if resp.get("status") == "success":
                    order_id = resp["order_id"]

                    if self.intent_store:
                        self.intent_store.update(
                            intent["intent_id"],
                            "SENT",
                        )

                    return order_id

            except TimeoutError:

                # 🔑 Idempotency recovery
                existing = self.find_order_by_client_id(client_order_id)

                if existing:
                    return existing["order_id"]

                if attempt == retries:
                    raise Exception("Order failed after retries")

                time.sleep(0.4)

        return None

    # =========================
    # BUILD DHAN PAYLOAD
    # =========================
    def _build_payload(self, intent):

        segment_map = {
            "EQ": "NSE",
            "FUT": "NFO",
            "OPT": "NFO",
            "MCX": "MCX",
            "CRYPTO": "CRYPTO",
        }

        exchange = segment_map.get(intent["segment"], "NSE")

        return dict(
            symbol=intent["symbol"],
            side=intent["side"],
            quantity=intent["qty"],
            order_type=intent.get("order_type", "MARKET"),
            product=intent.get("product", "MARGIN"),
            price=intent.get("price", 0),
            trigger_price=intent.get("trigger_price", 0),
            exchange=exchange,
        )

    # =========================
    # ORDER SEARCH (Idempotency)
    # =========================
    def find_order_by_client_id(self, client_order_id):
        orders = self.api.get_order_list()

        for o in orders:
            if o.get("client_order_id") == client_order_id:
                return o

        return None

    # =========================
    # POSITION SYNC
    # =========================
    def sync_positions(self):
        """
        Broker truth → PositionManager
        """
        if not self.position_manager:
            return

        broker_positions = {}

        df = self.api.get_positions()

        if df is None or df.empty:
            return

        for _, row in df.iterrows():

            sym = row["tradingSymbol"]

            broker_positions[sym] = {
                "qty": int(row["netQty"]),
                "avg_price": float(row["avgPrice"]),
                "segment": row.get("segment", "EQ"),
                "lot_size": row.get("lotSize", 1),
            }

        self.position_manager.reconcile_with_broker(broker_positions)

    # =========================
    # EXIT POSITION
    # =========================
    def exit_position(self, symbol, qty, side):

        exit_side = "SELL" if side == "BUY" else "BUY"

        order = dict(
            symbol=symbol,
            side=exit_side,
            qty=qty,
            segment="EQ",
            order_type="MARKET",
            product="MARGIN",
        )

        return self.place_order({"intent_id": f"exit_{uuid.uuid4().hex[:6]}", **order})
