# DhanBroker

> 61 nodes

## Key Concepts

- **DhanBroker** (44 connections) — `core/broker/internal/dhan/broker.py`
- **dhan_correlation_id()** (16 connections) — `core/broker/internal/dhan/mappings.py`
- **Any** (13 connections)
- **_quantize_order_prices()** (9 connections) — `core/broker/internal/dhan/broker.py`
- **._build_payload()** (8 connections) — `core/broker/internal/dhan/broker.py`
- **.check_funds_before_order()** (8 connections) — `core/broker/internal/dhan/broker.py`
- **.check_funds_before_orders()** (8 connections) — `core/broker/internal/dhan/broker.py`
- **.place_order()** (8 connections) — `core/broker/internal/dhan/broker.py`
- **.find_forever_order_by_client_id()** (7 connections) — `core/broker/internal/dhan/broker.py`
- **.get_all_forever_orders_raw()** (6 connections) — `core/broker/internal/dhan/broker.py`
- **.get_recent_fills()** (6 connections) — `core/broker/internal/dhan/broker.py`
- **.modify_order_price()** (6 connections) — `core/broker/internal/dhan/broker.py`
- **.find_order_by_id()** (5 connections) — `core/broker/internal/dhan/broker.py`
- **.get_fill_for_client_order_id()** (5 connections) — `core/broker/internal/dhan/broker.py`
- **.get_forever_open_orders()** (5 connections) — `core/broker/internal/dhan/broker.py`
- **._normalize_forever_order_for_recon()** (5 connections) — `core/broker/internal/dhan/broker.py`
- **._place_forever_order()** (5 connections) — `core/broker/internal/dhan/broker.py`
- **.instance()** (5 connections) — `core/utils/global_rate_limiter.py`
- **.cancel_open_day_orders_for_symbol()** (4 connections) — `core/broker/internal/dhan/broker.py`
- **.cancel_order_by_id()** (4 connections) — `core/broker/internal/dhan/broker.py`
- **.find_order_by_client_id()** (4 connections) — `core/broker/internal/dhan/broker.py`
- **.get_fill_by_order_id()** (4 connections) — `core/broker/internal/dhan/broker.py`
- **._parse_margin_shortfall()** (4 connections) — `core/broker/internal/dhan/broker.py`
- **TestForeverTriggeredNormalize** (3 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **._get_available_balance()** (3 connections) — `core/broker/internal/dhan/broker.py`
- *... and 36 more nodes in this community*

## Relationships

- [dhan/broker.py](dhan-broker.py.md) (12 shared connections)
- [DhanBrokerApi](DhanBrokerApi.md) (5 shared connections)
- [RunMode](RunMode.md) (5 shared connections)
- [._get_dhan_http](_get_dhan_http.md) (3 shared connections)
- [BaseBroker](BaseBroker.md) (2 shared connections)
- [KotakBroker](KotakBroker.md) (2 shared connections)
- [Any](Any.md) (2 shared connections)
- [OrderRouter](OrderRouter.md) (2 shared connections)
- [.create_live_engine](create_live_engine.md) (1 shared connections)
- [factory.py](factory.py.md) (1 shared connections)
- [Component Details](Component_Details.md) (1 shared connections)
- [GttFallbackWatch](GttFallbackWatch.md) (1 shared connections)

## Source Files

- `core/broker/internal/dhan/broker.py`
- `core/broker/internal/dhan/mappings.py`
- `core/library/dhan_tradehull.py`
- `core/orderExecution/test_gtt_broker_position_adopt.py`
- `core/utils/global_rate_limiter.py`

## Audit Trail

- EXTRACTED: 135 (93%)
- INFERRED: 10 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*