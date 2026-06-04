from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext


class BaseStrategy:
    name = ""
    required_context = []

    def prepare_indicators(self, df: Any) -> Any:
        return df

    def persisted_indicator_keys(self) -> List[str]:
        """
        Indicator columns to append to shared ``logs/indicators/{symbol}/{tf}/indicator_history.jsonl``.
        Override per strategy (RSI, EMA, Bollinger, etc.).
        """
        return []

    def requires_live_rsi_patch(self) -> bool:
        """Legacy opt-in for RSI merge on live bars; prefer ``persisted_indicator_keys``."""
        return False

    def on_candle(self, candle: Any, ctx: "StrategyContext") -> Any:
        raise NotImplementedError

    def should_exit(
        self, position: Any, candle: Any, ctx: Optional["StrategyContext"] = None
    ) -> bool:
        return False

    def get_warmup_period(self):
        return 0

    def on_forced_exit(self, **kwargs: Any) -> None:
        """Optional: broker-driven close (liquidation, orphan fill, etc.). Override to sync strategy state."""
        return None
