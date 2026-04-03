from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from core.models.strategy_context import StrategyContext


class BaseStrategy:
    name = ""
    required_context = []

    def prepare_indicators(self, df: Any) -> Any:
        return df

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
