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
import pdb


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
    # BUILD DHAN PAYLOAD
    # =========================
    def _build_payload(self, intent):
        """
        Convert intent into broker payload for Dhan API.
        """

        # Map segment to exchange for Dhan API
        segment_map = {
            "EQ": "NSE",
            "FUT": "NSE",
            "OPT": "NSE",
            "MCX": "MCX",
            "CRYPTO": "CRYPTO",
            "D": "NSE",
            "NSE": "NSE",
            "NFO": "NSE",
        }
        segment = intent.get("segment", "EQ")
        exchange = segment_map.get(segment, "NSE")

        required = ["trading_symbol", "side", "qty"]
        for r in required:
            if r not in intent or intent[r] is None:
                raise ValueError(f"❌ Missing required intent field: {r}")

        qty = int(intent["qty"])
        lot_size = int(intent.get("lot_size", 1))
        total_qty = qty * lot_size

        payload = {
            "tradingsymbol": intent["trading_symbol"],
            "exchange": exchange,
            "quantity": total_qty,
            "price": float(intent.get("price", 0) or 0),
            "trigger_price": float(intent.get("trigger_price", 0) or 0),
            "order_type": intent.get("order_type", "MARKET"),
            "transaction_type": intent["side"],  # BUY / SELL
            "trade_type": intent.get("trade_type", "MARGIN"),
            "disclosed_quantity": int(intent.get("disclosed_quantity", 0)),
            "after_market_order": bool(intent.get("after_market_order", False)),
            "validity": intent.get("validity", "DAY"),
            "amo_time": intent.get("amo_time", "OPEN"),
            "bo_profit_value": intent.get("bo_profit_value", 0),
            "bo_stop_loss_value": intent.get("bo_stop_loss_value", 0),
            "tag": intent.get("intent_id"),  # idempotency
        }

        return payload

    # =========================
    # ORDER PLACEMENT
    # =========================
    def place_order(self, intent, retries=2):
        """
        Intent → Safe Dhan Order
        """
        order_payload = self._build_payload(intent)
        # pdb.set_trace()
        for attempt in range(retries + 1):
            try:
                resp = self.api.place_order(
                    tradingsymbol=order_payload["tradingsymbol"],
                    exchange=order_payload["exchange"],
                    quantity=order_payload["quantity"],
                    price=order_payload["price"],
                    trigger_price=order_payload["trigger_price"],
                    order_type=order_payload["order_type"],
                    transaction_type=order_payload["transaction_type"],
                    trade_type=order_payload["trade_type"],
                    disclosed_quantity=order_payload["disclosed_quantity"],
                    after_market_order=order_payload["after_market_order"],
                    validity=order_payload["validity"],
                    amo_time=order_payload["amo_time"],
                    bo_profit_value=order_payload["bo_profit_value"],
                    bo_stop_loss_value=order_payload["bo_stop_loss_value"],
                    tag=order_payload["tag"],
                )

                if not isinstance(resp, dict):
                    raise Exception(f"Invalid broker response: {resp},{order_payload}")

                if resp.get("status") != "success":
                    print("❌ Broker rejection:", resp)
                    return None

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
            except Exception as e:
                print("❌ place_order exception:", e)
                return None

        return None

    # =========================
    # ORDER SEARCH (Idempotency)
    # =========================
    def find_order_by_client_id(self, client_order_id):
        orders = self.api.get_order_list() or []

        for o in orders:
            if o.get("tag") == client_order_id:
                return o

        return None

    # =========================
    # POSITION SYNC
    # =========================
    def get_positions(self):
        return self.api.get_positions()

    def sync_positions(self):
        """
        Broker truth → PositionManager
        """
        if not self.position_manager:
            return

        df = self.api.get_positions()
        if df is None or df.empty:
            return

        broker_positions = {}

        for _, row in df.iterrows():
            sym = row["tradingSymbol"]

            broker_positions[sym] = {
                "qty": int(row["netQty"]),
                "avg_price": float(row["avgPrice"]),
                "segment": row.get("segment", "EQ"),
                "lot_size": int(row.get("lotSize", 1)),
            }

        self.position_manager.reconcile_with_broker(broker_positions)

    # =========================
    # EXIT POSITION
    # =========================
    def exit_position(self, trading_symbol, qty, side, segment="EQ", lot_size=1):
        exit_side = "SELL" if side == "BUY" else "BUY"

        intent = {
            "intent_id": f"exit_{uuid.uuid4().hex[:6]}",
            "trading_symbol": trading_symbol,
            "side": exit_side,
            "qty": int(qty),
            "segment": segment,
            "lot_size": int(lot_size),
            "order_type": "MARKET",
            "trade_type": "MARGIN",
        }

        return self.place_order(intent)
