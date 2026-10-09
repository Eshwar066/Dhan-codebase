# DhanBrokerApi

> 21 nodes

## Key Concepts

- **DhanBrokerApi** (21 connections) — `core/broker/internal/dhan/api.py`
- **Any** (8 connections)
- **TestDh906SlPricing** (5 connections) — `core/broker/internal/dhan/test_dh906_sl_pricing.py`
- **dhan/api.py** (5 connections) — `core/broker/internal/dhan/api.py`
- **dhan/__init__.py** (5 connections) — `core/broker/internal/dhan/__init__.py`
- **.get_fills()** (4 connections) — `core/broker/internal/dhan/api.py`
- **.get_forever_orders()** (3 connections) — `core/broker/internal/dhan/api.py`
- **.get_order_by_id()** (3 connections) — `core/broker/internal/dhan/api.py`
- **.test_place_order_api_preserves_decimal_ticks()** (3 connections) — `core/broker/internal/dhan/test_dh906_sl_pricing.py`
- **.cancel_forever_order()** (2 connections) — `core/broker/internal/dhan/api.py`
- **.get_order_list()** (2 connections) — `core/broker/internal/dhan/api.py`
- **.get_positions()** (2 connections) — `core/broker/internal/dhan/api.py`
- **.place_forever_order()** (2 connections) — `core/broker/internal/dhan/api.py`
- **.place_order()** (2 connections) — `core/broker/internal/dhan/api.py`
- **.test_order_intent_payload_sell_sl_not_equal()** (2 connections) — `core/broker/internal/dhan/test_dh906_sl_pricing.py`
- **.test_quantize_sell_stop_nudges_limit_below_trigger()** (2 connections) — `core/broker/internal/dhan/test_dh906_sl_pricing.py`
- **.__init__()** (1 connections) — `core/broker/internal/dhan/api.py`
- **Dhan broker API: order placement and position/order lookup via Dhan.** (1 connections) — `core/broker/internal/dhan/api.py`
- **Fills from order list (filled/TRADED orders) for trade-led OMS.** (1 connections) — `core/broker/internal/dhan/api.py`
- **IBrokerApi implementation for Dhan. Order placement + positions + order list.** (1 connections) — `core/broker/internal/dhan/api.py`
- **Regression: int(price) collapsed 72.85/72.9 → 72/72 → DH-906.** (1 connections) — `core/broker/internal/dhan/test_dh906_sl_pricing.py`

## Relationships

- [DhanBroker](DhanBroker.md) (5 shared connections)
- [RunMode](RunMode.md) (3 shared connections)
- [BaseBroker](BaseBroker.md) (2 shared connections)
- [KotakBroker](KotakBroker.md) (2 shared connections)
- [dhan/broker.py](dhan-broker.py.md) (2 shared connections)
- [.create_live_engine](create_live_engine.md) (1 shared connections)
- [factory.py](factory.py.md) (1 shared connections)
- [DeltaBrokerApi](DeltaBrokerApi.md) (1 shared connections)
- [typing](typing.md) (1 shared connections)

## Source Files

- `core/broker/internal/dhan/__init__.py`
- `core/broker/internal/dhan/api.py`
- `core/broker/internal/dhan/test_dh906_sl_pricing.py`

## Audit Trail

- EXTRACTED: 41 (87%)
- INFERRED: 6 (13%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*