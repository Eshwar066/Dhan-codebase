# ._rest_option_quote

> 12 nodes

## Key Concepts

- **._rest_option_quote()** (7 connections) — `core/engine/live_engine_common.py`
- **._entry_price_from_depth()** (5 connections) — `core/engine/live_engine_common.py`
- **._exit_price_from_depth()** (5 connections) — `core/engine/live_engine_common.py`
- **._get_bid_ask()** (5 connections) — `core/engine/live_engine_common.py`
- **._is_spread_acceptable()** (5 connections) — `core/engine/live_engine_common.py`
- **._get_tick_size()** (4 connections) — `core/engine/live_engine_common.py`
- **.get_price_map()** (2 connections) — `core/engine/live_engine_common.py`
- **Institutional upgrades (roadmap)** (2 connections) — `core/engine/readme.md`
- **Return tick size for symbol from cache (populated at startup); fill cache on…** (1 connections) — `core/engine/live_engine_common.py`
- **Return (bid, ask, ltp) via data provider quote API, or None.** (1 connections) — `core/engine/live_engine_common.py`
- **True if both bid/ask exist and spread <= max_spread_pct * bid. Blocks wide…** (1 connections) — `core/engine/live_engine_common.py`
- **Return (best_bid, best_ask) for symbol from feed; (None, None) if unavailable.** (1 connections) — `core/engine/live_engine_common.py`

## Relationships

- [LiveEngineHelpersMixin](LiveEngineHelpersMixin.md) (7 shared connections)
- [RestQuoteProvider](RestQuoteProvider.md) (1 shared connections)
- [Live Engine](Live_Engine.md) (1 shared connections)

## Source Files

- `core/engine/live_engine_common.py`
- `core/engine/readme.md`

## Audit Trail

- EXTRACTED: 23 (96%)
- INFERRED: 1 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*