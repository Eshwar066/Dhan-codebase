# Runtime notes

> 5 nodes

## Key Concepts

- **Runtime notes** (8 connections) — `docs/runtime_flow.md`
- **.get_intraday()** (4 connections) — `core/data/datalayer/base.py`
- **Live Runtime Flow** (3 connections) — `docs/runtime_flow.md`
- **DataFrame** (1 connections)
- **Historical intraday candles for backtest.** (1 connections) — `core/data/datalayer/base.py`

## Relationships

- [IDataProvider](IDataProvider.md) (1 shared connections)
- [docs/README.md](docs-README.md.md) (1 shared connections)
- [EngineConfig](EngineConfig.md) (1 shared connections)
- [CandleAggregator](CandleAggregator.md) (1 shared connections)
- [DeltaWebSocketFeed](DeltaWebSocketFeed.md) (1 shared connections)
- [DhanWebSocketFeed](DhanWebSocketFeed.md) (1 shared connections)
- [GttFallbackBook](GttFallbackBook.md) (1 shared connections)
- [IndicatorManager](IndicatorManager.md) (1 shared connections)
- [ExitRolloverService](ExitRolloverService.md) (1 shared connections)

## Source Files

- `core/data/datalayer/base.py`
- `docs/runtime_flow.md`

## Audit Trail

- EXTRACTED: 6 (46%)
- INFERRED: 7 (54%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*