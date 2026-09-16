# dhan/broker.py

> 30 nodes

## Key Concepts

- **dhan/broker.py** (21 connections) — `core/broker/internal/dhan/broker.py`
- **parse_dhan_api_error()** (15 connections) — `core/broker/internal/dhan/mappings.py`
- **dhan/mappings.py** (13 connections) — `core/broker/internal/dhan/mappings.py`
- **_order_intent_to_payload()** (9 connections) — `core/broker/internal/dhan/broker.py`
- **GlobalRateLimiter** (8 connections) — `core/utils/global_rate_limiter.py`
- **to_broker_place_order_payload()** (8 connections) — `core/broker/internal/dhan/mappings.py`
- **format_broker_failure_for_log()** (6 connections) — `core/broker/internal/dhan/mappings.py`
- **from_broker_error()** (4 connections) — `core/broker/internal/dhan/mappings.py`
- **_walk()** (4 connections) — `core/broker/internal/dhan/mappings.py`
- **Any** (4 connections)
- **internal_segment_to_exchange_arg()** (3 connections) — `core/broker/internal/dhan/mappings.py`
- **normalize_order_type()** (3 connections) — `core/broker/internal/dhan/mappings.py`
- **.place_forever_order()** (3 connections) — `core/data/sources/dhan_source.py`
- **.place_order()** (3 connections) — `core/data/sources/dhan_source.py`
- **normalize_trade_type()** (2 connections) — `core/broker/internal/dhan/mappings.py`
- **normalize_validity()** (2 connections) — `core/broker/internal/dhan/mappings.py`
- **_merge()** (2 connections) — `core/broker/internal/dhan/mappings.py`
- **.acquire()** (2 connections) — `core/utils/global_rate_limiter.py`
- **core_broker_internal_dhan** (2 connections)
- **.__init__()** (1 connections) — `core/utils/global_rate_limiter.py`
- **Dhan broker: order placement via DhanBrokerApi. Trade-led OMS via…** (1 connections) — `core/broker/internal/dhan/broker.py`
- **Convert OrderIntent to dict for Dhan payload.** (1 connections) — `core/broker/internal/dhan/broker.py`
- **Single contract with DhanHQ v2 field semantics (see Annexure in docs). Maps…** (1 connections) — `core/broker/internal/dhan/mappings.py`
- **Normalize a loose intent dict to DhanBroker / DhanSource.place_order kwargs…** (1 connections) — `core/broker/internal/dhan/mappings.py`
- **Normalize Dhan error payload to (message, error_type, error_code).** (1 connections) — `core/broker/internal/dhan/mappings.py`
- *... and 5 more nodes in this community*

## Relationships

- [DhanBroker](DhanBroker.md) (12 shared connections)
- [logging.py](logging.py.md) (6 shared connections)
- [RunMode](RunMode.md) (5 shared connections)
- [typing](typing.md) (3 shared connections)
- [DhanBrokerApi](DhanBrokerApi.md) (2 shared connections)
- [Any](Any.md) (2 shared connections)
- [DhanSource](DhanSource.md) (2 shared connections)
- [BaseBroker](BaseBroker.md) (2 shared connections)
- [roll_leaps_hedge.py](roll_leaps_hedge.py.md) (2 shared connections)
- [DhanMarketFeedClient](DhanMarketFeedClient.md) (1 shared connections)
- [BankNiftyBTST](BankNiftyBTST.md) (1 shared connections)
- [KotakBroker](KotakBroker.md) (1 shared connections)

## Source Files

- `core/broker/internal/dhan/broker.py`
- `core/broker/internal/dhan/mappings.py`
- `core/data/sources/dhan_source.py`
- `core/utils/global_rate_limiter.py`

## Audit Trail

- EXTRACTED: 80 (98%)
- INFERRED: 2 (2%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*