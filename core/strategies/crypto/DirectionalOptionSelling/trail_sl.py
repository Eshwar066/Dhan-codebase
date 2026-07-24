"""Broker MAIN_SL trail helpers for DirectionalOptionSelling."""

from __future__ import annotations

import logging
import time as time_mod
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional

from run.config import RUN_MODE, RunMode

from .constants import (
    FORCE_EXIT_POINTS,
    SLEEVE_DAILY,
    TRAIL_SL_IMMEDIATE_RETRY_SLEEP_SEC,
    TRAIL_SL_MODIFY_ATTEMPTS,
    TRAIL_SL_PENDING_RETRY_GAP_SEC,
    TRAIL_SL_POINTS,
)

logger = logging.getLogger(__name__)


@dataclass
class PendingTrailRetry:
    """Queued when SuperTrend moved but broker MAIN_SL modify failed."""

    structure_id: str
    direction: int
    target_supertrend: float
    sleeve: str
    attempts: int = 0
    last_attempt_mono: float = 0.0


# Backward-compatible private alias used by the strategy module / tests.
_PendingTrailRetry = PendingTrailRetry


class DosTrailSlMixin:
    """ST±100 broker trail levels, modify, and pending retry queue."""

    @staticmethod
    def _trail_sl_level(
        direction: int,
        supertrend: float,
        *,
        strike: Optional[float] = None,
        option_type: Optional[str] = None,
    ) -> float:
        """Broker SL level. Bullish: ST - 100. Bearish: ST + 100.

        When strike is known, clamp so CE SL stays strictly below strike and
        PE SL stays strictly above strike (still prefer ST±100 when valid).

        Example (morning PE short): ST=64813.39, strike=64800 → ST-100=64713.39
        is invalid; clamp to strike+1 = 64801.
        """
        st = float(supertrend)
        if direction > 0:
            level = st - TRAIL_SL_POINTS
        else:
            level = st + TRAIL_SL_POINTS
        try:
            k = float(strike) if strike is not None else 0.0
        except (TypeError, ValueError):
            k = 0.0
        if k <= 0:
            return level
        ot = str(
            option_type or ("PE" if direction > 0 else "CE")
        ).strip().upper()
        if ot.startswith("C") and not ot.startswith("P"):
            # Short CE: index SL must stay strictly below strike.
            clamped = min(level, k - 1.0)
            if clamped >= k:
                clamped = k - 1.0
            return float(clamped)
        if ot.startswith("P"):
            # Short PE: index SL must stay strictly above strike.
            clamped = max(level, k + 1.0)
            if clamped <= k:
                clamped = k + 1.0
            return float(clamped)
        return level

    @staticmethod
    def _strike_from_trading_symbol(trading_symbol: Any) -> Optional[float]:
        """Parse strike from Delta symbols like ``P-BTC-64800-240726``."""
        import re

        sym = str(trading_symbol or "").strip().upper()
        if not sym:
            return None
        m = re.match(r"^[PC]-BTC-(\d+)-", sym)
        if not m:
            return None
        try:
            k = float(m.group(1))
        except (TypeError, ValueError):
            return None
        return k if k > 0 else None

    @staticmethod
    def _sl_strike_side_from_position(
        position: Any, meta: Any = None
    ) -> tuple[Optional[float], Optional[str]]:
        """Resolve (strike, option_type) for MAIN_SL clamp from meta/instrument."""
        strike: Optional[float] = None
        option_type: Optional[str] = None
        if meta is not None:
            try:
                k = float(getattr(meta, "strike", 0) or 0)
            except (TypeError, ValueError):
                k = 0.0
            if k > 0:
                strike = k
            ot = str(getattr(meta, "option_type", "") or "").strip().upper()
            if ot:
                option_type = ot
        inst = getattr(position, "instrument", None)
        if strike is None and inst is not None:
            try:
                k = float(getattr(inst, "strike", 0) or 0)
            except (TypeError, ValueError):
                k = 0.0
            if k > 0:
                strike = k
        if strike is None and inst is not None:
            strike = DosTrailSlMixin._strike_from_trading_symbol(
                getattr(inst, "trading_symbol", None)
            )
        if not option_type and inst is not None:
            ot = str(getattr(inst, "option_type", "") or "").strip().upper()
            if ot:
                option_type = ot
            else:
                sym = str(getattr(inst, "trading_symbol", "") or "").upper()
                if sym.startswith("P-") or ":PE:" in sym or "-PE-" in sym:
                    option_type = "PE"
                elif sym.startswith("C-") or ":CE:" in sym or "-CE-" in sym:
                    option_type = "CE"
        return strike, option_type

    @staticmethod
    def _force_exit_level(direction: int, supertrend: float) -> float:
        """Strategy emergency exit level. Bullish: ST - 300. Bearish: ST + 300."""
        st = float(supertrend)
        if direction > 0:
            return st - FORCE_EXIT_POINTS
        return st + FORCE_EXIT_POINTS

    def _find_main_sl_record(self, ctx: Any, structure_id: str) -> Optional[dict]:
        intent_store = getattr(ctx, "intent_store", None)
        if intent_store is None or not callable(
            getattr(intent_store, "list_by_status", None)
        ):
            return None
        from core.orderExecution.intent_store import IntentStatus

        pending = []
        for status in (
            IntentStatus.SENT,
            IntentStatus.ACKED,
            IntentStatus.VALIDATED,
        ):
            pending.extend(intent_store.list_by_status(status) or [])
        for rec in pending:
            payload = rec.get("payload") or {}
            if str(payload.get("structure_id") or rec.get("structure_id") or "") != str(
                structure_id
            ):
                continue
            if str(payload.get("tag") or rec.get("tag") or "").upper() != "MAIN_SL":
                continue
            if str(payload.get("strategy") or rec.get("strategy") or "") not in {
                "",
                self.name,
            }:
                if str(payload.get("strategy_id") or "") != self.name:
                    continue
            return rec
        return None

    def _modify_broker_trail_sl(
        self, ctx: Any, position: Any, *, direction: int, supertrend: float
    ) -> bool:
        """Update resting broker MAIN_SL stop_price to the latest SuperTrend trail level.

        Retries a few times immediately. Callers must treat False as stale SL and
        queue ``_pending_trail_retries`` so later candles/quotes keep trying.
        """
        sid = str(getattr(position, "structure_id", "") or "")
        meta = None
        if sid and hasattr(self, "_meta_by_structure_id"):
            meta = self._meta_by_structure_id.get(sid)
        if meta is None and callable(getattr(self, "_ensure_meta", None)):
            try:
                meta = self._ensure_meta(position, ctx)
            except Exception:
                meta = None
        strike, option_type = self._sl_strike_side_from_position(position, meta)
        level = self._trail_sl_level(
            direction,
            supertrend,
            strike=strike,
            option_type=option_type,
        )
        router = getattr(ctx, "order_router", None)
        broker = getattr(router, "broker", None) if router is not None else None
        if broker is None:
            logger.error(
                "%s TRAIL_SL_STALE broker missing sid=%s desired_sl=%.2f ST=%.2f",
                self.name,
                getattr(position, "structure_id", None),
                level,
                float(supertrend),
            )
            return False
        qty = abs(int(getattr(position, "net_qty", 0) or 0)) or 1
        inst = getattr(position, "instrument", None)
        trading_symbol = str(getattr(inst, "trading_symbol", "") or "")

        # Simulated / paper: update pending SL book directly when available.
        update_pending = getattr(broker, "update_pending_sl_trigger", None)
        if callable(update_pending) and sid:
            if update_pending(sid, level):
                logger.info(
                    "%s broker trail SL updated sid=%s level=%.2f (sim)",
                    self.name,
                    sid,
                    level,
                )
                return True

        order_id = None
        product_id = getattr(inst, "product_id", None) if inst is not None else None
        find_oid = getattr(broker, "find_bracket_leg_order_id", None)
        if callable(find_oid) and trading_symbol:
            order_id = find_oid(trading_symbol, "MAIN_SL")
        rec = self._find_main_sl_record(ctx, sid)
        if not order_id and rec is not None:
            order_id = rec.get("broker_order_id")
        if product_id is None and trading_symbol:
            api = getattr(broker, "api", None)
            pid_fn = (
                getattr(api, "product_id_for_symbol", None) if api is not None else None
            )
            if callable(pid_fn):
                product_id = pid_fn(trading_symbol)
        update_fn = getattr(broker, "update_order_stop_price", None)
        if not callable(update_fn) or not order_id or product_id is None:
            logger.error(
                "%s TRAIL_SL_STALE sid=%s order_id=%s product_id=%s "
                "desired_sl=%.2f ST=%.2f (missing broker update path) — will retry",
                self.name,
                sid,
                order_id,
                product_id,
                level,
                float(supertrend),
            )
            return False

        attempts = max(1, int(TRAIL_SL_MODIFY_ATTEMPTS))
        last_ok = False
        for attempt in range(1, attempts + 1):
            try:
                last_ok = bool(
                    update_fn(
                        product_id=int(product_id),
                        order_id=str(order_id),
                        new_stop_price=float(level),
                        size=int(qty),
                    )
                )
            except Exception as exc:
                last_ok = False
                logger.error(
                    "%s TRAIL_SL_MODIFY_ERROR sid=%s order=%s desired_sl=%.2f "
                    "ST=%.2f attempt=%s/%s err=%s",
                    self.name,
                    sid,
                    order_id,
                    level,
                    float(supertrend),
                    attempt,
                    attempts,
                    exc,
                )
            if last_ok:
                break
            logger.error(
                "%s TRAIL_SL_STALE sid=%s order=%s desired_sl=%.2f ST=%.2f "
                "attempt=%s/%s broker_modify_failed",
                self.name,
                sid,
                order_id,
                level,
                float(supertrend),
                attempt,
                attempts,
            )
            if attempt < attempts and RUN_MODE != RunMode.BACKTEST:
                time_mod.sleep(float(TRAIL_SL_IMMEDIATE_RETRY_SLEEP_SEC))

        if last_ok:
            logger.info(
                "%s broker trail SL updated sid=%s order=%s level=%.2f ST=%.2f",
                self.name,
                sid,
                order_id,
                level,
                float(supertrend),
            )
            if rec is not None:
                payload = rec.get("payload") or {}
                payload["trigger_price"] = float(level)
                payload["price"] = float(level)
                meta = dict(payload.get("strategy_meta") or {})
                meta["trail_sl_level"] = float(level)
                meta["supertrend"] = float(supertrend)
                payload["strategy_meta"] = meta
                rec["payload"] = payload
            return True

        logger.error(
            "%s TRAIL_SL_STALE FINAL sid=%s order=%s desired_sl=%.2f ST=%.2f "
            "after %s attempts — SL not moved; queued for retry",
            self.name,
            sid,
            order_id,
            level,
            float(supertrend),
            attempts,
        )
        return False

    def _queue_trail_sl_retry(
        self,
        *,
        structure_id: str,
        direction: int,
        target_supertrend: float,
        sleeve: str,
        prev_ref: Optional[float],
    ) -> None:
        sid = str(structure_id or "").strip()
        if not sid:
            return
        # Retry queue logging uses unclamped ST±100; broker modify re-resolves
        # strike from the open position when it runs.
        desired = self._trail_sl_level(int(direction), float(target_supertrend))
        stale = (
            self._trail_sl_level(int(direction), float(prev_ref))
            if prev_ref is not None
            else None
        )
        existing = self._pending_trail_retries.get(sid)
        attempts = int(existing.attempts) if existing is not None else 0
        self._pending_trail_retries[sid] = PendingTrailRetry(
            structure_id=sid,
            direction=int(direction),
            target_supertrend=float(target_supertrend),
            sleeve=str(sleeve or SLEEVE_DAILY),
            attempts=attempts,
            last_attempt_mono=time_mod.monotonic(),
        )
        logger.error(
            "%s TRAIL_SL_RETRY_QUEUED sid=%s sleeve=%s ST %.2f -> %.2f "
            "broker_sl %.2f -> %.2f (meta not advanced until modify succeeds)",
            self.name,
            sid,
            sleeve,
            float(prev_ref) if prev_ref is not None else float("nan"),
            float(target_supertrend),
            float(stale) if stale is not None else float("nan"),
            float(desired),
        )

    def _clear_trail_sl_retry(self, structure_id: Any) -> None:
        sid = str(structure_id or "").strip()
        if sid:
            self._pending_trail_retries.pop(sid, None)

    def _apply_trail_sl_update(
        self,
        ctx: Any,
        position: Any,
        *,
        direction: int,
        ref_st: float,
        sleeve: str,
        prev_ref: Optional[float],
    ) -> bool:
        """Modify broker SL to ``ref_st`` trail; update meta only on success."""
        sid = str(getattr(position, "structure_id", "") or "")
        updated = self._modify_broker_trail_sl(
            ctx,
            position,
            direction=int(direction),
            supertrend=float(ref_st),
        )
        meta = self._meta_by_structure_id.get(sid) if sid else None
        if updated:
            self._clear_trail_sl_retry(sid)
            if meta is not None and sid:
                self._meta_by_structure_id[sid] = replace(
                    meta, supertrend=float(ref_st)
                )
            return True
        self._queue_trail_sl_retry(
            structure_id=sid,
            direction=int(direction),
            target_supertrend=float(ref_st),
            sleeve=str(sleeve or SLEEVE_DAILY),
            prev_ref=float(prev_ref) if prev_ref is not None else None,
        )
        return False

    def _retry_pending_trail_sl(self, ctx: Any) -> None:
        """Re-attempt broker trail modifies that failed after an ST move."""
        if not self._pending_trail_retries:
            return
        now = time_mod.monotonic()
        gap = float(TRAIL_SL_PENDING_RETRY_GAP_SEC)
        open_by_sid = {
            str(getattr(p, "structure_id", "") or ""): p
            for p in self._open_main_positions(ctx)
        }
        for sid, pending in list(self._pending_trail_retries.items()):
            position = open_by_sid.get(sid)
            if position is None or sid in self._pending_exit_structure_ids:
                self._clear_trail_sl_retry(sid)
                continue
            if (now - float(pending.last_attempt_mono or 0.0)) < gap:
                continue
            meta = self._ensure_meta(position, ctx)
            prev_ref = float(meta.supertrend) if meta is not None else None
            target = float(pending.target_supertrend)
            if prev_ref is not None and abs(target - prev_ref) <= 1e-9:
                # Meta already matches target (e.g. restored); still push broker.
                pass
            pending.attempts = int(pending.attempts or 0) + 1
            pending.last_attempt_mono = now
            logger.error(
                "%s TRAIL_SL_RETRY sid=%s sleeve=%s attempt=%s desired_ST=%.2f "
                "desired_sl=%.2f meta_ST=%s",
                self.name,
                sid,
                pending.sleeve,
                pending.attempts,
                target,
                self._trail_sl_level(int(pending.direction), target),
                f"{prev_ref:.2f}" if prev_ref is not None else "None",
            )
            self._apply_trail_sl_update(
                ctx,
                position,
                direction=int(pending.direction),
                ref_st=target,
                sleeve=str(pending.sleeve or SLEEVE_DAILY),
                prev_ref=prev_ref,
            )
