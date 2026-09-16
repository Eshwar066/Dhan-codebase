# dummy_live.py

> 23 nodes

## Key Concepts

- **dummy_live.py** (20 connections) — `run/dummy_live.py`
- **strategy_profiles.py** (18 connections) — `run/strategy_profiles.py`
- **resolve_engine_job()** (17 connections) — `run/strategy_profiles.py`
- **main()** (10 connections) — `run/dummy_live.py`
- **collect_engine_symbols()** (4 connections) — `run/strategy_profiles.py`
- **_parse_start_datetime()** (3 connections) — `run/dummy_live.py`
- **_resolve_job()** (3 connections) — `run/dummy_live.py`
- **get_strategy_profile()** (3 connections) — `run/strategy_profiles.py`
- **_merge_backtest_dicts()** (3 connections) — `run/strategy_profiles.py`
- **_merge_live_dicts()** (3 connections) — `run/strategy_profiles.py`
- **symbols_for_strategy()** (3 connections) — `run/strategy_profiles.py`
- **Any** (3 connections)
- **build_strategy_eval_map()** (2 connections) — `run/strategy_profiles.py`
- **_symbols_from_strategy_class()** (2 connections) — `run/strategy_profiles.py`
- **datetime** (2 connections)
- **core_data_feeds** (2 connections)
- **profiles.py** (1 connections) — `core/strategies/_generated/profiles.py`
- **Any** (1 connections)
- **Run a strategy with DummyRealtimeFeed + CandleAggregator in PAPER mode. Usage…** (1 connections) — `run/dummy_live.py`
- **Per-strategy defaults: symbols, live/backtest venue settings, eval mode, Delta…** (1 connections) — `run/strategy_profiles.py`
- **Union of strategy symbols; ``None`` when universe-driven (e.g. IPO).** (1 connections) — `run/strategy_profiles.py`
- **Merge engine job with strategy profiles. Engine job keeps: engine_id, venue,…** (1 connections) — `run/strategy_profiles.py`
- **copy** (1 connections)

## Relationships

- [RunMode](RunMode.md) (5 shared connections)
- [.create_live_engine](create_live_engine.md) (4 shared connections)
- [main.py](main.py.md) (4 shared connections)
- [factory.py](factory.py.md) (4 shared connections)
- [force_leaps_cycle.py](force_leaps_cycle.py.md) (3 shared connections)
- [roll_leaps_hedge.py](roll_leaps_hedge.py.md) (3 shared connections)
- [EngineConfig](EngineConfig.md) (2 shared connections)
- [CandleAggregator](CandleAggregator.md) (2 shared connections)
- [DummyRealtimeFeed](DummyRealtimeFeed.md) (2 shared connections)
- [typing](typing.md) (2 shared connections)
- [indicator_history_path](indicator_history_path.md) (1 shared connections)
- [registry.py](registry.py.md) (1 shared connections)

## Source Files

- `core/strategies/_generated/profiles.py`
- `run/dummy_live.py`
- `run/strategy_profiles.py`

## Audit Trail

- EXTRACTED: 67 (97%)
- INFERRED: 2 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*