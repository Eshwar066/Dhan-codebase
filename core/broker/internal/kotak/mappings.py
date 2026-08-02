"""
Kotak Neo order/segment mappings for OMS intents.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# Internal segment / exchange → Neo exchange_segment keys (neo_api_client.settings).
_SEGMENT_TO_NEO = {
    "NSE": "nse_cm",
    "NSE_EQ": "nse_cm",
    "EQ": "nse_cm",
    "NSECM": "nse_cm",
    "BSE": "bse_cm",
    "BSE_EQ": "bse_cm",
    "BSECM": "bse_cm",
    "NFO": "nse_fo",
    "NSE_FO": "nse_fo",
    "NSEFO": "nse_fo",
    "BFO": "bse_fo",
    "BSE_FO": "bse_fo",
    "BSEFO": "bse_fo",
    "MCX": "mcx_fo",
    "MCX_FO": "mcx_fo",
    "CDS": "cde_fo",
    "CURRENCY": "cde_fo",
    "INDEX": "nse_cm",
    "DHAN": "nse_cm",
    "KOTAK": "nse_cm",
}


def internal_segment_to_neo(segment: Any) -> str:
    key = str(segment or "NSE").strip().upper()
    return _SEGMENT_TO_NEO.get(key, "nse_cm")


def normalize_order_type(order_type: Any) -> str:
    raw = str(order_type or "MARKET").strip().upper().replace("_", "-")
    if raw in {"MKT", "MARKET"}:
        return "MKT"
    if raw in {"L", "LIMIT"}:
        return "L"
    if raw in {"SL", "STOP", "STOPLIMIT", "STOP-LIMIT"}:
        return "SL"
    if raw in {"SL-M", "SLM", "STOPMARKET", "STOP-MARKET"}:
        return "SL-M"
    return "MKT"


def normalize_product(trade_type: Any, segment: Any = None) -> str:
    """Map OMS trade_type → Neo product (CNC / MIS / NRML)."""
    tt = str(trade_type or "MARGIN").strip().upper()
    seg = str(segment or "").strip().upper()
    if tt in {"CNC", "DELIVERY", "CO"}:
        return "CNC"
    if tt in {"MIS", "INTRADAY", "BO"}:
        return "MIS"
    if tt in {"NRML", "MARGIN", "CARRYFORWARD", "CF"}:
        # Equity overnight → CNC; F&O → NRML
        if seg in {"NSE", "BSE", "EQ", "NSE_EQ", "BSE_EQ"}:
            return "CNC"
        return "NRML"
    return "MIS"


def normalize_transaction(side: Any) -> str:
    s = str(side or "BUY").strip().upper()
    return "B" if s in {"B", "BUY"} else "S"


def extract_order_id(resp: Any) -> Optional[str]:
    """Best-effort order id from Neo place/modify responses."""
    if resp is None:
        return None
    if isinstance(resp, (str, int)):
        s = str(resp).strip()
        return s or None
    if not isinstance(resp, dict):
        return None
    for key in (
        "nOrdNo",
        "order_id",
        "orderId",
        "NOrdNo",
        "neoOrdNo",
        "oid",
    ):
        val = resp.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    data = resp.get("data")
    if isinstance(data, dict):
        return extract_order_id(data)
    if isinstance(data, list) and data:
        return extract_order_id(data[0])
    return None


def is_error_response(resp: Any) -> bool:
    if resp is None:
        return True
    if isinstance(resp, dict):
        if resp.get("error") or resp.get("Error Message") or resp.get("error_message"):
            return True
        st = str(resp.get("stat") or resp.get("status") or "").strip().upper()
        if st in {"NOT_OK", "ERROR", "FAILED", "FAILURE"}:
            return True
    return False


def response_message(resp: Any) -> str:
    if resp is None:
        return "empty response"
    if isinstance(resp, dict):
        for key in ("Error Message", "error_message", "message", "emsg", "stCode"):
            if resp.get(key) is not None:
                return str(resp.get(key))
        err = resp.get("error")
        if err is not None:
            return str(err)
    return str(resp)


def intent_to_neo_payload(
    intent: Any,
    execution_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Build Neo place_order kwargs from OrderIntent or dict."""
    if hasattr(intent, "instrument"):
        inst = intent.instrument
        trading_symbol = inst.place_order_symbol()
        segment = getattr(inst, "segment", "NFO") or "NFO"
        qty = int(getattr(intent, "qty", getattr(inst, "lot_size", 1)) or 1)
        lot_size = int(getattr(inst, "lot_size", 1) or 1)
        total_qty = qty * lot_size
        intent_price = float(getattr(intent, "price", 0) or 0)
        trigger = float(getattr(intent, "trigger_price", 0) or 0)
        side = getattr(intent, "side", "BUY")
        order_type = getattr(intent, "order_type", "MARKET")
        trade_type = getattr(intent, "trade_type", "MARGIN")
        tag = getattr(intent, "intent_id", None)
        scrip_token = getattr(inst, "instrument_id", None)
    else:
        trading_symbol = str(intent.get("trading_symbol") or intent.get("tradingsymbol") or "")
        segment = intent.get("segment", "EQ")
        total_qty = int(intent.get("qty", 1)) * int(intent.get("lot_size", 1) or 1)
        intent_price = float(intent.get("price", 0) or 0)
        trigger = float(intent.get("trigger_price", 0) or 0)
        side = intent.get("side", "BUY")
        order_type = intent.get("order_type", "MARKET")
        trade_type = intent.get("trade_type", "MARGIN")
        tag = intent.get("intent_id") or intent.get("tag")
        scrip_token = intent.get("instrument_id") or intent.get("scrip_token")

    ot = normalize_order_type(order_type)
    price = float(execution_price) if execution_price is not None else intent_price
    if ot == "MKT":
        price = 0.0
    if trigger <= 0 and ot in {"SL", "SL-M"}:
        trigger = price

    return {
        "exchange_segment": internal_segment_to_neo(segment),
        "product": normalize_product(trade_type, segment),
        "price": str(price if price > 0 else "0"),
        "order_type": ot,
        "quantity": str(int(total_qty)),
        "validity": "DAY",
        "trading_symbol": trading_symbol,
        "transaction_type": normalize_transaction(side),
        "amo": "NO",
        "disclosed_quantity": "0",
        "trigger_price": str(trigger if trigger > 0 else "0"),
        "tag": str(tag) if tag else None,
        "scrip_token": str(scrip_token) if scrip_token is not None else None,
    }
