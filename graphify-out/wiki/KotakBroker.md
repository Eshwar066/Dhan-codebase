# KotakBroker

> 52 nodes

## Key Concepts

- **KotakBroker** (25 connections) — `core/broker/internal/kotak/broker.py`
- **KotakBrokerApi** (17 connections) — `core/broker/internal/kotak/api.py`
- **internal/__init__.py** (17 connections) — `core/broker/internal/__init__.py`
- **test_kotak_mappings.py** (17 connections) — `core/broker/internal/kotak/test_kotak_mappings.py`
- **kotak/broker.py** (10 connections) — `core/broker/internal/kotak/broker.py`
- **.calculate_structure_margin()** (9 connections) — `core/broker/internal/kotak/broker.py`
- **.check_funds_before_orders()** (8 connections) — `core/broker/internal/kotak/broker.py`
- **kotak/api.py** (7 connections) — `core/broker/internal/kotak/api.py`
- **Any** (7 connections)
- **Any** (6 connections)
- **TestKotakBrokerPlace** (5 connections) — `core/broker/internal/kotak/test_kotak_mappings.py`
- **._build_margin_leg_payload()** (5 connections) — `core/broker/internal/kotak/broker.py`
- **._parse_margin_response()** (5 connections) — `core/broker/internal/kotak/broker.py`
- **kotak/__init__.py** (5 connections) — `core/broker/internal/kotak/__init__.py`
- **core_broker_internal_kotak** (5 connections)
- **TestKotakMappings** (4 connections) — `core/broker/internal/kotak/test_kotak_mappings.py`
- **._estimate_hedge_benefit()** (4 connections) — `core/broker/internal/kotak/broker.py`
- **._get_available_balance()** (4 connections) — `core/broker/internal/kotak/broker.py`
- **.modify_order()** (3 connections) — `core/broker/internal/kotak/api.py`
- **.__init__()** (3 connections) — `core/broker/internal/kotak/broker.py`
- **.place_order()** (3 connections) — `core/broker/internal/kotak/broker.py`
- **simulated/__init__.py** (3 connections) — `core/broker/internal/simulated/__init__.py`
- **.cancel_order()** (2 connections) — `core/broker/internal/kotak/api.py`
- **.get_order_by_id()** (2 connections) — `core/broker/internal/kotak/api.py`
- **.get_order_list()** (2 connections) — `core/broker/internal/kotak/api.py`
- *... and 27 more nodes in this community*

## Relationships

- [BaseBroker](BaseBroker.md) (6 shared connections)
- [RunMode](RunMode.md) (4 shared connections)
- [kotak/mappings.py](kotak-mappings.py.md) (3 shared connections)
- [logging.py](logging.py.md) (3 shared connections)
- [KotakWebSocketFeed](KotakWebSocketFeed.md) (3 shared connections)
- [.create_live_engine](create_live_engine.md) (2 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [DhanBroker](DhanBroker.md) (2 shared connections)
- [KotakSource](KotakSource.md) (2 shared connections)
- [DhanBrokerApi](DhanBrokerApi.md) (2 shared connections)
- [DeltaBrokerApi](DeltaBrokerApi.md) (2 shared connections)
- [SimulatedBroker](SimulatedBroker.md) (2 shared connections)

## Source Files

- `core/broker/internal/__init__.py`
- `core/broker/internal/kotak/__init__.py`
- `core/broker/internal/kotak/api.py`
- `core/broker/internal/kotak/broker.py`
- `core/broker/internal/kotak/test_kotak_mappings.py`
- `core/broker/internal/simulated/__init__.py`

## Audit Trail

- EXTRACTED: 119 (95%)
- INFERRED: 6 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*