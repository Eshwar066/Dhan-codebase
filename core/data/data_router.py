from core.data.adapters.nse_adapter import NSEAdapter
from core.data.adapters.dhan_adapter import DhanAdapter
from core.data.adapters.kotak_adapter import KotakAdapter


class DataRouter:
    """
    Pick an option-chain adapter by API key.

    Engines set ``default_api`` from the venue (e.g. KOTAK / DHAN) so strategies
    can keep a legacy ``api="DHAN"`` and still hit the venue adapter.
    """

    def __init__(self, data_service, default_api: str | None = None):
        self.adapters = {
            "NSE": NSEAdapter(data_service),
            "DHAN": DhanAdapter(data_service),
            "KOTAK": KotakAdapter(data_service),
        }
        self.default_api = (default_api or "").strip().upper() or None

    def resolve_api(self, api: str | None) -> str:
        requested = (api or "").strip().upper()
        # Preserve explicit NSE (and future DELTA) selections.
        if requested in ("NSE", "DELTA"):
            if requested in self.adapters:
                return requested
            raise ValueError(f"Unsupported api source: {requested}")
        if self.default_api and self.default_api in self.adapters:
            return self.default_api
        if not requested:
            raise ValueError("params must define 'api' (NSE / DHAN / KOTAK)")
        if requested not in self.adapters:
            raise ValueError(f"Unsupported api source: {requested}")
        return requested

    def from_candle(self, params):
        if "api" not in params and not self.default_api:
            raise ValueError("params must define 'api' (NSE / DHAN / KOTAK)")

        api = self.resolve_api(params.get("api"))
        params["api"] = api
        return self.adapters[api]
