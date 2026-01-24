"""
Legacy / non-Dhan data sources. Prefer core.api (Dhan) as single source of truth.
"""

from legacy.free_nse_fetcher import FreeNSEFetcher

__all__ = ["FreeNSEFetcher"]
