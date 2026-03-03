"""
Delta Exchange environment credentials.

When using testnet/demo, prefers DEMO_DELTA_API_KEY and DEMO_DELTA_API_SECRET
so production and demo accounts can be kept separate in .env.
"""

import os
from typing import Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def get_delta_credentials(testnet: bool) -> Tuple[str, str]:
    """
    Return (api_key, api_secret) for Delta Exchange.

    - If testnet is True: use DEMO_DELTA_API_KEY / DEMO_DELTA_API_SECRET if set,
      otherwise fall back to DELTA_API_KEY / DELTA_API_SECRET.
    - If testnet is False: use DELTA_API_KEY / DELTA_API_SECRET only.

    Raises ValueError if credentials are missing.
    """
    if testnet:
        api_key = os.getenv("DEMO_DELTA_API_KEY") or os.getenv("DELTA_API_KEY")
        api_secret = os.getenv("DEMO_DELTA_API_SECRET") or os.getenv("DELTA_API_SECRET")
    else:
        api_key = os.getenv("DELTA_API_KEY")
        api_secret = os.getenv("DELTA_API_SECRET")

    if not api_key or not api_secret:
        raise ValueError(
            "Delta API credentials not found. For testnet/demo set DEMO_DELTA_API_KEY and "
            "DEMO_DELTA_API_SECRET (or DELTA_API_KEY / DELTA_API_SECRET). For production set "
            "DELTA_API_KEY and DELTA_API_SECRET."
        )
    return api_key, api_secret
