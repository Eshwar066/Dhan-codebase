"""
Re-export for backward compatibility. Prefer core.api.DhanDataProvider (Dhan as single source).
"""
from legacy.free_nse_fetcher import FreeNSEFetcher

__all__ = ["FreeNSEFetcher"]
