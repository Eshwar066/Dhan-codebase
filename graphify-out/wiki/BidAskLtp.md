# BidAskLtp

> 19 nodes

## Key Concepts

- **BidAskLtp** (21 connections) — `core/orderExecution/gtt_fallback_book.py`
- **TestGttFallbackHarden** (11 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **CompositeQuoteProvider** (7 connections) — `core/orderExecution/gtt_fallback_book.py`
- **FeedQuoteProvider** (7 connections) — `core/orderExecution/gtt_fallback_book.py`
- **._watch()** (6 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **QuoteProvider** (5 connections) — `core/orderExecution/gtt_fallback_book.py`
- **.test_price_cap_allows_limit_below_170()** (4 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **.test_price_cap_skips_limit_above_170()** (4 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **.test_triggered_forever_skips_fallback_limit()** (4 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **.test_gtt_still_unfilled_treats_triggered_as_filled()** (3 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **.get_quote()** (2 connections) — `core/orderExecution/gtt_fallback_book.py`
- **.__init__()** (2 connections) — `core/orderExecution/gtt_fallback_book.py`
- **.get_quote()** (2 connections) — `core/orderExecution/gtt_fallback_book.py`
- **.__init__()** (2 connections) — `core/orderExecution/gtt_fallback_book.py`
- **.set_quote_provider()** (2 connections) — `core/orderExecution/gtt_fallback_book.py`
- **.get_quote()** (2 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Protocol** (1 connections)
- **Feed-first; REST when feed has no usable bid/ask.** (1 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Best bid/ask from a subscribed realtime feed cache.** (1 connections) — `core/orderExecution/gtt_fallback_book.py`

## Relationships

- [RunMode](RunMode.md) (8 shared connections)
- [GttFallbackBook](GttFallbackBook.md) (7 shared connections)
- [GttFallbackWatch](GttFallbackWatch.md) (5 shared connections)
- [Event](Event.md) (2 shared connections)
- [TestGttBrokerPositionAdopt](TestGttBrokerPositionAdopt.md) (2 shared connections)
- [._run_watches](_run_watches.md) (2 shared connections)
- [.option_identity_key](option_identity_key.md) (2 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [LiveEngine](LiveEngine.md) (2 shared connections)
- [RestQuoteProvider](RestQuoteProvider.md) (1 shared connections)
- [test_event_bus.py](test_event_bus.py.md) (1 shared connections)
- [test_gtt_quote_handler_push_calls_on_quote](test_gtt_quote_handler_push_calls_on_quote.md) (1 shared connections)

## Source Files

- `core/orderExecution/gtt_fallback_book.py`
- `core/orderExecution/test_gtt_broker_position_adopt.py`

## Audit Trail

- EXTRACTED: 52 (85%)
- INFERRED: 9 (15%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*