# TradeLogger

> 16 nodes

## Key Concepts

- **TradeLogger** (18 connections) — `utils/logger/trade_logger.py`
- **.log_trade()** (6 connections) — `utils/logger/trade_logger.py`
- **Common Issues** (6 connections) — `docs/ORDER_LOGGING_PIPELINE.md`
- **._ensure_schema_or_rotate()** (5 connections) — `utils/logger/trade_logger.py`
- **.log()** (5 connections) — `utils/logger/trade_logger.py`
- **.__init__()** (3 connections) — `core/orderExecution/position_manager.py`
- **._get_lock()** (3 connections) — `utils/logger/trade_logger.py`
- **._get_per_strategy_trade_log_file()** (3 connections) — `utils/logger/trade_logger.py`
- **._get_file()** (2 connections) — `utils/logger/trade_logger.py`
- **._get_trade_log_file()** (2 connections) — `utils/logger/trade_logger.py`
- **._header_matches()** (2 connections) — `utils/logger/trade_logger.py`
- **.__init__()** (1 connections) — `utils/logger/trade_logger.py`
- **Log a completed trade (round-trip) for performance analytics. trade_row must…** (1 connections) — `utils/logger/trade_logger.py`
- **Per-strategy trade-summary file (same schema as aggregate trade_log.csv).** (1 connections) — `utils/logger/trade_logger.py`
- **If an existing file has a stale/misaligned header, drop it and start fresh. No…** (1 connections) — `utils/logger/trade_logger.py`
- **Append one per-fill row using a fixed ``TRADES_COLUMNS`` schema.** (1 connections) — `utils/logger/trade_logger.py`

## Relationships

- [.create_live_engine](create_live_engine.md) (3 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [PositionManager](PositionManager.md) (2 shared connections)
- [._set_order_state](_set_order_state.md) (2 shared connections)
- [RunMode](RunMode.md) (1 shared connections)
- [Order Logging Pipeline](Order_Logging_Pipeline.md) (1 shared connections)
- [IndiaMktMixins](IndiaMktMixins.md) (1 shared connections)

## Source Files

- `core/orderExecution/position_manager.py`
- `docs/ORDER_LOGGING_PIPELINE.md`
- `utils/logger/trade_logger.py`

## Audit Trail

- EXTRACTED: 29 (81%)
- INFERRED: 7 (19%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*