# SignalFloodTestStrategy

> 14 nodes

## Key Concepts

- **SignalFloodTestStrategy** (13 connections) — `core/strategies/PipelineTest/signal_flood_test.py`
- **.on_candle()** (4 connections) — `core/strategies/PipelineTest/signal_flood_test.py`
- **._exchange_from_store()** (3 connections) — `core/strategies/PipelineTest/signal_flood_test.py`
- **.__init__()** (3 connections) — `core/strategies/PipelineTest/signal_flood_test.py`
- **.on_position_exit()** (3 connections) — `core/strategies/PipelineTest/signal_flood_test.py`
- **.should_exit()** (3 connections) — `core/strategies/PipelineTest/signal_flood_test.py`
- **Any** (3 connections)
- **.should_evaluate()** (2 connections) — `core/strategies/PipelineTest/signal_flood_test.py`
- **Exit after one candle (always exit when in position for this test).** (1 connections) — `core/strategies/PipelineTest/signal_flood_test.py`
- **Build exit intent from position.** (1 connections) — `core/strategies/PipelineTest/signal_flood_test.py`
- **Test strategy: signal every 1m, alternate BUY/SELL, force exits, optional…** (1 connections) — `core/strategies/PipelineTest/signal_flood_test.py`
- **Infer exchange (DELTA or NSE) from instrument store type.** (1 connections) — `core/strategies/PipelineTest/signal_flood_test.py`
- **Evaluate on every closed 1m candle.** (1 connections) — `core/strategies/PipelineTest/signal_flood_test.py`
- **Alternate BUY/SELL when flat; return exit handled by should_exit +…** (1 connections) — `core/strategies/PipelineTest/signal_flood_test.py`

## Relationships

- [typing](typing.md) (3 shared connections)
- [IndiaMktMixins](IndiaMktMixins.md) (1 shared connections)
- [Strategy index](Strategy_index.md) (1 shared connections)
- [Registered strategies](Registered_strategies.md) (1 shared connections)

## Source Files

- `core/strategies/PipelineTest/signal_flood_test.py`

## Audit Trail

- EXTRACTED: 21 (91%)
- INFERRED: 2 (9%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*