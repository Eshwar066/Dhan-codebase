core/ – Algo trading core
========================

core/
├── data/
│   ├── datalayer/           IDataProvider, DhanDataProvider, DeltaDataProvider
│   ├── sources/             DhanSource, NSEClient, delta_source
│   ├── adapters/            NSEAdapter, DhanAdapter
│   ├── feeds/               DhanWebSocketFeed, DeltaWebSocketFeed, DhanDepthFeed
│   ├── candle_aggregator.py Closed-bar builder from ticks
│   ├── option_chain_service.py
│   └── candle_service.py
├── engine/
│   ├── base_engine.py       StrategyContext, build_context
│   ├── backtest_engine.py   Historical loop; exits+rollover every bar
│   ├── live_engine.py       Feed loop, scheduled eval, GttFallbackBook tick
│   ├── live_engine_common.py Depth pricing, spread checks
│   ├── execution_engine.py  Intent queue workers, OMS fanout
│   └── factory.py           EngineFactory per job
├── models/
│   ├── order_intent.py
│   └── strategy_context.py
├── broker/                  See broker/README.md
├── orderExecution/          See orderExecution/README.md
│   ├── order_router.py
│   ├── gtt_fallback_book.py HYBRID_GTT watch + fallback
│   ├── bracket_orders.py
│   ├── risk_manager.py, intent_store.py, position_manager.py
├── strategies/
│   ├── base.py              BaseStrategy hooks
│   ├── IndiaMktMixins.py    India options: chain, hedge, rollover
│   ├── registry.py          STRATEGY_MAP
│   ├── runtime_spec.py      Per-mode data feeds
│   ├── Leaps/               LEAPS_RSI
│   ├── BTST/                BankNiftyBTST
│   ├── OpenIntrest/         OIPositionalBuy
│   ├── Futures/             FuturesEMAHighLow, Futures_EMA_Momentum
│   ├── Equity/              IPOBreakout (IPOAnchorVWAP)
│   ├── MagicalLines/        NiftyIntradayMagicalLine, MagicalLines (+ readme.md)
│   └── crypto/              RSIBreadAndButter (+ readme.md), oneDayMagicalLine
├── utils/
│   ├── expiry_resolver.py   MONTHLY, QUARTERLY, LEAPS_ROLL, WEEKLY
│   ├── indicator_history.py
│   ├── instruments/
│   └── session/
└── analytics/

Data flow:  Feed/IDataProvider → Engine → Strategy.on_candle → OrderIntent
Order flow: Intent queue → OrderRouter → Broker → fills → PositionManager

See docs/EVENT_DRIVEN_STRATEGY_GUIDE.md for adding new strategies.
