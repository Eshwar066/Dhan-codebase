# DeltaBroker

> 69 nodes

## Key Concepts

- **DeltaBroker** (42 connections) — `core/broker/internal/delta/broker.py`
- **delta/broker.py** (14 connections) — `core/broker/internal/delta/broker.py`
- **Any** (13 connections)
- **test_delta_no_market_orders.py** (10 connections) — `core/broker/internal/delta/test_delta_no_market_orders.py`
- **TestDeltaNoMarketOrders** (9 connections) — `core/broker/internal/delta/test_delta_no_market_orders.py`
- **.place_combined_bracket_orders()** (9 connections) — `core/broker/internal/delta/broker.py`
- **_delta_limit_price_from_payload()** (7 connections) — `core/broker/internal/delta/broker.py`
- **.find_bracket_leg_order_id()** (7 connections) — `core/broker/internal/delta/broker.py`
- **_intent_to_delta_payload()** (7 connections) — `core/broker/internal/delta/broker.py`
- **.has_bracket_leg_on_exchange()** (6 connections) — `core/broker/internal/delta/broker.py`
- **.check_funds_before_order()** (5 connections) — `core/broker/internal/delta/broker.py`
- **.get_balance_snapshot()** (5 connections) — `core/broker/internal/delta/broker.py`
- **._live_orders_for_symbol()** (5 connections) — `core/broker/internal/delta/broker.py`
- **.place_order()** (5 connections) — `core/broker/internal/delta/broker.py`
- **._delta_symbol_limit_price()** (4 connections) — `core/broker/internal/delta/broker.py`
- **.exit_position()** (4 connections) — `core/broker/internal/delta/broker.py`
- **._find_order_in_history_or_fills()** (4 connections) — `core/broker/internal/delta/broker.py`
- **.get_fill_by_order_id()** (4 connections) — `core/broker/internal/delta/broker.py`
- **.get_fill_for_client_order_id()** (4 connections) — `core/broker/internal/delta/broker.py`
- **.get_ticker()** (4 connections) — `core/broker/internal/delta/broker.py`
- **_delta_required_margin()** (3 connections) — `core/broker/internal/delta/broker.py`
- **._bracket_leg_type_for_tag()** (3 connections) — `core/broker/internal/delta/broker.py`
- **.cancel_order_by_id()** (3 connections) — `core/broker/internal/delta/broker.py`
- **.find_order_by_client_id()** (3 connections) — `core/broker/internal/delta/broker.py`
- **.find_order_by_id()** (3 connections) — `core/broker/internal/delta/broker.py`
- *... and 44 more nodes in this community*

## Relationships

- [BaseBroker](BaseBroker.md) (5 shared connections)
- [DeltaSource](DeltaSource.md) (3 shared connections)
- [.create_live_engine](create_live_engine.md) (2 shared connections)
- [DeltaBrokerApi](DeltaBrokerApi.md) (2 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [.option_identity_key](option_identity_key.md) (2 shared connections)
- [logging.py](logging.py.md) (2 shared connections)
- [typing](typing.md) (2 shared connections)
- [RunMode](RunMode.md) (2 shared connections)
- [KotakBroker](KotakBroker.md) (1 shared connections)
- [Component Details](Component_Details.md) (1 shared connections)
- [._maybe_switch_premium_sl_to_index](_maybe_switch_premium_sl_to_index.md) (1 shared connections)

## Source Files

- `core/broker/internal/delta/broker.py`
- `core/broker/internal/delta/test_delta_no_market_orders.py`

## Audit Trail

- EXTRACTED: 126 (91%)
- INFERRED: 13 (9%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*