"""
Append option chain snapshots (live / backtest) to CSV.

Set ALGO_OPTION_CHAIN_CSV_LOG=0 to disable.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

try:
    from core.utils.json_numeric import round_json_floats
except ImportError:
    round_json_floats = None  # type: ignore

_ROOT = Path(__file__).resolve().parents[2]
_LOG_SUBDIR = "logs/option_chain_snapshots"
_OPTION_BUILDUP_SUBDIR = "logs/option_buildup"
_OI_POSITIONAL_BUY_SUBDIR = "logs/OIPositionalBuy"

logger = logging.getLogger(__name__)


def _option_buildup_snapshot(params: Optional[dict]) -> bool:
    return (
        isinstance(params, dict)
        and bool(params.get("snapshot"))
        and str(params.get("snapshot_target") or "").strip().lower() == "option_buildup"
    )


def _safe_filename_part(s: str, max_len: int = 64) -> str:
    t = re.sub(r"[^\w\-.]+", "_", str(s).strip())
    return (t[:max_len] if t else "na").strip("_") or "na"


def log_option_chain_snapshot(
    chain: Any,
    *,
    ctx: Any,
    strategy_name: str = "",
    api: str = "",
    params: Optional[dict] = None,
) -> bool:
    """
    Write chain payload to a timestamped CSV (one file per call).

    Supports:
    - DHAN-style dict: ``{symbol, exchange, chain: DataFrame, atm_strike, expiry}``
    - Bare ``DataFrame`` (some paths).

    Returns True if a non-empty CSV was written.
    """
    if os.getenv("ALGO_OPTION_CHAIN_CSV_LOG", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        if _option_buildup_snapshot(params if isinstance(params, dict) else None):
            logger.warning(
                "option_buildup snapshot skipped: ALGO_OPTION_CHAIN_CSV_LOG disabled "
                "(sym=%s slot=%s)",
                getattr(ctx, "symbol", "?"),
                (params or {}).get("snapshot_time"),
            )
        return False
    if isinstance(params, dict) and not bool(params.get("snapshot", False)):
        return False
    if chain is None:
        if _option_buildup_snapshot(params if isinstance(params, dict) else None):
            logger.warning(
                "option_buildup snapshot skipped: chain=None (sym=%s date=%s time=%s)",
                getattr(ctx, "symbol", "?"),
                (params or {}).get("snapshot_date"),
                (params or {}).get("snapshot_time"),
            )
        return False

    target = str((params or {}).get("snapshot_target") or "").strip().lower()
    if target == "option_buildup":
        out_dir = _ROOT / _OPTION_BUILDUP_SUBDIR
    elif target == "oi_positional_buy":
        out_dir = _ROOT / _OI_POSITIONAL_BUY_SUBDIR
    else:
        out_dir = _ROOT / _LOG_SUBDIR

    ts_now = datetime.now(timezone.utc)
    date_part = str((params or {}).get("snapshot_date") or ts_now.strftime("%Y-%m-%d"))
    time_part = str((params or {}).get("snapshot_time") or ts_now.strftime("%H%M"))

    df: Optional[pd.DataFrame] = None
    meta: dict[str, Any] = {}

    if isinstance(chain, dict):
        meta = {
            "snapshot_symbol": chain.get("symbol"),
            "snapshot_exchange": chain.get("exchange"),
            "snapshot_expiry": chain.get("expiry"),
            "snapshot_atm_strike": chain.get("atm_strike"),
        }
        inner = chain.get("chain")
        if isinstance(inner, pd.DataFrame):
            df = inner.copy()
    elif isinstance(chain, pd.DataFrame):
        df = chain.copy()

    if df is None or df.empty:
        if target == "option_buildup":
            logger.warning(
                "option_buildup snapshot skipped: empty or non-DataFrame chain "
                "(sym=%s date=%s time=%s chain_type=%s)",
                getattr(ctx, "symbol", "?"),
                (params or {}).get("snapshot_date"),
                (params or {}).get("snapshot_time"),
                type(chain).__name__,
            )
        return False

    out_dir = out_dir / _safe_filename_part(date_part)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if target == "option_buildup":
            logger.warning(
                "option_buildup snapshot skipped: mkdir failed %s (%s)", out_dir, exc
            )
        return False

    sym = _safe_filename_part(getattr(ctx, "symbol", None) or "UNK")
    strat = _safe_filename_part(strategy_name or "strategy")

    snap = datetime.now(timezone.utc).isoformat()
    n = len(df)
    prefix = pd.DataFrame(
        {
            # "_snapshot_utc": [snap] * n,
            "_strategy": [strategy_name or ""] * n,
            "_api": [api or ""] * n,
            "_ctx_symbol": [getattr(ctx, "symbol", "") or ""] * n,
            "_ctx_exchange": [getattr(ctx, "exchange", "") or ""] * n,
            "_chain_expiry": [meta.get("snapshot_expiry", "")] * n,
            "_atm_strike": [meta.get("snapshot_atm_strike", "")] * n,
        }
    )
    df_out = pd.concat([prefix, df.reset_index(drop=True)], axis=1)
    df_out.insert(1, "_snapshot_date", date_part)
    df_out.insert(2, "_snapshot_slot", time_part)

    time_token = _safe_filename_part(time_part)
    if target in ("option_buildup", "oi_positional_buy"):
        fname = f"{time_token}.csv"
    else:
        exp_part = meta.get("snapshot_expiry") or "exp"
        fname = f"chain_{strat}_{sym}_{_safe_filename_part(str(exp_part))}_{time_token}.csv"
    path = out_dir / fname

    try:
        if path.exists():
            df_out.to_csv(path, index=False, encoding="utf-8", mode="a", header=False, float_format="%.2f")
        else:
            df_out.to_csv(path, index=False, encoding="utf-8", float_format="%.2f")
    except OSError as exc:
        if target == "option_buildup":
            logger.warning(
                "option_buildup snapshot skipped: CSV write failed path=%s (%s)", path, exc
            )
        return False

    if params:
        try:
            ppath = path.with_suffix(".params.json")
            with open(ppath, "w", encoding="utf-8") as f:
                pout = round_json_floats(params) if round_json_floats else params
                json.dump(pout, f, indent=2, default=str)
        except (OSError, TypeError):
            pass

    if target == "option_buildup":
        logger.info(
            "option_buildup snapshot written sym=%s -> %s", getattr(ctx, "symbol", "?"), path
        )
    return True
