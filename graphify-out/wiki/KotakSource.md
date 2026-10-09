# KotakSource

> 24 nodes

## Key Concepts

- **KotakSource** (24 connections) — `core/data/sources/kotak_source.py`
- **Any** (18 connections)
- **.api()** (8 connections) — `core/data/sources/kotak_source.py`
- **.fetch_quote_map()** (6 connections) — `core/data/sources/kotak_source.py`
- **._fetch_quote_map_via_ws()** (5 connections) — `core/data/sources/kotak_source.py`
- **.get_option_chain_for_expiry()** (3 connections) — `core/data/sources/kotak_source.py`
- **.get_order_by_id()** (3 connections) — `core/data/sources/kotak_source.py`
- **.get_order_list()** (3 connections) — `core/data/sources/kotak_source.py`
- **._is_quotes_error()** (3 connections) — `core/data/sources/kotak_source.py`
- **.quotes()** (3 connections) — `core/data/sources/kotak_source.py`
- **.cancel_order()** (2 connections) — `core/data/sources/kotak_source.py`
- **.get_holdings()** (2 connections) — `core/data/sources/kotak_source.py`
- **.get_positions()** (2 connections) — `core/data/sources/kotak_source.py`
- **.limits()** (2 connections) — `core/data/sources/kotak_source.py`
- **.margin_required()** (2 connections) — `core/data/sources/kotak_source.py`
- **.modify_order()** (2 connections) — `core/data/sources/kotak_source.py`
- **.place_order()** (2 connections) — `core/data/sources/kotak_source.py`
- **.scrip_master()** (2 connections) — `core/data/sources/kotak_source.py`
- **.search_scrip()** (2 connections) — `core/data/sources/kotak_source.py`
- **_run()** (1 connections) — `core/data/sources/kotak_source.py`
- **Map ``instrument_token`` → quote payload. Prefers REST ``quotes``; falls back…** (1 connections) — `core/data/sources/kotak_source.py`
- **Single entry for Kotak Neo: orders, positions, quotes, scrip master. Historical…** (1 connections) — `core/data/sources/kotak_source.py`
- **One-shot SFeed snapshot(+subscribe) for LTP/bid/ask.** (1 connections) — `core/data/sources/kotak_source.py`
- **Fetch all options for a given expiry from Kotak's live API. Uses search_scrip…** (1 connections) — `core/data/sources/kotak_source.py`

## Relationships

- [kotak_source.py](kotak_source.py.md) (4 shared connections)
- [.create_live_engine](create_live_engine.md) (2 shared connections)
- [KotakBroker](KotakBroker.md) (2 shared connections)
- [IndiaMktMixins](IndiaMktMixins.md) (2 shared connections)
- [factory.py](factory.py.md) (1 shared connections)
- [DosTrailSlMixin](DosTrailSlMixin.md) (1 shared connections)
- [Event-Driven Strategy Guide](Event-Driven_Strategy_Guide.md) (1 shared connections)

## Source Files

- `core/data/sources/kotak_source.py`

## Audit Trail

- EXTRACTED: 48 (86%)
- INFERRED: 8 (14%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*