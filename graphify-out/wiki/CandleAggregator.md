# CandleAggregator

> 32 nodes

## Key Concepts

- **CandleAggregator** (25 connections) — `core/data/candle_aggregator.py`
- **.apply_exchange_candle()** (10 connections) — `core/data/candle_aggregator.py`
- **._propagate_from_closed_1m()** (9 connections) — `core/data/candle_aggregator.py`
- **.on_tick()** (8 connections) — `core/data/candle_aggregator.py`
- **.flush_session_end()** (6 connections) — `core/data/candle_aggregator.py`
- **Any** (6 connections)
- **_candle_to_dict()** (5 connections) — `core/data/candle_aggregator.py`
- **._ensure_symbol_tf()** (5 connections) — `core/data/candle_aggregator.py`
- **.flush_mcx_session_end()** (4 connections) — `core/data/candle_aggregator.py`
- **.get_all_closed_for_resolution()** (4 connections) — `core/data/candle_aggregator.py`
- **.get_last_closed_candle()** (4 connections) — `core/data/candle_aggregator.py`
- **.set_exchange_native_resolutions()** (4 connections) — `core/data/candle_aggregator.py`
- **.apply_exchange_1m_candle()** (3 connections) — `core/data/candle_aggregator.py`
- **._prune_session_end_flush_keys()** (3 connections) — `core/data/candle_aggregator.py`
- **._tick_price_sane()** (3 connections) — `core/data/candle_aggregator.py`
- **Notes** (3 connections) — `README.md`
- **_finalize_current()** (2 connections) — `core/data/candle_aggregator.py`
- **.__init__()** (2 connections) — `core/data/candle_aggregator.py`
- **.symbols_with_data()** (2 connections) — `core/data/candle_aggregator.py`
- **datetime** (2 connections)
- **Lock-free candle engine. Ticks update only 1m current; when 1m bucket changes,…** (1 connections) — `core/data/candle_aggregator.py`
- **Mark resolutions whose OHLC comes from exchange candlestick WS, not ticks.** (1 connections) — `core/data/candle_aggregator.py`
- **After configured session close (IST), finalize in-flight candles without…** (1 connections) — `core/data/candle_aggregator.py`
- **Backward-compatible alias for :meth:`flush_session_end`.** (1 connections) — `core/data/candle_aggregator.py`
- **Drop outlier ticks that would poison 1m high/low (e.g. 58300 on ~61100).** (1 connections) — `core/data/candle_aggregator.py`
- *... and 7 more nodes in this community*

## Relationships

- [factory.py](factory.py.md) (10 shared connections)
- [.create_live_engine](create_live_engine.md) (3 shared connections)
- [dummy_live.py](dummy_live.py.md) (2 shared connections)
- [delta_candlestick.py](delta_candlestick.py.md) (2 shared connections)
- [.start](start.md) (2 shared connections)
- [Live Engine](Live_Engine.md) (1 shared connections)
- [Runtime notes](Runtime_notes.md) (1 shared connections)
- [._run_watches](_run_watches.md) (1 shared connections)
- [LiveEngineHelpersMixin](LiveEngineHelpersMixin.md) (1 shared connections)
- [logging.py](logging.py.md) (1 shared connections)
- [Algo - Multi-Venue Trading System](Algo_-_Multi-Venue_Trading_System.md) (1 shared connections)
- [EngineConfig](EngineConfig.md) (1 shared connections)

## Source Files

- `README.md`
- `core/data/candle_aggregator.py`

## Audit Trail

- EXTRACTED: 62 (84%)
- INFERRED: 12 (16%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*