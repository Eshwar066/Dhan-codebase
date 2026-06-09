"""
Append option chain snapshots (live / backtest) to CSV.

Set ALGO_OPTION_CHAIN_CSV_LOG=0 to disable.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

try:
    from core.utils.json_numeric import round_json_floats
except ImportError:
    round_json_floats = None  # type: ignore

_ROOT = Path(__file__).resolve().parents[2]
_LOG_SUBDIR = "logs/option_chain_snapshots"
_OPTION_BUILDUP_SUBDIR = "logs/option_buildup"
_OI_POSITIONAL_BUY_SUBDIR = "logs/OIPositionalBuy"
_LEAPS_RSI_SUBDIR = "logs/LEAPS_RSI/option_chain_snapshots"
_LEAPS_RSI_HEDGE_SUBDIR = "logs/LEAPS_RSI/hedge_option_chain_snapshots"
_BANKNIFTY_BTST_SUBDIR = "logs/BankNiftyBTST/option_chain_snapshots"
_NAMED_SNAPSHOT_TARGETS = frozenset(
    {
        "option_buildup",
        "oi_positional_buy",
        "leaps_rsi",
        "leaps_rsi_hedge",
        "banknifty_btst",
    }
)

logger = logging.getLogger(__name__)

# Wall-clock retry policy for oi_positional_buy reference snapshots (not tied to candle bars).
OI_SNAPSHOT_RETRY_INTERVAL_SEC = float(
    os.getenv("OI_SNAPSHOT_RETRY_INTERVAL_SEC", "60")
)
OI_SNAPSHOT_RETRY_MAX_WINDOW_SEC = float(
    os.getenv("OI_SNAPSHOT_RETRY_MAX_WINDOW_SEC", str(45 * 60))
)


def snapshot_retry_should_attempt(
    last_attempt_unix: float,
    first_attempt_unix: float,
    *,
    now_unix: Optional[float] = None,
) -> Tuple[bool, str]:
    """
    Whether another snapshot fetch/write should run now.

    Returns (should_attempt, reason). Reasons include ``first_attempt``,
    ``interval_elapsed``, ``wait_<N>s``, and ``max_window_expired``.
    """
    now = time.time() if now_unix is None else float(now_unix)
    if first_attempt_unix <= 0:
        return True, "first_attempt"
    if now - first_attempt_unix > OI_SNAPSHOT_RETRY_MAX_WINDOW_SEC:
        return False, "max_window_expired"
    if last_attempt_unix <= 0:
        return True, "first_attempt"
    elapsed = now - last_attempt_unix
    if elapsed >= OI_SNAPSHOT_RETRY_INTERVAL_SEC:
        return True, "interval_elapsed"
    wait = OI_SNAPSHOT_RETRY_INTERVAL_SEC - elapsed
    return False, f"wait_{wait:.0f}s"


def _option_buildup_snapshot(params: Optional[dict]) -> bool:
    return (
        isinstance(params, dict)
        and bool(params.get("snapshot"))
        and str(params.get("snapshot_target") or "").strip().lower() == "option_buildup"
    )


def _safe_filename_part(s: str, max_len: int = 64) -> str:
    t = re.sub(r"[^\w\-.]+", "_", str(s).strip())
    return (t[:max_len] if t else "na").strip("_") or "na"


def _snapshot_out_dir(snapshot_target: str) -> Path:
    target = str(snapshot_target or "").strip().lower()
    if target == "option_buildup":
        return _ROOT / _OPTION_BUILDUP_SUBDIR
    if target == "oi_positional_buy":
        return _ROOT / _OI_POSITIONAL_BUY_SUBDIR
    if target == "leaps_rsi":
        return _ROOT / _LEAPS_RSI_SUBDIR
    if target == "leaps_rsi_hedge":
        return _ROOT / _LEAPS_RSI_HEDGE_SUBDIR
    if target == "banknifty_btst":
        return _ROOT / _BANKNIFTY_BTST_SUBDIR
    return _ROOT / _LOG_SUBDIR


def resolve_option_chain_snapshot_path(
    *,
    snapshot_date: str,
    snapshot_time: str,
    snapshot_target: str = "leaps_rsi",
) -> Optional[Path]:
    """Resolve ``{out_dir}/{date}/{HH-MM}.csv`` for a logged chain snapshot."""
    date_part = str(snapshot_date or "").strip()
    time_part = str(snapshot_time or "").strip().replace(":", "-")
    if not date_part or not time_part:
        return None
    day_dir = _snapshot_out_dir(snapshot_target) / _safe_filename_part(date_part)
    if not day_dir.is_dir():
        return None
    token = _safe_filename_part(time_part)
    for candidate in (
        day_dir / f"{token}.csv",
        day_dir / f"{token.replace('-', '')}.csv",
    ):
        if candidate.is_file():
            return candidate
    matches = sorted(day_dir.glob(f"*{token}*.csv"))
    return matches[0] if matches else None


def load_option_chain_snapshot_csv(
    path: Path,
    *,
    ctx_symbol: str = "",
    ctx_exchange: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Rebuild a DHAN-style chain dict from a snapshot CSV written by ``log_option_chain_snapshot``.

    Returns ``{symbol, exchange, chain: DataFrame, atm_strike, expiry}`` or None.
    """
    try:
        raw = pd.read_csv(path)
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return None
    if raw.empty:
        return None

    meta_cols = [c for c in raw.columns if str(c).startswith("_")]
    expiry = None
    atm = None
    sym = ctx_symbol or ""
    ex = ctx_exchange or ""
    if meta_cols:
        if "_chain_expiry" in raw.columns:
            val = raw["_chain_expiry"].iloc[0]
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                try:
                    expiry = pd.Timestamp(val).date()
                except (TypeError, ValueError):
                    expiry = val
        if "_atm_strike" in raw.columns:
            aval = raw["_atm_strike"].iloc[0]
            if aval is not None and not (isinstance(aval, float) and pd.isna(aval)):
                try:
                    atm = float(aval)
                except (TypeError, ValueError):
                    atm = aval
        if "_ctx_symbol" in raw.columns and not sym:
            sym = str(raw["_ctx_symbol"].iloc[0] or "").strip()
        if "_ctx_exchange" in raw.columns and not ex:
            ex = str(raw["_ctx_exchange"].iloc[0] or "").strip()

    df = raw.drop(columns=meta_cols, errors="ignore")
    if "Strike Price" in df.columns:
        df = df.drop_duplicates(subset=["Strike Price"], keep="last")
    if df.empty:
        return None

    return {
        "symbol": sym,
        "exchange": ex,
        "chain": df,
        "atm_strike": atm,
        "expiry": expiry,
    }


def load_option_chain_snapshot(
    *,
    snapshot_date: str,
    snapshot_time: str,
    snapshot_target: str = "leaps_rsi",
    ctx_symbol: str = "",
    ctx_exchange: str = "",
) -> Optional[Dict[str, Any]]:
    """Load chain dict from on-disk snapshot if the CSV exists."""
    path = resolve_option_chain_snapshot_path(
        snapshot_date=snapshot_date,
        snapshot_time=snapshot_time,
        snapshot_target=snapshot_target,
    )
    if path is None:
        return None
    return load_option_chain_snapshot_csv(
        path, ctx_symbol=ctx_symbol, ctx_exchange=ctx_exchange
    )


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
        target = str((params or {}).get("snapshot_target") or "").strip().lower()
        if target in ("option_buildup", "oi_positional_buy"):
            logger.warning(
                "%s snapshot skipped: chain=None (sym=%s date=%s time=%s)",
                target,
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
    elif target == "leaps_rsi":
        out_dir = _ROOT / _LEAPS_RSI_SUBDIR
    elif target == "leaps_rsi_hedge":
        out_dir = _ROOT / _LEAPS_RSI_HEDGE_SUBDIR
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
        if target in ("option_buildup", "oi_positional_buy"):
            logger.warning(
                "%s snapshot skipped: empty or non-DataFrame chain "
                "(sym=%s date=%s time=%s chain_type=%s)",
                target,
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
    if target in _NAMED_SNAPSHOT_TARGETS:
        fname = f"{time_token}.csv"
    else:
        exp_part = meta.get("snapshot_expiry") or "exp"
        fname = f"chain_{strat}_{sym}_{_safe_filename_part(str(exp_part))}_{time_token}.csv"
    path = out_dir / fname

    try:
        if path.exists():
            if target in _NAMED_SNAPSHOT_TARGETS:
                return True
            df_out.to_csv(
                path,
                index=False,
                encoding="utf-8",
                mode="a",
                header=False,
                float_format="%.2f",
            )
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

    if target in ("option_buildup", "oi_positional_buy"):
        logger.info(
            "%s snapshot written sym=%s -> %s",
            target,
            getattr(ctx, "symbol", "?"),
            path,
        )
    return True
