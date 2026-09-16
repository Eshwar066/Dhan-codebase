# .reconcile_with_broker

> 22 nodes

## Key Concepts

- **.reconcile_with_broker()** (15 connections) — `core/orderExecution/position_manager.py`
- **._extract_option_hint()** (10 connections) — `core/orderExecution/position_manager.py`
- **load_position_metadata_from_csv()** (9 connections) — `utils/logger/open_positions_logger.py`
- **.merge_ownership_from_all_strategy_open_positions_csvs()** (7 connections) — `core/orderExecution/position_manager.py`
- **.rebuild_open_positions_from_open_positions_csv()** (7 connections) — `core/orderExecution/position_manager.py`
- **._merge_position_metadata()** (6 connections) — `core/orderExecution/position_manager.py`
- **._pair_orphan_hedge_legs_locked()** (6 connections) — `core/orderExecution/position_manager.py`
- **._detect_hedge_position()** (5 connections) — `core/orderExecution/position_manager.py`
- **._merge_open_positions_csv_dict()** (4 connections) — `core/orderExecution/position_manager.py`
- **.rebuild_position_metadata_from_open_positions_csv()** (4 connections) — `core/orderExecution/position_manager.py`
- **.sync_symbol_flat_at_broker()** (3 connections) — `core/orderExecution/position_manager.py`
- **_identity()** (2 connections) — `core/orderExecution/position_manager.py`
- **_row_to_meta()** (1 connections) — `utils/logger/open_positions_logger.py`
- **Merge metadata from logs/{engine_id}_open_positions.csv (strategy_meta, etc.).** (1 connections) — `core/orderExecution/position_manager.py`
- **After restart, restore open legs into PM from the open-positions CSV snapshot…** (1 connections) — `core/orderExecution/position_manager.py`
- **Best-effort parse of (option_type, strike) from structure_id / trading_symbol.…** (1 connections) — `core/orderExecution/position_manager.py`
- **Detect if a position is a HEDGE leg based on structure characteristics. Hedge…** (1 connections) — `core/orderExecution/position_manager.py`
- **Sync PositionManager to broker truth. broker_positions: { symbol: { "qty": int,…** (1 connections) — `core/orderExecution/position_manager.py`
- **Attach untagged long options to the unique short MAIN on the same underlying.…** (1 connections) — `core/orderExecution/position_manager.py`
- **Broker confirms no open position (manual exit / no_open_position). Drop local…** (1 connections) — `core/orderExecution/position_manager.py`
- **Multi-strategy engines store ownership in…** (1 connections) — `core/orderExecution/position_manager.py`
- **Replay {engine_id}_open_positions.csv and return trading_symbol -> metadata…** (1 connections) — `utils/logger/open_positions_logger.py`

## Relationships

- [PositionManager](PositionManager.md) (10 shared connections)
- [normalize_fill_side](normalize_fill_side.md) (4 shared connections)
- [.option_identity_key](option_identity_key.md) (3 shared connections)
- [.symbol_underlying_root](symbol_underlying_root.md) (3 shared connections)
- [factory.py](factory.py.md) (3 shared connections)
- [Position](Position.md) (2 shared connections)
- [GttFallbackBook](GttFallbackBook.md) (1 shared connections)
- [.seed_filled_intents_from_open_positions_csv](seed_filled_intents_from_open_positions_csv.md) (1 shared connections)
- [.create_live_engine](create_live_engine.md) (1 shared connections)
- [Legacy keys (read-only compatibility)](Legacy_keys_read-only_compatibility.md) (1 shared connections)
- [Order Logging Pipeline](Order_Logging_Pipeline.md) (1 shared connections)
- [OpenPositionsLogger](OpenPositionsLogger.md) (1 shared connections)

## Source Files

- `core/orderExecution/position_manager.py`
- `utils/logger/open_positions_logger.py`

## Audit Trail

- EXTRACTED: 57 (95%)
- INFERRED: 3 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*