# factory.py

> 71 nodes

## Key Concepts

- **factory.py** (91 connections) — `core/engine/factory.py`
- **live_engine.py** (72 connections) — `core/engine/live_engine.py`
- **os** (39 connections)
- **refresh_crypto_indicator_history.py** (36 connections) — `utils/delta/refresh_crypto_indicator_history.py`
- **delta_source.py** (28 connections) — `core/data/sources/delta_source.py`
- **live_engine_common.py** (26 connections) — `core/engine/live_engine_common.py`
- **_resolution_to_seconds()** (25 connections) — `core/data/candle_aggregator.py`
- **round_json_floats()** (24 connections) — `core/utils/json_numeric.py`
- **base_engine.py** (19 connections) — `core/engine/base_engine.py`
- **engine_logger.py** (19 connections) — `utils/logger/engine_logger.py`
- **candle_aggregator.py** (18 connections) — `core/data/candle_aggregator.py`
- **backtest_engine.py** (18 connections) — `core/engine/backtest_engine.py`
- **indicator_manager.py** (17 connections) — `core/engine/indicator_manager.py`
- **BaseEngine** (16 connections) — `core/engine/base_engine.py`
- **open_positions_logger.py** (15 connections) — `utils/logger/open_positions_logger.py`
- **supervisor.py** (14 connections) — `core/engine/supervisor.py`
- **json_numeric.py** (13 connections) — `core/utils/json_numeric.py`
- **execution_engine.py** (12 connections) — `core/engine/execution_engine.py`
- **engine/__init__.py** (12 connections) — `core/engine/__init__.py`
- **kotak_env.py** (12 connections) — `core/utils/kotak_env.py`
- **collections** (10 connections)
- **risk_manager.py** (9 connections) — `core/orderExecution/risk_manager.py`
- **dotenv** (9 connections)
- **_bucket_ts()** (8 connections) — `core/data/candle_aggregator.py`
- **read_open_positions_snapshot()** (8 connections) — `utils/logger/open_positions_logger.py`
- *... and 46 more nodes in this community*

## Relationships

- [logging.py](logging.py.md) (54 shared connections)
- [typing](typing.md) (53 shared connections)
- [RunMode](RunMode.md) (44 shared connections)
- [indicator_history.py](indicator_history.py.md) (16 shared connections)
- [refresh_file](refresh_file.md) (14 shared connections)
- [CandleAggregator](CandleAggregator.md) (10 shared connections)
- [.create_live_engine](create_live_engine.md) (8 shared connections)
- [BacktestEngine](BacktestEngine.md) (7 shared connections)
- [EngineLogger](EngineLogger.md) (7 shared connections)
- [historical_cache.py](historical_cache.py.md) (7 shared connections)
- [kotak_source.py](kotak_source.py.md) (7 shared connections)
- [reentry_at_cost.py](reentry_at_cost.py.md) (7 shared connections)

## Source Files

- `core/data/candle_aggregator.py`
- `core/data/sources/delta_source.py`
- `core/engine/__init__.py`
- `core/engine/backtest_engine.py`
- `core/engine/base_engine.py`
- `core/engine/execution_engine.py`
- `core/engine/factory.py`
- `core/engine/indicator_manager.py`
- `core/engine/live_engine.py`
- `core/engine/live_engine_common.py`
- `core/engine/supervisor.py`
- `core/orderExecution/account_router.py`
- `core/orderExecution/risk_manager.py`
- `core/strategies/runtime_spec.py`
- `core/utils/delta_env.py`
- `core/utils/json_numeric.py`
- `core/utils/jsonl_rotate.py`
- `core/utils/kotak_env.py`
- `run/engine_lock.py`
- `utils/delta/refresh_crypto_indicator_history.py`

## Audit Trail

- EXTRACTED: 537 (99%)
- INFERRED: 5 (1%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*