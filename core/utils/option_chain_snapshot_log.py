"""
Append option chain snapshots (live / backtest) to CSV under logs/option_chain_snapshots/.

Set ALGO_OPTION_CHAIN_CSV_LOG=0 to disable.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
_LOG_SUBDIR = "logs/option_chain_snapshots"
IST = ZoneInfo("Asia/Kolkata")


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
) -> None:
    """
    Write chain payload to a timestamped CSV (one file per call).

    Supports:
    - DHAN-style dict: ``{symbol, exchange, chain: DataFrame, atm_strike, expiry}``
    - Bare ``DataFrame`` (some paths).
    """
    if os.getenv("ALGO_OPTION_CHAIN_CSV_LOG", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return
    if chain is None:
        return

    out_dir = _ROOT / _LOG_SUBDIR
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    # Filename timestamp uses IST for easier local operations/debugging.
    ts = datetime.now(IST).strftime("%Y%m%d_%H%M%S_%f")
    sym = _safe_filename_part(getattr(ctx, "symbol", None) or "UNK")
    strat = _safe_filename_part(strategy_name or "strategy")

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
        return

    snap = datetime.now(timezone.utc).isoformat()
    n = len(df)
    prefix = pd.DataFrame(
        {
            "_snapshot_utc": [snap] * n,
            "_strategy": [strategy_name or ""] * n,
            "_api": [api or ""] * n,
            "_ctx_symbol": [getattr(ctx, "symbol", "") or ""] * n,
            "_ctx_exchange": [getattr(ctx, "exchange", "") or ""] * n,
            "_chain_expiry": [meta.get("snapshot_expiry", "")] * n,
            "_atm_strike": [meta.get("snapshot_atm_strike", "")] * n,
        }
    )
    df_out = pd.concat([prefix, df.reset_index(drop=True)], axis=1)

    exp_part = meta.get("snapshot_expiry") or "exp"
    fname = f"chain_{strat}_{sym}_{_safe_filename_part(str(exp_part))}_{ts}.csv"
    path = out_dir / fname

    try:
        df_out.to_csv(path, index=False, encoding="utf-8")
    except OSError:
        return

    if params:
        try:
            ppath = path.with_suffix(".params.json")
            with open(ppath, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, default=str)
        except (OSError, TypeError):
            pass
