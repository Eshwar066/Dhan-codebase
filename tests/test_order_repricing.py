from types import SimpleNamespace

from core.orderExecution.intent_store import IntentStatus, IntentStore
from core.orderExecution.order_router import OrderRouter


class _Broker:
    def __init__(self, order):
        self.order = order
        self.updates = []

    def find_order_by_client_id(self, _intent_id):
        return self.order

    def update_order_price(self, **kwargs):
        self.updates.append(kwargs)
        return True


def _router_for_entry(order, *, order_type="LIMIT"):
    store = IntentStore()
    payload = {
        "action": "ENTRY",
        "order_type": order_type,
        "side": "SELL",
        "symbol": "BTCUSD",
    }
    record = store.create(payload, intent_id="I1")
    store.update("I1", IntentStatus.VALIDATED)
    store.update("I1", IntentStatus.SENT, broker_order_id="B1")
    record["instrument"] = SimpleNamespace(trading_symbol="P-BTC-62000-180726")
    record["side"] = "SELL"
    record["last_price_update_ts"] = 0

    router = object.__new__(OrderRouter)
    router.broker = _Broker(order)
    router.intent_store = store
    router.engine_logger = None
    return router


def test_open_sell_entry_is_repriced_to_best_bid_and_throttled():
    router = _router_for_entry(
        {
            "status": "live",
            "product_id": 123,
            "order_id": "B1",
            "remaining_qty": 2,
            "price": 6.4,
        }
    )

    router.refresh_stale_entry_orders(lambda _symbol: (6.2, 6.4), stale_seconds=30)
    router.refresh_stale_entry_orders(lambda _symbol: (6.1, 6.3), stale_seconds=30)

    assert router.broker.updates == [
        {"product_id": 123, "order_id": "B1", "new_limit_price": 6.2}
    ]


def test_entry_reprice_skips_filled_or_mismatched_orders():
    filled = _router_for_entry(
        {
            "status": "open",
            "product_id": 123,
            "order_id": "B1",
            "remaining_qty": 0,
            "price": 6.4,
        }
    )
    mismatched = _router_for_entry(
        {
            "status": "open",
            "product_id": 123,
            "order_id": "OTHER",
            "remaining_qty": 2,
            "price": 6.4,
        }
    )

    filled.refresh_stale_entry_orders(lambda _symbol: (6.2, 6.4))
    mismatched.refresh_stale_entry_orders(lambda _symbol: (6.2, 6.4))

    assert filled.broker.updates == []
    assert mismatched.broker.updates == []


def test_entry_reprice_skips_non_limit_orders():
    router = _router_for_entry(
        {
            "status": "open",
            "product_id": 123,
            "order_id": "B1",
            "remaining_qty": 2,
            "price": 0,
        },
        order_type="MARKET",
    )

    router.refresh_stale_entry_orders(lambda _symbol: (6.2, 6.4))

    assert router.broker.updates == []
