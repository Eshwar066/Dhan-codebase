# option_buildup_scheduler.py

> 24 nodes

## Key Concepts

- **option_buildup_scheduler.py** (22 connections) — `run/option_buildup_scheduler.py`
- **DataRouter** (17 connections) — `core/data/data_router.py`
- **OptionChainService** (15 connections) — `core/data/option_chain_service.py`
- **run_scheduler()** (10 connections) — `run/option_buildup_scheduler.py`
- **Layer responsibilities** (5 connections) — `docs/module_map.md`
- **.get_chain()** (4 connections) — `core/data/option_chain_service.py`
- **._resolve_api()** (4 connections) — `core/data/option_chain_service.py`
- **.resolve_api()** (3 connections) — `core/data/data_router.py`
- **.get_expiries()** (3 connections) — `core/data/option_chain_service.py`
- **.__init__()** (3 connections) — `core/engine/base_engine.py`
- **_extract_close()** (3 connections) — `run/option_buildup_scheduler.py`
- **_is_market_window_ist()** (3 connections) — `run/option_buildup_scheduler.py`
- **main()** (3 connections) — `run/option_buildup_scheduler.py`
- **_next_five_min_slot_ist()** (3 connections) — `run/option_buildup_scheduler.py`
- **_parse_args()** (3 connections) — `run/option_buildup_scheduler.py`
- **datetime** (3 connections)
- **.from_candle()** (2 connections) — `core/data/data_router.py`
- **.__init__()** (1 connections) — `core/data/option_chain_service.py`
- **Any** (1 connections)
- **Namespace** (1 connections)
- **Pick an option-chain adapter by API key. Engines set ``default_api`` from the…** (1 connections) — `core/data/data_router.py`
- **Fetch option chain; ``api`` is resolved via DataRouter.default_api when set.** (1 connections) — `core/data/option_chain_service.py`
- **Standalone Option Buildup scheduler. - Runs on wall-clock IST 5-minute slots…** (1 connections) — `run/option_buildup_scheduler.py`
- **core_strategies_openintrest_optionbuildup** (1 connections)

## Relationships

- [StrategyContext](StrategyContext.md) (10 shared connections)
- [factory.py](factory.py.md) (5 shared connections)
- [kotak_data_provider.py](kotak_data_provider.py.md) (3 shared connections)
- [RunMode](RunMode.md) (3 shared connections)
- [logging.py](logging.py.md) (3 shared connections)
- [typing](typing.md) (2 shared connections)
- [IDataProvider](IDataProvider.md) (2 shared connections)
- [DhanSource](DhanSource.md) (2 shared connections)
- [DhanDataProvider](DhanDataProvider.md) (2 shared connections)
- [OptionBuildup](OptionBuildup.md) (2 shared connections)
- [indicator_history_path](indicator_history_path.md) (1 shared connections)
- [docs/README.md](docs-README.md.md) (1 shared connections)

## Source Files

- `core/data/data_router.py`
- `core/data/option_chain_service.py`
- `core/engine/base_engine.py`
- `docs/module_map.md`
- `run/option_buildup_scheduler.py`

## Audit Trail

- EXTRACTED: 61 (81%)
- INFERRED: 14 (19%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*