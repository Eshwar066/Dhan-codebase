# ._run_watches

> 17 nodes

## Key Concepts

- **._run_watches()** (8 connections) — `core/orderExecution/gtt_fallback_book.py`
- **.tick()** (7 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Live Execution Flow** (7 connections) — `README.md`
- **.maintenance_tick()** (6 connections) — `core/orderExecution/gtt_fallback_book.py`
- **datetime** (6 connections)
- **Real-time WebSocket feeds** (6 connections) — `core/data/feeds/README.md`
- **.on_quote()** (5 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Operational notes** (5 connections) — `core/data/feeds/README.md`
- **Interface: `RealtimeFeed`** (3 connections) — `core/data/feeds/README.md`
- **Quote subscription (HYBRID_GTT)** (3 connections) — `core/data/feeds/README.md`
- **.has_active_watches()** (2 connections) — `core/orderExecution/gtt_fallback_book.py`
- **feeds/README.md** (1 connections) — `core/data/feeds/README.md`
- **Smoke test** (1 connections) — `core/data/feeds/README.md`
- **Execution modes (opt-in per intent)** (1 connections) — `README.md`
- **Full scan: fill sync, active_until, and quote triggers via QuoteProvider.** (1 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Fill sync + active_until only (no quote trigger). Use when quotes are push-…** (1 connections) — `core/orderExecution/gtt_fallback_book.py`
- **Push path: evaluate watches for ``trading_symbol`` using the feed quote. Prefer…** (1 connections) — `core/orderExecution/gtt_fallback_book.py`

## Relationships

- [GttFallbackBook](GttFallbackBook.md) (7 shared connections)
- [BidAskLtp](BidAskLtp.md) (2 shared connections)
- [GttFallbackWatch](GttFallbackWatch.md) (2 shared connections)
- [.start](start.md) (1 shared connections)
- [Event](Event.md) (1 shared connections)
- [Live Engine](Live_Engine.md) (1 shared connections)
- [RunMode](RunMode.md) (1 shared connections)
- [NiftySMA9Weekly](NiftySMA9Weekly.md) (1 shared connections)
- [logging.py](logging.py.md) (1 shared connections)
- [OrderRouter](OrderRouter.md) (1 shared connections)
- [PositionManager](PositionManager.md) (1 shared connections)
- [EngineLogger](EngineLogger.md) (1 shared connections)

## Source Files

- `README.md`
- `core/data/feeds/README.md`
- `core/orderExecution/gtt_fallback_book.py`

## Audit Trail

- EXTRACTED: 29 (64%)
- INFERRED: 16 (36%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*