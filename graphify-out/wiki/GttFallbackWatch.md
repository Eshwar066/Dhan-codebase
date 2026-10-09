# GttFallbackWatch

> 25 nodes

## Key Concepts

- **GttFallbackWatch** (31 connections) — `core/orderExecution/gtt_fallback_book.py`
- **._tick_watch()** (19 connections) — `core/orderExecution/gtt_fallback_book.py`
- **._adopt_if_already_in()** (9 connections) — `core/orderExecution/gtt_fallback_book.py`
- **._broker_position_open()** (8 connections) — `core/orderExecution/gtt_fallback_book.py`
- **._maybe_adopt_broker_open_fill()** (8 connections) — `core/orderExecution/gtt_fallback_book.py`
- **.place_order_symbol()** (8 connections) — `core/utils/instruments/base.py`
- **._adopt_fill_from_broker()** (7 connections) — `core/orderExecution/gtt_fallback_book.py`
- **_fallback_limit_price()** (6 connections) — `core/orderExecution/gtt_fallback_book.py`
- **._cancel_open_child_day_orders()** (6 connections) — `core/orderExecution/gtt_fallback_book.py`
- **.on_fill()** (6 connections) — `core/orderExecution/gtt_fallback_book.py`
- **._forever_already_fired()** (5 connections) — `core/orderExecution/gtt_fallback_book.py`
- **_fallback_price_allowed()** (4 connections) — `core/orderExecution/gtt_fallback_book.py`
- **_trigger_met()** (4 connections) — `core/orderExecution/gtt_fallback_book.py`
- **._gtt_still_unfilled()** (3 connections) — `core/orderExecution/gtt_fallback_book.py`
- **._structure_filled()** (3 connections) — `core/orderExecution/gtt_fallback_book.py`
- **_symbol_key()** (1 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Adopt + complete watch when broker already has the leg or Forever fired.** (1 connections) — `core/orderExecution/gtt_fallback_book.py`
- **True when Dhan Forever is TRIGGERED/TRADED (child may be live or filled).** (1 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Cancel resting day BUY/SELL orders on this contract left by a Forever child…** (1 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Sync GTT ENTRY fill from Forever APIs or broker position so MAIN_SL arms.** (1 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Throttled broker-position adopt for watches whose Forever status is stale.** (1 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Check broker truth for this exact contract before placing fallback LIMIT.** (1 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Resting LIMIT after Forever cancel: use best ask (BUY) / best bid (SELL) so the…** (1 connections) — `core/orderExecution/gtt_fallback_book.py`
- **True when fallback LIMIT premium is strictly below max_fallback_price (if set).** (1 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Symbol string for broker order/margin APIs. Dhan: SEM_CUSTOM_SYMBOL (e.g.…** (1 connections) — `core/utils/instruments/base.py`

## Relationships

- [GttFallbackBook](GttFallbackBook.md) (26 shared connections)
- [RunMode](RunMode.md) (6 shared connections)
- [BidAskLtp](BidAskLtp.md) (5 shared connections)
- [TestGttBrokerPositionAdopt](TestGttBrokerPositionAdopt.md) (4 shared connections)
- [._broker_position_row_for_intent](_broker_position_row_for_intent.md) (3 shared connections)
- [._run_watches](_run_watches.md) (2 shared connections)
- [Any](Any.md) (1 shared connections)
- [OrderRouter](OrderRouter.md) (1 shared connections)
- [RestQuoteProvider](RestQuoteProvider.md) (1 shared connections)
- [DhanBroker](DhanBroker.md) (1 shared connections)
- [Instrument](Instrument.md) (1 shared connections)
- [.option_identity_key](option_identity_key.md) (1 shared connections)

## Source Files

- `core/orderExecution/gtt_fallback_book.py`
- `core/utils/instruments/base.py`

## Audit Trail

- EXTRACTED: 85 (89%)
- INFERRED: 10 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*