"""
Round floating-point values for logs, CSV exports, and JSON caches (2 decimals by default).

Internal trading math should stay full precision; apply these helpers at serialization boundaries.
"""

from __future__ import annotations

import math
from typing import Any


def round_json_floats(obj: Any, *, decimals: int = 2) -> Any:
    """
    Recursively round floats (including ``numpy`` scalars) to ``decimals`` places.

    Leaves ``int``, ``bool``, ``str``, ``bytes``, and ``None`` unchanged.
    """
    if obj is None or isinstance(obj, (bool, str, bytes)):
        return obj
    if isinstance(obj, int) and not isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return obj
        return round(obj, decimals)
    try:
        import numpy as np

        if isinstance(obj, np.generic):
            if np.issubdtype(type(obj), np.floating):
                x = float(obj)
                if math.isnan(x) or math.isinf(x):
                    return x
                return round(x, decimals)
            if np.issubdtype(type(obj), np.integer):
                return int(obj)
    except Exception:
        pass
    if isinstance(obj, dict):
        return {k: round_json_floats(v, decimals=decimals) for k, v in obj.items()}
    if isinstance(obj, list):
        return [round_json_floats(v, decimals=decimals) for v in obj]
    if isinstance(obj, tuple):
        return tuple(round_json_floats(v, decimals=decimals) for v in obj)
    return obj
