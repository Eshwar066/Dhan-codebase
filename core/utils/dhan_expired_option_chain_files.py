"""
Load Dhan expired option OHLC from locally downloaded CSVs (same layout as
``dhan expired option chain/Expired options data.py``):

    {root}/ATM Wise data/{SYMBOL}/{YYYY-MM-DD}/{ATM±n}/{SYMBOL}_{YYYY-MM-DD}_CALL.csv
    {root}/ATM Wise data/{SYMBOL}/{YYYY-MM-DD}/{ATM±n}/{SYMBOL}_{YYYY-MM-DD}_PUT.csv

``root`` is the folder that contains ``ATM Wise data`` — e.g.
``dhan expired option chain/dhan/Two month Options data 15 mins`` or
``.../Monthly Options data 15 mins``.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, List, Optional, Sequence, Union

import pandas as pd

logger = logging.getLogger(__name__)

# Project root (parent of ``core``)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_expired_option_chain_root() -> Optional[Path]:
    """
    If ``DHAN_EXPIRED_OPTION_CHAIN_ROOT`` is unset, look under
    ``<repo>/dhan expired option chain/`` for a data folder that contains
    ``ATM Wise data`` (see candidates below).
    """
    env = (os.getenv("DHAN_EXPIRED_OPTION_CHAIN_ROOT") or "").strip()
    if env:
        p = Path(env).expanduser()
        return p if p.is_dir() else None
    base = _PROJECT_ROOT / "dhan expired option chain"
    if not base.is_dir():
        return None
    # Prefer: dhan/Two month Options data 15 mins (then top-level fallbacks)
    candidates: List[Path] = [
        base / "dhan" / "Two month Options data 15 mins",
        # base / "Two month Options data 15 mins",
        # base / "Monthly Options data 15 mins",
        # base / "Monthly Options data 60 mins",
    ]
    for cand in candidates:
        if cand.is_dir():
            return cand
    return None


def resolve_atm_wise_root(root: Optional[Union[str, Path]] = None) -> Optional[Path]:
    """Return directory that contains ``ATM Wise data``, or None."""
    r = Path(root).expanduser() if root else default_expired_option_chain_root()
    if r is None:
        return None
    if not r.is_dir():
        return None
    aw = r / "ATM Wise data"
    return aw if aw.is_dir() else r


def atm_label_from_spot_strike(
    spot_price: float,
    strike: float,
    strike_step: int = 50,
    max_n: int = 10,
) -> str:
    """
    Same mapping as ``DhanAdapter.get_historical_option_chain`` (ATM, ATM±n).
    """
    atm_strike = round(float(spot_price) / strike_step) * strike_step
    diff = int(round(float(strike))) - int(atm_strike)
    n = int(diff / strike_step) if strike_step else 0
    if n == 0:
        return "ATM"
    if 0 < n <= max_n:
        return f"ATM+{n}"
    if -max_n <= n < 0:
        return f"ATM{n}"
    if n > max_n:
        return f"ATM+{max_n}"
    return f"ATM-{max_n}"


def _normalize_expiry_str(expiry: Union[date, datetime, str]) -> str:
    if isinstance(expiry, str):
        return expiry[:10]
    if hasattr(expiry, "strftime"):
        return expiry.strftime("%Y-%m-%d")
    return str(expiry)[:10]


def _option_right_filename(option_type: str) -> str:
    u = str(option_type).upper()
    if u in ("PUT", "PE"):
        return "PUT"
    return "CALL"


def leg_csv_path(
    atm_wise_root: Path,
    symbol: str,
    expiry: Union[date, datetime, str],
    atm_label: str,
    option_type: str,
) -> Path:
    exp_s = _normalize_expiry_str(expiry)
    sym = symbol.upper()
    right = _option_right_filename(option_type)
    return (
        atm_wise_root
        / sym
        / exp_s
        / atm_label
        / f"{sym}_{exp_s}_{right}.csv"
    )


def read_leg_csv(path: Path) -> Optional[pd.DataFrame]:
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path)
    except Exception as e:
        logger.warning("Failed to read expired option CSV %s: %s", path, e)
        return None
    if df is None or df.empty:
        return None
    if "datetime" not in df.columns:
        return None
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce", utc=True)
    df = df.dropna(subset=["datetime"])
    return df


def strikes_to_atm_folder_labels(
    strikes: Sequence[Any],
    spot_price: float,
    strike_step: int = 50,
) -> List[str]:
    """
    Map numeric strikes (or precomputed ``ATM`` / ``ATM±n`` folder names) to folder labels.
    De-duplicates while preserving order.
    """
    out: List[str] = []
    seen: set[str] = set()
    for s in strikes:
        if isinstance(s, str) and s.upper().startswith("ATM"):
            label = s
        else:
            try:
                strike_f = float(s)
            except (TypeError, ValueError):
                continue
            label = atm_label_from_spot_strike(
                spot_price, strike_f, strike_step=strike_step
            )
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out


def load_expired_option_chain_from_files(
    *,
    symbol: str,
    calendar_expiry: Union[date, datetime, str],
    strikes: Sequence[Any],
    option_type: str,
    spot_price: float,
    from_date: str,
    to_date: str,
    root: Optional[Union[str, Path]] = None,
    strike_step: int = 50,
) -> Optional[pd.DataFrame]:
    """
    Load and concatenate one leg (CALL or PUT) across multiple strike folders.

    Rows are filtered to ``from_date`` … ``to_date`` (inclusive, date part only).
    """
    atm_wise = resolve_atm_wise_root(root)
    if atm_wise is None:
        logger.debug(
            "Dhan expired option files: no root (set DHAN_EXPIRED_OPTION_CHAIN_ROOT "
            "or add e.g. dhan expired option chain/dhan/Two month Options data 15 mins "
            "with ATM Wise data inside)"
        )
        return None

    sym = symbol.upper()
    strike_list: List[Any] = list(strikes)
    if not strike_list:
        return None

    labels = strikes_to_atm_folder_labels(
        strike_list, spot_price, strike_step=strike_step
    )
    if not labels:
        return None

    frames: List[pd.DataFrame] = []
    for label in labels:
        path = leg_csv_path(atm_wise, sym, calendar_expiry, label, option_type)
        df = read_leg_csv(path)
        if df is None or df.empty:
            continue
        frames.append(df)

    if not frames:
        return None

    out = pd.concat(frames, ignore_index=True)
    fd = pd.to_datetime(from_date).date()
    td = pd.to_datetime(to_date).date()
    dpart = pd.to_datetime(out["datetime"], utc=True).dt.date
    out = out[(dpart >= fd) & (dpart <= td)]
    if out.empty:
        return None
    return out.sort_values("datetime").reset_index(drop=True)
