"""Dhan broker: order placement via DhanBrokerApi."""

import time
import uuid

from core.broker.base import BaseBroker


def _order_intent_to_payload(intent, execution_price=None):
    """Convert OrderIntent to dict for Dhan payload."""
    inst = intent.instrument
    segment_map = {
        "EQ": "NSE", "FUT": "NSE", "OPT": "NSE", "MCX": "MCX",
        "CRYPTO": "CRYPTO", "D": "NSE", "NSE": "NSE", "NFO": "NSE",
    }
    segment = getattr(inst, "segment", "NFO")
    exchange = segment_map.get(segment, "NSE")
    price = execution_price if execution_price is not None else (intent.price or 0)
    qty = getattr(intent, "qty", inst.lot_size)
    lot_size = int(getattr(inst, "lot_size", 1))
    total_qty = int(qty) * lot_size
    return {
        "tradingsymbol": inst.trading_symbol,
        "exchange": exchange,
        "quantity": total_qty,
        "price": float(price),
        "trigger_price": float(getattr(intent, "trigger_price", 0) or 0),
        "order_type": getattr(intent, "order_type", "MARKET"),
        "transaction_type": intent.side,
        "trade_type": getattr(intent, "trade_type", "MARGIN"),
        "disclosed_quantity": 0,
        "after_market_order": False,
        "validity": "DAY",
        "amo_time": "OPEN",
        "bo_profit_value": None,
        "bo_stop_loss_value": None,
        "tag": intent.intent_id,
        "intent_id": intent.intent_id,
    }


class DhanBroker(BaseBroker):
    """Order placement via Dhan. Uses IBrokerApi (DhanBrokerApi)."""

    def __init__(self, api, position_manager=None, intent_store=None):
        super().__init__(position_manager=position_manager, intent_store=intent_store)
        self.api = api

    def _build_payload(self, intent, execution_price=None):
        if hasattr(intent, "instrument"):
            return _order_intent_to_payload(intent, execution_price)
        segment_map = {
            "EQ": "NSE", "FUT": "NSE", "OPT": "NSE", "MCX": "MCX",
            "CRYPTO": "CRYPTO", "D": "NSE", "NSE": "NSE", "NFO": "NSE",
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
        price = execution_price if execution_price is not None else float(intent.get("price", 0) or 0)
        return {
            "tradingsymbol": intent["trading_symbol"],
            "exchange": exchange,
            "quantity": total_qty,
            "price": price,
            "trigger_price": float(intent.get("trigger_price", 0) or 0),
            "order_type": intent.get("order_type", "MARKET"),
            "transaction_type": intent["side"],
            "trade_type": intent.get("trade_type", "MARGIN"),
            "disclosed_quantity": int(intent.get("disclosed_quantity", 0)),
            "after_market_order": bool(intent.get("after_market_order", False)),
            "validity": intent.get("validity", "DAY"),
            "amo_time": intent.get("amo_time", "OPEN"),
            "bo_profit_value": intent.get("bo_profit_value", 0),
            "bo_stop_loss_value": intent.get("bo_stop_loss_value", 0),
            "tag": intent.get("intent_id"),
            "intent_id": intent.get("intent_id"),
        }

    def place_order(self, intent, execution_price=None, retries=2):
        order_payload = self._build_payload(intent, execution_price)
        intent_id = order_payload["intent_id"]
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
                    raise Exception(f"Invalid broker response: {resp}")
                if resp.get("status") != "success":
                    print("❌ Broker rejection:", resp)
                    return None
                order_id = resp.get("order_id")
                if self.intent_store:
                    self.intent_store.update(intent_id, "SENT")
                return order_id
            except TimeoutError:
                existing = self.find_order_by_client_id(intent_id)
                if existing:
                    return existing.get("order_id")
                if attempt == retries:
                    raise Exception("Order failed after retries")
                time.sleep(0.4)
            except Exception as e:
                print("❌ place_order exception:", e)
                return None
        return None

    def find_order_by_client_id(self, client_order_id):
        orders = self.api.get_order_list() or []
        for o in orders:
            if o.get("tag") == client_order_id:
                return o
        return None

    def get_positions(self):
        return self.api.get_positions()

    def sync_positions(self):
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
        return self.place_order(intent, execution_price=None)
