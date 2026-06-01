from datetime import datetime
from typing import Any, Dict

from core.data.data_router import DataRouter
from core.utils.lag_diag import print_data_check
from core.data.option_chain_service import OptionChainService
from core.models.strategy_context import StrategyContext
from core.strategies.runtime_spec import STRATEGY_RUNTIME_SPEC
from run.config import RUN_MODE, RunMode


class BaseEngine:

    def __init__(
        self,
        strategy,
        data,
        instrument_store,
        position_manager,
        universe_service=None,
    ):
        self.strategy = strategy
        self.data = data
        self.instrument_store = instrument_store
        self.position_manager = position_manager
        self.universe_service = universe_service
        self.data_router = DataRouter(data)
        self.option_chain_service = OptionChainService(self.data_router)

    def get_strategy_params(self):
        return STRATEGY_RUNTIME_SPEC[self.strategy.name][RUN_MODE]

    def build_context(self, candle, recent_candles=None, intent_store=None):
        ts = candle["timestamp"]
        if not isinstance(ts, datetime):
            ts = datetime.fromisoformat(str(ts))

        ctx = StrategyContext(
            symbol=candle["symbol"],
            exchange=candle.get("exchange"),
            timestamp=ts,
            spot_price=float(candle["close"]),
            instrument_store=self.instrument_store,
            position_store=self.position_manager,
            option_chain_service=self.option_chain_service,
            universe_service=getattr(self, "universe_service", None),
            recent_candles=recent_candles,
            intent_store=intent_store,
        )

        # Lag diagnosis: data delay before strategy (set ALGO_LAG_DIAG=1). See cursor.md
        print_data_check(candle)

        intent = self.strategy.on_candle(candle, ctx)
        return ctx, intent

    def build_context_only(
        self, candle, recent_candles=None, intent_store=None
    ) -> "StrategyContext":
        """StrategyContext without calling ``on_candle`` (for fill-time hooks)."""
        ts = candle["timestamp"]
        if not isinstance(ts, datetime):
            ts = datetime.fromisoformat(str(ts))
        if intent_store is None and hasattr(self, "order_router"):
            intent_store = getattr(self.order_router, "intent_store", None)
        return StrategyContext(
            symbol=candle["symbol"],
            exchange=candle.get("exchange"),
            timestamp=ts,
            spot_price=float(candle.get("close", 0) or 0),
            instrument_store=self.instrument_store,
            position_store=self.position_manager,
            option_chain_service=self.option_chain_service,
            universe_service=getattr(self, "universe_service", None),
            recent_candles=recent_candles,
            intent_store=intent_store,
        )

    def evaluate_sim_broker_stops(self, candle: Dict[str, Any], ctx: Any) -> None:
        """SimulatedBroker: fire resting MAIN_SL when option LTP crosses trigger (backtest/paper)."""
        router = getattr(self, "order_router", None)
        if router is None:
            return
        br = getattr(router, "broker", None)
        if br is None or not hasattr(br, "evaluate_pending_stops"):
            return
        price_map: Dict[str, float] = {}
        for sym, pos in self.position_manager.positions.items():
            if pos.net_qty == 0:
                continue
            if getattr(pos, "tag", None) != "MAIN":
                continue
            if getattr(pos, "strategy", None) != self.strategy.name:
                continue
            inst = pos.instrument
            ts = getattr(inst, "trading_symbol", None)
            if not ts:
                continue
            strike = getattr(inst, "strike", None)
            option_type = getattr(inst, "option_type", None)
            if not self.strategy._is_option_instrument(strike, option_type):
                px = float(candle.get("close", 0) or 0)
            else:
                px = self.strategy.get_option_price_at_candle(
                    candle,
                    ctx,
                    strike,
                    option_type,
                    inst.expiry,
                    trading_symbol=ts,
                )
                if px is None:
                    px = float(candle.get("close", 0) or 0)
            price_map[ts] = float(px)
        if not price_map:
            return
        br.evaluate_pending_stops(
            router,
            price_map,
            candle.get("timestamp"),
        )
