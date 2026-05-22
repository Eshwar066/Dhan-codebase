"""
Single contract with DhanHQ v2 field semantics (see Annexure in docs).

Maps internal strategy/broker intent fields ↔ Dhan REST / SDK expectations.
https://dhanhq.co/docs/v2/

Note: Official dhanhq Python client maps ``tag`` → JSON ``correlationId`` on place_order
(see dhanhq._order.place_order). WS order_alert returns ``CorrelationId`` in Data — use the
same string as ``tag`` at placement for primary fill routing.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# Internal segment (instrument.segment or exchange hint) → Dhan order_placement ``exchange`` arg
# (Tradehull then maps to exchange_segment / script_exchange).
INTERNAL_SEGMENT_TO_EXCHANGE_ARG: Dict[str, str] = {
    "EQ": "NSE",
    "NSE": "NSE",
    "NFO": "NFO",
    "FUT": "NFO",
    "OPT": "NFO",
    "MCX": "MCX",
    "BFO": "BFO",
    "CUR": "CUR",
    "BSE": "BSE",
    # Dhan scrip master uses SEM_SEGMENT "D" for derivatives (OPTIDX/FNO on NSE); order/margin need NFO segment, not NSE EQ.
    "D": "NFO",
    "CRYPTO": "CRYPTO",
}

# Tradehull ``instrument_exchange`` for security CSV lookup (SEM_EXM_EXCH_ID)
EXCHANGE_ARG_TO_INSTRUMENT_CSV_EXCH: Dict[str, str] = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NSE",
    "BFO": "BSE",
    "MCX": "MCX",
    "CUR": "NSE",
}

# Internal trade_type / product names → must match Tradehull ``product`` dict keys
TRADE_TYPE_ALIASES: Dict[str, str] = {
    "MIS": "MIS",
    "INTRADAY": "MIS",
    "INTRA": "MIS",
    "MARGIN": "MARGIN",
    "NRML": "MARGIN",
    "CNC": "CNC",
    "MTF": "MTF",
    "CO": "CO",
    "BO": "BO",
}

ORDER_TYPE_ALIASES: Dict[str, str] = {
    "LIMIT": "LIMIT",
    "MARKET": "MARKET",
    "SL": "STOPLIMIT",
    "SL-M": "STOPMARKET",
    "SLM": "STOPMARKET",
    "STOPLIMIT": "STOPLIMIT",
    "STOPMARKET": "STOPMARKET",
}

VALIDITY_ALIASES: Dict[str, str] = {
    "DAY": "DAY",
    "IOC": "IOC",
}


def normalize_trade_type(tt: Optional[str]) -> str:
    if not tt:
        return "MARGIN"
    u = str(tt).strip().upper()
    return TRADE_TYPE_ALIASES.get(u, u)


def normalize_order_type(ot: Optional[str]) -> str:
    if not ot:
        return "MARKET"
    u = str(ot).strip().upper()
    return ORDER_TYPE_ALIASES.get(u, u)


def normalize_validity(v: Optional[str]) -> str:
    if not v:
        return "DAY"
    u = str(v).strip().upper()
    return VALIDITY_ALIASES.get(u, u)


def internal_segment_to_exchange_arg(segment: Optional[str]) -> str:
    if not segment:
        return "NSE"
    s = str(segment).strip().upper()
    return INTERNAL_SEGMENT_TO_EXCHANGE_ARG.get(s, "NSE")


def to_broker_place_order_payload(intent_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a loose intent dict to DhanBroker / DhanSource.place_order kwargs shape.
    Does not resolve security_id — Tradehull still uses instrument CSV.
    """
    seg = intent_dict.get("segment")
    if seg is None and intent_dict.get("instrument") is not None:
        inst_obj = intent_dict.get("instrument")
        seg = getattr(inst_obj, "segment", None)
        if seg is None and isinstance(inst_obj, dict):
            seg = inst_obj.get("segment")
    ex = internal_segment_to_exchange_arg(
        str(seg) if seg is not None else "NFO"
    )
    tt = normalize_trade_type(
        intent_dict.get("trade_type") or intent_dict.get("product_type")
    )
    ot = normalize_order_type(intent_dict.get("order_type"))
    val = normalize_validity(intent_dict.get("validity"))
    intent_id = intent_dict.get("intent_id") or intent_dict.get("tag")
    return {
        "tradingsymbol": intent_dict.get("trading_symbol") or intent_dict.get("tradingsymbol"),
        "exchange": ex,
        "quantity": int(intent_dict.get("quantity") or intent_dict.get("qty") or 0),
        "price": float(intent_dict.get("price") or 0),
        "trigger_price": float(intent_dict.get("trigger_price") or 0),
        "order_type": ot,
        "transaction_type": str(intent_dict.get("side") or intent_dict.get("transaction_type") or "BUY").upper(),
        "trade_type": tt,
        "disclosed_quantity": int(intent_dict.get("disclosed_quantity") or 0),
        "after_market_order": bool(intent_dict.get("after_market_order", False)),
        "validity": val,
        "amo_time": intent_dict.get("amo_time") or "OPEN",
        "tag": dhan_correlation_id(str(intent_id)) if intent_id is not None else "",
        "correlation_id": dhan_correlation_id(str(intent_id)) if intent_id is not None else "",
    }


DHAN_CORRELATION_ID_MAX_LEN = 30


def dhan_correlation_id(intent_id: Optional[str]) -> str:
    """
    Dhan REST/WS ``correlationId``: max 30 chars, allowed ``[a-zA-Z0-9 _-]``.
    Full ``intent_id`` (32-char hex uuid) causes DH-905 on place order.
    """
    raw = str(intent_id or "").strip()
    cleaned = "".join(c for c in raw if c.isalnum() or c in " _-")
    return cleaned[:DHAN_CORRELATION_ID_MAX_LEN]


def from_broker_error(response: Any) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Normalize Dhan error payload to (message, error_type, error_code).
    """
    if not isinstance(response, dict):
        return (str(response), None, None)
    msg = (
        response.get("errorMessage")
        or response.get("message")
        or response.get("remarks")
        or str(response)
    )
    et = response.get("errorType") or response.get("error_type")
    ec = response.get("errorCode") or response.get("error_code")
    return (str(msg), str(et) if et is not None else None, str(ec) if ec is not None else None)
