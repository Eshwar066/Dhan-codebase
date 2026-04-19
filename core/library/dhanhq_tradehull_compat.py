"""
Tradehull expects ``DhanContext``, ``dhanhq(DhanContext)``, and ``FullDepth`` from older
dhanhq-style APIs. The PyPI ``dhanhq`` 2.x package uses ``dhanhq(client_id, access_token)``
instead. This module maps the legacy call pattern onto dhanhq 2.x.
"""

from __future__ import annotations

from dhanhq.dhanhq import dhanhq as _DhanhqClient


class DhanContext:
    __slots__ = ("client_id", "token_id")

    def __init__(self, client_id: str, token_id: str) -> None:
        self.client_id = str(client_id)
        self.token_id = token_id


def dhanhq(ctx: DhanContext) -> _DhanhqClient:
    if not isinstance(ctx, DhanContext):
        raise TypeError(f"dhanhq() expects DhanContext, got {type(ctx).__name__}")
    return _DhanhqClient(ctx.client_id, ctx.token_id)


class FullDepth:
    """
    Legacy full-depth WebSocket helper from older dhanhq builds.
    Not implemented on dhanhq 2.x; Tradehull paths that call this will fail loudly.
    """

    def __init__(self, dhan_context: DhanContext, instruments) -> None:
        self._dhan_context = dhan_context
        self._instruments = instruments
        self.ws = None

    def run_forever(self) -> None:
        raise NotImplementedError(
            "FullDepth is not available with dhanhq 2.x. "
            "Use DhanDepthFeed / DhanDepthWebSocket for depth, or pin a legacy dhanhq build."
        )

    def get_data(self) -> None:
        raise NotImplementedError(
            "FullDepth is not available with dhanhq 2.x. "
            "Use DhanDepthFeed / DhanDepthWebSocket for depth, or pin a legacy dhanhq build."
        )
