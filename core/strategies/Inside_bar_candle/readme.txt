Inside Bar – Strategy module
============================
Implementation: inside_bar.py, historical_dhan.py (as needed)
Registry:       core/strategies/registry.STRATEGY_MAP (if registered)

Engine flow (current codebase):
- BacktestEngine fetches intraday data from data_provider (IDataProvider).
- base_engine.build_context(candle) returns StrategyContext (typed) and intent from strategy.on_candle(candle, ctx).
- strategy.on_candle(candle, ctx: StrategyContext) returns OrderIntent(s) or None.
- Exits: strategy.should_exit(position, candle, ctx); strategy.on_position_exit(position, candle, ctx) returns exit intents.
- OrderRouter.process_intent(intent, price_map) → RiskManager → Broker → PositionManager.

Use ctx.position_store, ctx.option_chain_service, ctx.instrument_store (StrategyContext attributes), not ctx["key"].
