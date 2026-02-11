core/ – Algo trading core
========================

Current layout (matches this codebase):

core/
├── data/
│   ├── datalayer/           IDataProvider, DhanDataProvider – data feed for engines
│   ├── sources/             DhanSource (Dhan API via library), NSEClient
│   ├── adapters/             NSEAdapter, DhanAdapter – option chain per API
│   ├── data_router.py        Picks adapter by api (NSE/DHAN)
│   ├── option_chain_service.py  get_expiries, get_chain (uses StrategyContext)
│   └── candle_service.py    Latest closed candle for live
├── engine/
│   ├── base_engine.py        build_context() → StrategyContext, strategy.on_candle
│   ├── backtest_engine.py    Candle loop, exits, rollover, entry
│   └── live_engine.py       Live/paper loop
├── library/
│   └── dhan_tradehull.py    In-project Dhan Tradehull (OHLC, option chain, orders)
├── models/
│   ├── order_intent.py      OrderIntent dataclass
│   └── strategy_context.py StrategyContext dataclass (typed ctx for strategies)
├── broker/                   Order placement only (see broker/README.md)
│   ├── broker_api.py        IBrokerApi
│   ├── dhan_broker_api.py, dhanbroker.py
│   ├── delta_broker_api.py, delta_broker.py
│   └── simulated_broker.py
├── orderExecution/           Intent → risk → broker → PositionManager (see orderExecution/README.md)
│   ├── order_router.py
│   ├── risk_manager.py, intent_store.py, position_manager.py
│   ├── order_state.py, slippage.py
├── strategies/
│   ├── base.py              BaseStrategy (on_candle(candle, ctx: StrategyContext))
│   ├── IndiaMktMixins.py    Shared option/hedge/rollover logic for India strategies
│   ├── registry.py          STRATEGY_MAP
│   ├── runtime_spec.py      STRATEGY_RUNTIME_SPEC
│   ├── Leaps/               LeapsQuatery_RSI_52_32, readme
│   └── Inside_bar_candle/   inside_bar, historical_dhan, readme
├── utils/
│   ├── expiry_resolver.py   Expiry resolution (NSE/Dhan, monthly/quarterly)
│   ├── instruments/         instrument_store.py, README
│   └── session/            holidays, market_calendar, session_manager
└── instruments.py           (legacy/convenience if used)

Data flow:  IDataProvider → Engine → Strategy.on_candle(candle, StrategyContext) → OrderIntent
Order flow: OrderRouter.process_intent(intent) → RiskManager → Broker.place_order() → PositionManager
