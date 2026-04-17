"""
Dhan Postback (webhook) — optional third path for order lifecycle events.

Docs: Trading APIs → Postback in DhanHQ v2.
Wire an HTTPS endpoint to your infra and forward payloads into OrderRouter.process_trade
with the same trade_id / intent rules as REST + WS.

This module only provides parsing helpers — no HTTP server (avoid binding ports in the engine).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def postback_body_to_trade_hint(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Best-effort map of a postback JSON body to fields useful for OMS.
    Actual schema is versioned in Dhan docs — adjust keys to match your subscribed events.
    """
    if not isinstance(body, dict):
        return None
    oid = body.get("orderId") or body.get("order_id") or body.get("OrderNo")
    cid = body.get("correlationId") or body.get("correlation_id") or body.get("tag")
    if not oid and not cid:
        return None
    return {
        "order_id": str(oid) if oid else "",
        "correlation_id": str(cid) if cid else "",
        "raw": body,
    }


def verify_postback_signature(
    _headers: Dict[str, str],
    _body_bytes: bytes,
    _secret: str,
) -> bool:
    """
    Placeholder: implement HMAC/signature verification per Dhan postback documentation.
    """
    logger.debug("Postback signature verification not configured")
    return True
