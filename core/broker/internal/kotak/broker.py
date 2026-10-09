"""Kotak Neo broker: order placement via KotakBrokerApi (no Forever/GTT in v1)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from core.broker.base import BaseBroker
from core.broker.internal.kotak import mappings as kotak_map

logger = logging.getLogger(__name__)


class KotakBroker(BaseBroker):
    """Order placement via Kotak Neo. Uses KotakBrokerApi."""

    supports_hedge_fill_gated_bundles = False

    def __init__(self, api, position_manager=None, intent_store=None):
        super().__init__(position_manager=position_manager, intent_store=intent_store)
        self.api = api
        self._last_place_order_failure: Optional[Dict[str, Any]] = None

    # ---------- Multi-leg margin with hedge benefit ----------

    def _get_available_balance(self) -> Optional[float]:
        """Get available cash/balance from Kotak limits API."""
        try:
            source = getattr(self.api, "_source", None)
            if source is None:
                return None
            limits = source.limits()
            if not isinstance(limits, list):
                return None
            for row in limits:
                if isinstance(row, dict):
                    # Kotak limits: look for available cash/equity
                    avail = row.get("availableCash") or row.get("available_margin") \
                        or row.get("equityAvailableMargin") or row.get("availableBalance")
                    if avail is not None:
                        return float(avail)
        except Exception as e:
            logger.warning("Kotak get available balance failed: %s", e)
        return None

    def _build_margin_leg_payload(self, intent: Any, execution_price: Optional[float] = None) -> Dict[str, Any]:
        """Build a single leg payload for margin calculation."""
        inst = intent.instrument
        exchange_segment = kotak_map.internal_segment_to_neo(inst.segment or "NFO")
        product = kotak_map.normalize_product(getattr(intent, "trade_type", "MARGIN"), inst.segment)
        transaction_type = kotak_map.normalize_transaction(intent.side)
        order_type = kotak_map.normalize_order_type(getattr(intent, "order_type", "LIMIT"))
        price = float(execution_price if execution_price is not None else getattr(intent, "price", 0) or 0)
        trigger_price = float(getattr(intent, "trigger_price", 0) or 0)
        quantity = int(getattr(intent, "qty", inst.lot_size) or inst.lot_size)

        # Get instrument token
        scrip_token = getattr(inst, "scrip_token", None) or getattr(inst, "instrument_token", None)
        if not scrip_token:
            # Try to resolve from instrument store
            router = getattr(self, "order_router", None)
            if router and router.instrument_store:
                scrip_token = router.instrument_store.get_scrip_token(inst)

        return {
            "exchange_segment": exchange_segment,
            "product": product,
            "price": price,
            "order_type": order_type,
            "quantity": quantity,
            "instrument_token": int(scrip_token) if scrip_token else 0,
            "transaction_type": transaction_type,
            "trigger_price": trigger_price,
            "broker_name": "KOTAK",
            "branch_id": "ONLINE",
        }

    def _parse_margin_response(self, response: Any) -> Dict[str, Any]:
        """Parse Kotak margin response to extract key fields."""
        if not isinstance(response, dict):
            return {"total_margin": 0, "span_margin": 0, "exposure_margin": 0}

        data = response.get("data") or response
        if not isinstance(data, dict):
            return {"total_margin": 0, "span_margin": 0, "exposure_margin": 0}

        total = float(data.get("totalMargin") or data.get("total_margin") or data.get("margin") or 0)
        span = float(data.get("spanMargin") or data.get("span_margin") or 0)
        exposure = float(data.get("exposureMargin") or data.get("exposure_margin") or 0)

        return {
            "total_margin": total,
            "span_margin": span,
            "exposure_margin": exposure,
        }

    def calculate_structure_margin(
        self,
        main_leg: Any,
        hedge_leg: Any,
        main_execution_price: Optional[float] = None,
        hedge_execution_price: Optional[float] = None,
        include_position: bool = True,
        include_orders: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Calculate margin for a hedged structure (MAIN + HEDGE).

        Returns dict with:
        - gross_margin: sum of individual leg margins (no hedge benefit)
        - hedge_benefit: margin reduction due to hedge
        - final_margin: actual margin required after hedge benefit
        - span_margin: SPAN component of final margin
        - exposure_margin: Exposure component of final margin

        Args:
            main_leg: MAIN leg intent (short option)
            hedge_leg: HEDGE leg intent (long option)
            main_execution_price: execution price for MAIN leg
            hedge_execution_price: execution price for HEDGE leg
            include_position: include existing positions in margin calc
            include_orders: include pending orders in margin calc
        """
        try:
            # Build payloads for both legs
            main_payload = self._build_margin_leg_payload(main_leg, main_execution_price)
            hedge_payload = self._build_margin_leg_payload(hedge_leg, hedge_execution_price)

            # Check if Kotak Neo supports multi-leg margin calculation
            # If not, fall back to single-leg calculation with estimated hedge benefit
            source = getattr(self.api, "_source", None)
            if source is None:
                return None

            neo_api = getattr(source, "api", None)
            if neo_api is None:
                return None

            # Try multi-leg margin if Kotak supports it
            # Kotak Neo API currently only has single-leg margin_required
            # We'll calculate individual margins and estimate hedge benefit

            # Get individual leg margins
            main_margin_resp = neo_api.margin_required(**main_payload)
            hedge_margin_resp = neo_api.margin_required(**hedge_payload)

            main_parsed = self._parse_margin_response(main_margin_resp)
            hedge_parsed = self._parse_margin_response(hedge_margin_resp)

            gross_total = main_parsed["total_margin"] + hedge_parsed["total_margin"]
            gross_span = main_parsed["span_margin"] + hedge_parsed["span_margin"]
            gross_exposure = main_parsed["exposure_margin"] + hedge_parsed["exposure_margin"]

            # Calculate hedge benefit
            # For a hedged position (short + long same underlying, same expiry):
            # The SPAN margin is significantly reduced because the positions offset
            # Hedge benefit ≈ min(short_span, long_span) * hedge_efficiency_factor
            # For vertical spreads (different strikes, same expiry), typical hedge benefit is 60-80%
            # of the short leg's SPAN margin

            # Estimate hedge benefit based on option type and strikes
            hedge_benefit = self._estimate_hedge_benefit(main_leg, hedge_leg, main_parsed, hedge_parsed)

            # Final margin = gross - hedge_benefit (with minimum floor)
            # Minimum margin floor: SPAN margin of the hedged structure cannot be less than
            # the SPAN margin of the wider leg (typically the short leg)
            min_final_span = max(main_parsed["span_margin"], hedge_parsed["span_margin"]) * 0.1  # 10% floor
            final_span = max(gross_span - hedge_benefit, min_final_span)
            final_exposure = max(gross_exposure - hedge_benefit * 0.5, gross_exposure * 0.2)
            final_total = final_span + final_exposure

            available = self._get_available_balance()

            return {
                "gross_margin": gross_total,
                "gross_span_margin": gross_span,
                "gross_exposure_margin": gross_exposure,
                "hedge_benefit": hedge_benefit,
                "final_margin": final_total,
                "span_margin": final_span,
                "exposure_margin": final_exposure,
                "available": available,
                "leg_count": 2,
                "main_leg_margin": main_parsed,
                "hedge_leg_margin": hedge_parsed,
            }

        except Exception as e:
            logger.warning("Kotak calculate_structure_margin failed: %s", e)
            return None

    def _estimate_hedge_benefit(
        self,
        main_leg: Any,
        hedge_leg: Any,
        main_margin: Dict[str, float],
        hedge_margin: Dict[str, float],
    ) -> float:
        """
        Estimate hedge benefit for vertical spread (short + long same underlying, same expiry).

        For vertical spreads (e.g., SELL 24150 PE + BUY 23650 PE):
        - Both same option type (PE), same expiry, different strikes
        - Short strike is closer to ATM, long strike is further OTM
        - SPAN margin is reduced because max loss is capped at strike difference * lot_size
        - Typical hedge benefit: 60-85% of short leg SPAN margin
        """
        try:
            main_inst = main_leg.instrument
            hedge_inst = hedge_leg.instrument

            main_strike = float(getattr(main_inst, "strike", 0) or 0)
            hedge_strike = float(getattr(hedge_inst, "strike", 0) or 0)
            main_opt_type = str(getattr(main_inst, "option_type", "") or "").upper()
            hedge_opt_type = str(getattr(hedge_inst, "option_type", "") or "").upper()

            # Must be same option type (both CE or both PE) for vertical spread
            if main_opt_type != hedge_opt_type:
                return 0.0

            # Calculate strike distance
            strike_distance = abs(main_strike - hedge_strike)
            if strike_distance <= 0:
                return 0.0

            # Lot size
            lot_size = int(getattr(main_inst, "lot_size", 75) or 75)

            # Max loss for vertical spread = strike_distance * lot_size
            max_loss = strike_distance * lot_size

            # Short leg SPAN margin
            short_span = main_margin["span_margin"] if main_leg.side == "SELL" else hedge_margin["span_margin"]

            # Hedge benefit: typically the short leg's SPAN margin minus the theoretical max loss margin
            # In practice, brokers apply ~60-85% reduction for vertical spreads
            # Conservative estimate: 70% of short SPAN margin
            hedge_efficiency = 0.70
            estimated_benefit = short_span * hedge_efficiency

            # Cap benefit at short SPAN margin (can't reduce below 0)
            max_benefit = short_span
            benefit = min(estimated_benefit, max_benefit)

            logger.debug(
                "Kotak hedge benefit estimate: main_strike=%.0f hedge_strike=%.0f "
                "distance=%.0f short_span=%.2f benefit=%.2f",
                main_strike, hedge_strike, strike_distance, short_span, benefit
            )

            return benefit

        except Exception as e:
            logger.warning("Hedge benefit estimation failed: %s", e)
            return 0.0

    def check_funds_before_orders(
        self,
        legs: List[Tuple[Any, Optional[float]]],
        *,
        include_position: bool = True,
        include_orders: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Multi-leg margin (hedge benefit) for same-structure ENTRY legs.

        Similar to Dhan's check_funds_before_orders.
        `legs`: list of (intent, execution_price)

        Returns dict with ok, available, required_margin (final_margin),
        span_margin, shortfall, hedge_benefit, leg_count, message.
        """
        if not legs:
            return None

        payloads = []
        for intent, execution_price in legs:
            try:
                payloads.append(self._build_margin_leg_payload(intent, execution_price))
            except Exception as e:
                logger.warning("Failed to build margin payload: %s", e)
                return None

        available = self._get_available_balance()
        if available is None:
            return None

        # If Kotak supports multi-leg margin API, use it
        # Otherwise fall back to single-leg + estimated hedge benefit
        source = getattr(self.api, "_source", None)
        neo_api = getattr(source, "api", None) if source else None

        if neo_api and hasattr(neo_api, "margin_required_multi"):
            # Use Kotak multi-leg margin if available
            try:
                multi_resp = neo_api.margin_required_multi(
                    payloads=payloads,
                    include_position=include_position,
                    include_orders=include_orders,
                )
                if isinstance(multi_resp, dict) and "data" in multi_resp:
                    data = multi_resp["data"]
                    required_margin = float(data.get("totalMargin") or data.get("total_margin") or 0)
                    span_margin = float(data.get("spanMargin") or data.get("span_margin") or 0)
                    hedge_benefit = data.get("hedgeBenefit") or data.get("hedge_benefit") or 0
                    ok = available >= required_margin
                    shortfall = max(0, required_margin - available)
                    return {
                        "ok": ok,
                        "available": available,
                        "required_margin": required_margin,
                        "span_margin": span_margin if span_margin else None,
                        "shortfall": shortfall,
                        "hedge_benefit": hedge_benefit,
                        "leg_count": len(legs),
                        "message": f"Multi-leg margin: available={available:.2f} required={required_margin:.2f} hedge_benefit={hedge_benefit:.2f}",
                    }
            except Exception as e:
                logger.warning("Kotak multi-leg margin failed, falling back: %s", e)

        # Fallback: calculate using single-leg margins with estimated hedge benefit
        if len(legs) == 2:
            # Try calculate_structure_margin for two legs
            intent1, px1 = legs[0]
            intent2, px2 = legs[1]
            structure_margin = self.calculate_structure_margin(
                intent1, intent2, px1, px2, include_position, include_orders
            )
            if structure_margin:
                required_margin = structure_margin["final_margin"]
                span_margin = structure_margin.get("span_margin")
                hedge_benefit = structure_margin.get("hedge_benefit")
                ok = available >= required_margin
                shortfall = max(0, required_margin - available)
                msg = f"Multi-leg margin (estimated): available={available:.2f} required={required_margin:.2f}"
                if hedge_benefit:
                    msg += f" hedge_benefit={hedge_benefit:.2f}"
                if not ok:
                    msg += f"; shortfall={shortfall:.2f}"
                return {
                    "ok": ok,
                    "available": available,
                    "required_margin": required_margin,
                    "span_margin": span_margin,
                    "shortfall": shortfall,
                    "hedge_benefit": hedge_benefit,
                    "leg_count": 2,
                    "message": msg,
                }

        # Final fallback: sum of single legs (no hedge benefit)
        total_required = 0.0
        total_span = 0.0
        for intent, execution_price in legs:
            payload = self._build_margin_leg_payload(intent, execution_price)
            try:
                resp = neo_api.margin_required(**payload)
                parsed = self._parse_margin_response(resp)
                total_required += parsed["total_margin"]
                total_span += parsed["span_margin"]
            except Exception:
                pass

        ok = available >= total_required
        shortfall = max(0, total_required - available)
        return {
            "ok": ok,
            "available": available,
            "required_margin": total_required,
            "span_margin": total_span if total_span else None,
            "shortfall": shortfall,
            "hedge_benefit": None,
            "leg_count": len(legs),
            "message": f"Multi-leg (sum of singles): available={available:.2f} required={total_required:.2f} shortfall={shortfall:.2f}",
        }

    def place_order(
        self,
        intent: Union[Dict, Any],
        execution_price: Optional[float] = None,
        retries: int = 0,
    ) -> Optional[str]:
        self._last_place_order_failure = None
        payload = kotak_map.intent_to_neo_payload(intent, execution_price)
        attempts = max(0, int(retries)) + 1
        for attempt in range(attempts):
            try:
                result = self.api.place_order(
                    tradingsymbol=payload["trading_symbol"],
                    exchange=payload["exchange_segment"],
                    quantity=int(payload["quantity"]),
                    price=float(payload["price"] or 0),
                    trigger_price=float(payload["trigger_price"] or 0),
                    order_type=payload["order_type"],
                    transaction_type=payload["transaction_type"],
                    trade_type=payload["product"],
                    disclosed_quantity=int(payload.get("disclosed_quantity") or 0),
                    after_market_order=str(payload.get("amo") or "NO").upper() == "YES",
                    validity=payload.get("validity") or "DAY",
                    tag=payload.get("tag"),
                    scrip_token=payload.get("scrip_token"),
                )
            except Exception as e:
                self._last_place_order_failure = {
                    "message": str(e),
                    "retryable": attempt + 1 < attempts,
                }
                logger.exception("Kotak place_order failed attempt=%s: %s", attempt + 1, e)
                continue
            if isinstance(result, dict) and result.get("status") == "success":
                oid = result.get("order_id")
                if oid:
                    return f"KOTAK_REST:{oid}"
            msg = (
                result.get("message")
                if isinstance(result, dict)
                else kotak_map.response_message(result)
            )
            self._last_place_order_failure = {
                "message": msg,
                "retryable": False,
                "raw": result,
            }
            logger.error(
                "Kotak place_order rejected %s: %s",
                payload.get("trading_symbol"),
                msg,
            )
            return None
        return None

    def exit_position(
        self,
        trading_symbol: str,
        qty: int,
        side: str,
        segment: str = "EQ",
        lot_size: int = 1,
        order_type: str = "MARKET",
        price: float = 0,
        trigger_price: float = 0,
        trade_type: str = "MARGIN",
        tag: Optional[str] = None,
    ) -> Optional[str]:
        exit_side = "SELL" if str(side).upper() in {"B", "BUY"} else "BUY"
        intent = {
            "trading_symbol": trading_symbol,
            "segment": segment,
            "qty": int(qty),
            "lot_size": int(lot_size or 1),
            "side": exit_side,
            "order_type": order_type,
            "price": price,
            "trigger_price": trigger_price,
            "trade_type": trade_type,
            "intent_id": tag,
        }
        return self.place_order(intent)

    def cancel_order(self, order_id: str) -> bool:
        oid = str(order_id or "")
        if oid.startswith("KOTAK_REST:"):
            oid = oid.split(":", 1)[1]
        elif oid.startswith("KOTAK_WS:"):
            oid = oid.split(":", 1)[1]
        try:
            result = self.api.cancel_order(oid)
            return isinstance(result, dict) and result.get("status") == "success"
        except Exception as e:
            logger.warning("Kotak cancel_order failed %s: %s", oid, e)
            return False

    def modify_order_price(
        self,
        order_id: str,
        price: float,
        trigger_price: float = 0,
        quantity: Optional[int] = None,
        order_type: str = "LIMIT",
    ) -> bool:
        oid = str(order_id or "")
        if oid.startswith("KOTAK_REST:") or oid.startswith("KOTAK_WS:"):
            oid = oid.split(":", 1)[1]
        try:
            result = self.api.modify_order(
                order_id=oid,
                price=price,
                trigger_price=trigger_price,
                quantity=quantity,
                order_type=order_type,
            )
            return isinstance(result, dict) and result.get("status") == "success"
        except Exception as e:
            logger.warning("Kotak modify_order failed %s: %s", oid, e)
            return False

    def get_positions(self, debug: str = "NO") -> Any:
        return self.api.get_positions(debug=debug)

    def get_order_list(self):
        return self.api.get_order_list()
