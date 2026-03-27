"""
RiskManager: per-engine limits, kill switch, capital-based exposure.
Exits always allowed; entries blocked when limits or kill switch triggered.
Option shorting: optional check_short_option_margin(intent, price_map) validates
SPAN and exposure margin before allowing short option entries. Wire via
make_short_option_margin_check(broker) when broker implements check_short_option_margin.
"""

import logging
import time
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def make_short_option_margin_check(
    broker: Any,
) -> Optional[Callable[[Any, Dict], bool]]:
    """
    Return a callable (intent, price_map) -> bool for SPAN + exposure margin validation,
    or None if broker does not support it. Brokers (e.g. Dhan) can implement
    check_short_option_margin(intent, price_map) using margin_calculator / fund limits.
    """
    if broker is None:
        return None
    fn = getattr(broker, "check_short_option_margin", None)
    if callable(fn):
        return lambda intent, price_map: fn(intent, price_map)
    return None


class RiskManager:
    def __init__(
        self,
        position_manager,
        max_portfolio_exposure: float = 10000000,
        max_symbol_exposure: float = 9000000,
        max_qty_per_symbol: int = 10000,
        max_open_positions: int = 20,
        cooldown_seconds: int = 5,
        daily_max_loss: Optional[float] = None,
        capital: Optional[float] = None,
        risk_per_trade_percent: Optional[float] = None,
        engine_logger: Optional[Any] = None,
        check_short_option_margin: Optional[
            Callable[[Any, Dict[str, float]], bool]
        ] = None,
    ):
        self.pm = position_manager
        self.engine_logger = engine_logger
        # Option shorting: callable(intent, price_map) -> True if SPAN + exposure margin OK
        self.check_short_option_margin = check_short_option_margin

        # Limits
        self.max_portfolio_exposure = max_portfolio_exposure
        self.max_symbol_exposure = max_symbol_exposure
        self.max_qty_per_symbol = max_qty_per_symbol
        self.max_open_positions = max_open_positions
        self.daily_max_loss = daily_max_loss
        self.capital = capital
        self.risk_per_trade_percent = risk_per_trade_percent or 0.0
        self.max_risk_amount: Optional[float] = None
        if capital is not None and risk_per_trade_percent is not None:
            self.max_risk_amount = capital * (risk_per_trade_percent / 100.0)

        # Max total exposure (alias; use max_portfolio_exposure)
        self.max_total_exposure = max_portfolio_exposure

        # Kill switch
        self._kill_switch_blocked = False
        self._kill_switch_reason: Optional[str] = None

        # Daily PnL (for daily_max_loss)
        self.daily_realized_pnl = 0.0

        # Anti-overtrading
        self.cooldown_seconds = cooldown_seconds
        self.last_trade_time = {}

        # execution_source -> counts per strategy (EXTERNAL_CLOSE, LIQUIDATION, ADL, INTENT, …)
        self.execution_source_counts: Dict[str, Counter] = defaultdict(Counter)

    def is_engine_blocked(self) -> bool:
        """True if kill switch is triggered. Block new entries; exits still allowed."""
        return self._kill_switch_blocked

    def trigger_kill_switch(self, reason: str) -> None:
        """Block all new entry intents. Log critical event. Exits remain allowed."""
        self._kill_switch_blocked = True
        self._kill_switch_reason = reason
        if self.engine_logger:
            self.engine_logger.kill_switch(reason)
        else:
            logger.critical("Kill switch: %s", reason)

    def record_realized_pnl(self, amount: float) -> None:
        """Call when a position is closed and PnL is realized (e.g. from PositionManager)."""
        self.daily_realized_pnl += amount

    def record_execution_source(
        self,
        execution_source: Optional[str],
        strategy: Optional[str] = None,
        *,
        symbol: Optional[str] = None,
        position_closed: bool = False,
    ) -> None:
        """
        Aggregate exits by source for risk analytics (liquidation rate, forced vs planned, etc.).
        """
        if not execution_source:
            return
        key = strategy or "GLOBAL"
        self.execution_source_counts[key][str(execution_source)] += 1
        _ = symbol
        _ = position_closed

    def reset_daily(self) -> None:
        """Reset daily PnL (call at start of new trading day)."""
        self.daily_realized_pnl = 0.0

    def _log_block(self, msg: str, symbol: Optional[str] = None) -> None:
        if self.engine_logger:
            self.engine_logger.risk_block(msg, symbol=symbol)
        else:
            logger.warning("Risk block: %s (symbol=%s)", msg, symbol)

    # -------------------------
    # MAIN CHECK
    # -------------------------
    def allow_intent(self, intent, price_map, candle_ts=None):
        """
        intent: OrderIntent object
        Exit/force exit always allowed. Entry blocked if kill switch or limits breached.
        """
        action = getattr(intent, "action", "ENTRY")
        if action in ("EXIT", "FORCE_EXIT"):
            return True

        if self._kill_switch_blocked:
            self._log_block("Entry blocked: kill switch active")
            return False

        symbol = intent.instrument.trading_symbol
        side = intent.side
        qty = intent.qty
        price = intent.price or 0
        lot_size = intent.instrument.lot_size
        strategy = getattr(intent, "strategy", None)
        structure_id = getattr(intent, "structure_id", None)
        tag = getattr(intent, "tag", None)
        if action is None:
            raise ValueError(
                f"Intent {intent.intent_id} missing action " f"(ENTRY / EXIT / ROLL)"
            )

        # 0️⃣ STRUCTURE LOCK
        if strategy and structure_id and action == "ENTRY" and tag == "MAIN":
            if self.pm.has_open_structure(
                structure_id=structure_id,
                tag="MAIN",
                strategy=strategy,
            ):
                self._log_block(f"Structure already open {strategy} | {structure_id}")
                return False

        # 1️⃣ Daily loss limit
        if (
            self.daily_max_loss is not None
            and self.daily_realized_pnl <= -self.daily_max_loss
        ):
            self._log_block("Daily max loss reached")
            return False

        # 2️⃣ Cooldown check
        now_ts = self._get_event_time(candle_ts)
        if not self._cooldown_ok(symbol, now_ts):
            self._log_block("Cooldown active", symbol=symbol)
            return False

        # 3️⃣ Position count limit
        open_count = self._open_positions_count()
        if open_count >= self.max_open_positions:
            if self.engine_logger:
                self.engine_logger.max_positions_blocked(
                    current_count=open_count, max_allowed=self.max_open_positions
                )
            self._log_block("Max open positions reached")
            return False

        # 4️⃣ Per-symbol qty limit ==> tested ✅
        future_qty = abs(self.pm.get_qty(symbol)) + qty
        if future_qty > self.max_qty_per_symbol:
            self._log_block("Qty limit breach", symbol=symbol)
            return False

        # 5️⃣ No double-direction entries
        if not self._direction_ok(intent.instrument, side):
            self._log_block("Opposite position exists", symbol=symbol)
            return False

        # 5b️⃣ Option shorting: validate SPAN + exposure margin before sending
        if self._is_short_option(intent) and self.check_short_option_margin is not None:
            try:
                if not self.check_short_option_margin(intent, price_map):
                    self._log_block(
                        "Insufficient margin (SPAN/exposure) for short option",
                        symbol=symbol,
                    )
                    return False
            except Exception as e:
                self._log_block(
                    f"Short option margin check failed: {e}",
                    symbol=symbol,
                )
                return False

        multiplier = getattr(intent.instrument, "contract_multiplier", 1)
        trade_exposure = abs(qty) * price * multiplier

        # 6️⃣ Per-trade risk (capital bucket)
        if self.max_risk_amount is not None and trade_exposure > self.max_risk_amount:
            self._log_block(
                f"Trade exposure {trade_exposure} exceeds max_risk_amount {self.max_risk_amount}",
                symbol=symbol,
            )
            return False

        # 7️⃣ Symbol exposure check
        sym_exposure = future_qty * price * multiplier
        if sym_exposure > self.max_symbol_exposure:
            self._log_block(f"Symbol exposure breach {sym_exposure}", symbol=symbol)
            return False

        # 8️⃣ 🔶🔶 Portfolio exposure check ==> checked when there are open positions in singal or multiple strategies
        portfolio_exposure = self.pm.total_exposure(price_map)
        new_exposure = portfolio_exposure + (qty * price * multiplier)
        if new_exposure > self.max_portfolio_exposure:
            self._log_block("Portfolio exposure breach")
            return False

        key = (
            getattr(intent, "strategy", None),
            getattr(intent, "structure_id", None),
            intent.instrument.contract_key,
        )
        self.last_trade_time[key] = now_ts
        return True

    # -------------------------
    # HELPERS
    # -------------------------
    def _is_short_option(self, intent) -> bool:
        """True if intent is ENTRY + SELL on an option (short option)."""
        action = getattr(intent, "action", "ENTRY")
        side = getattr(intent, "side", "")
        if action != "ENTRY" or (str(side).upper() != "SELL"):
            return False
        inst = getattr(intent, "instrument", None)
        if inst is None:
            return False
        itype = (getattr(inst, "instrument_type", None) or "").upper()
        otype = getattr(inst, "option_type", None)
        return itype in ("OP", "OPT", "OPTION") or otype in ("CE", "PE", "CALL", "PUT")

    def _direction_ok(self, instrument, side):
        for pos in self.pm.get_open_positions():
            if pos.instrument.contract_key != instrument.contract_key:
                continue
            if side == "BUY" and pos.net_qty < 0:
                return False
            if side == "SELL" and pos.net_qty > 0:
                return False
        return True

    def _open_positions_count(self):
        return sum(1 for p in self.pm.positions.values() if p.net_qty != 0)

    def _get_event_time(self, candle_ts):
        if candle_ts is None:
            return time.time()
        return candle_ts.timestamp()

    def _cooldown_ok(self, symbol, now_ts):
        last = self.last_trade_time.get(symbol, 0)
        return (now_ts - last) >= self.cooldown_seconds
