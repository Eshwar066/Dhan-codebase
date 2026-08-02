"""
Build a DHAN-shaped live option-chain DataFrame from Kotak instruments + quotes.

Strategies (e.g. LEAPS) consume columns like ``Strike Price``, ``CE LTP``,
``PE LTP``, ``CE Bid`` / ``CE Ask``, etc. — same contract as Tradehull
``format_option_chain``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

# Column order mirrors core/library/dhan_tradehull.format_option_chain
DHAN_OPTION_CHAIN_COLUMNS: Tuple[str, ...] = (
    "CE OI",
    "CE Chg in OI",
    "CE Volume",
    "CE IV",
    "CE LTP",
    "CE Bid Qty",
    "CE Bid",
    "CE Ask",
    "CE Ask Qty",
    "CE Delta",
    "CE Theta",
    "CE Gamma",
    "CE Vega",
    "Strike Price",
    "PE Bid Qty",
    "PE Bid",
    "PE Ask",
    "PE Ask Qty",
    "PE LTP",
    "PE IV",
    "PE Volume",
    "PE Chg in OI",
    "PE OI",
    "PE Delta",
    "PE Theta",
    "PE Gamma",
    "PE Vega",
)


def _to_date(value: Any) -> Optional[date]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date() if hasattr(ts, "date") else None


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def underlying_option_mask(df: pd.DataFrame, symbol: str) -> pd.Series:
    """True for OPTIDX/OPTSTK rows belonging to ``symbol`` (e.g. NIFTY, not NIFTYNXT50)."""
    root = str(symbol or "").strip().upper()
    if not root or df is None or df.empty:
        return pd.Series(dtype=bool)
    instr = df["SEM_INSTRUMENT_NAME"].astype(str).str.upper().str.strip()
    is_opt = instr.isin(("OPTIDX", "OPTSTK"))
    cust = df["SEM_CUSTOM_SYMBOL"].fillna("").astype(str).str.upper()
    first = cust.str.split().str[0]
    if "SM_SYMBOL_NAME" in df.columns:
        sm = df["SM_SYMBOL_NAME"].fillna("").astype(str).str.strip().str.upper()
        under = ((sm != "") & (sm == root)) | ((sm == "") & first.eq(root))
    else:
        under = first.eq(root)
    return is_opt & under


def list_option_expiries(
    instruments: pd.DataFrame,
    symbol: str,
    *,
    monthly_only: bool = False,
) -> List[date]:
    mask = underlying_option_mask(instruments, symbol)
    sub = instruments.loc[mask]
    if sub.empty:
        return []
    if monthly_only and "SEM_EXPIRY_FLAG" in sub.columns:
        m = sub["SEM_EXPIRY_FLAG"].astype(str).str.upper().str.strip() == "M"
        if m.any():
            sub = sub.loc[m]
    dates = sorted({d for d in (_to_date(v) for v in sub["SEM_EXPIRY_DATE"]) if d})
    return dates


def option_rows_for_expiry(
    instruments: pd.DataFrame,
    symbol: str,
    expiry: date,
    *,
    monthly_only: bool = False,
) -> pd.DataFrame:
    mask = underlying_option_mask(instruments, symbol)
    sub = instruments.loc[mask].copy()
    if sub.empty:
        return sub
    if monthly_only and "SEM_EXPIRY_FLAG" in sub.columns:
        m = sub["SEM_EXPIRY_FLAG"].astype(str).str.upper().str.strip() == "M"
        if m.any():
            sub = sub.loc[m]
    sub["_exp"] = sub["SEM_EXPIRY_DATE"].map(_to_date)
    out = sub.loc[sub["_exp"] == expiry].drop(columns=["_exp"], errors="ignore")
    return out.reset_index(drop=True)


def resolve_expiry(
    expiries: Sequence[date],
    *,
    expiry_index: int = 0,
    expiry_date: Any = None,
    expiry_match_same_month: bool = False,
) -> Optional[date]:
    if not expiries:
        return None
    if expiry_date is not None:
        target = _to_date(expiry_date)
        if target is None:
            return None
        if target in expiries:
            return target
        if expiry_match_same_month:
            same = [e for e in expiries if e.year == target.year and e.month == target.month]
            if same:
                return min(same, key=lambda e: abs((e - target).days))
        # nearest by day distance
        return min(expiries, key=lambda e: abs((e - target).days))
    ei = int(expiry_index or 0)
    if ei < 0:
        ei = 0
    if ei >= len(expiries):
        ei = len(expiries) - 1
    return expiries[ei]


def atm_strike_from_spot(spot: float, strikes: Iterable[float]) -> Optional[float]:
    vals = sorted({float(s) for s in strikes if s is not None and not pd.isna(s)})
    if not vals or spot is None or spot <= 0:
        return None
    return min(vals, key=lambda s: abs(s - float(spot)))


def filter_strikes_around_atm(
    strikes: Sequence[float],
    atm: float,
    strikes_around_atm: int,
) -> List[float]:
    vals = sorted({float(s) for s in strikes})
    if not vals:
        return []
    n = max(1, int(strikes_around_atm or 1))
    # ``strikes_around_atm`` means total strikes near ATM (Dhan num_strikes style)
    ordered = sorted(vals, key=lambda s: abs(s - float(atm)))
    keep = set(ordered[:n])
    return [s for s in vals if s in keep]


def quote_fields(raw: Any) -> Dict[str, float]:
    """Normalize REST dict or SFeed message into LTP / bid / ask / OI / volume."""
    if raw is None:
        return {
            "ltp": 0.0,
            "bid": 0.0,
            "ask": 0.0,
            "bid_qty": 0.0,
            "ask_qty": 0.0,
            "oi": 0.0,
            "volume": 0.0,
            "iv": 0.0,
        }

    if hasattr(raw, "last_traded_price"):
        bid = ask = bid_qty = ask_qty = 0.0
        buy = getattr(raw, "buy", None) or []
        sell = getattr(raw, "sell", None) or []
        if buy:
            bid = _f(getattr(buy[0], "price", 0))
            bid_qty = _f(getattr(buy[0], "quantity", 0))
        if sell:
            ask = _f(getattr(sell[0], "price", 0))
            ask_qty = _f(getattr(sell[0], "quantity", 0))
        ltp = _f(getattr(raw, "last_traded_price", 0))
        if ltp <= 0:
            ltp = _f(getattr(raw, "close_price", 0))
        return {
            "ltp": ltp,
            "bid": bid,
            "ask": ask,
            "bid_qty": bid_qty,
            "ask_qty": ask_qty,
            "oi": _f(getattr(raw, "open_interest", 0)),
            "volume": _f(getattr(raw, "volume_traded_today", 0)),
            "iv": 0.0,
        }

    if isinstance(raw, Mapping):
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        ltp = _f(
            data.get("last_traded_price")
            or data.get("ltp")
            or data.get("LTP")
            or data.get("close")
            or data.get("c")
        )
        bid = _f(data.get("buy_price") or data.get("bp") or data.get("bid"))
        ask = _f(data.get("sell_price") or data.get("sp") or data.get("ask"))
        return {
            "ltp": ltp,
            "bid": bid,
            "ask": ask,
            "bid_qty": _f(data.get("buy_quantity") or data.get("bq") or data.get("bid_qty")),
            "ask_qty": _f(data.get("sell_quantity") or data.get("sq") or data.get("ask_qty")),
            "oi": _f(data.get("open_interest") or data.get("oi")),
            "volume": _f(data.get("volume") or data.get("v")),
            "iv": _f(data.get("iv") or data.get("implied_volatility")),
        }

    return quote_fields(None)


def build_dhan_shaped_chain(
    option_rows: pd.DataFrame,
    quotes_by_token: Mapping[str, Any],
    *,
    spot_price: float,
    strikes_around_atm: int = 60,
) -> Tuple[pd.DataFrame, Optional[float]]:
    """
    Pivot CE/PE instrument rows + quotes into a wide DHAN-style chain frame.

    Returns ``(chain_df, atm_strike)``.
    """
    if option_rows is None or option_rows.empty:
        return pd.DataFrame(columns=list(DHAN_OPTION_CHAIN_COLUMNS)), None

    rows = option_rows.copy()
    rows["SEM_STRIKE_PRICE"] = pd.to_numeric(rows["SEM_STRIKE_PRICE"], errors="coerce")
    rows["SEM_OPTION_TYPE"] = rows["SEM_OPTION_TYPE"].astype(str).str.upper().str.strip()
    rows = rows.dropna(subset=["SEM_STRIKE_PRICE"])
    strikes_all = rows["SEM_STRIKE_PRICE"].astype(float).tolist()
    atm = atm_strike_from_spot(float(spot_price or 0), strikes_all)
    if atm is None:
        return pd.DataFrame(columns=list(DHAN_OPTION_CHAIN_COLUMNS)), None

    keep = set(filter_strikes_around_atm(strikes_all, atm, strikes_around_atm))
    rows = rows.loc[rows["SEM_STRIKE_PRICE"].astype(float).isin(keep)]

    by_strike: Dict[float, Dict[str, Any]] = {}
    for _, r in rows.iterrows():
        strike = float(r["SEM_STRIKE_PRICE"])
        opt = str(r["SEM_OPTION_TYPE"])
        tok = str(r.get("SEM_SMST_SECURITY_ID") or "").strip()
        q = quote_fields(quotes_by_token.get(tok))
        slot = by_strike.setdefault(strike, {})
        if opt == "CE":
            slot["ce"] = q
        elif opt == "PE":
            slot["pe"] = q

    out_rows: List[Dict[str, Any]] = []
    empty = quote_fields(None)
    for strike in sorted(by_strike):
        ce = by_strike[strike].get("ce") or empty
        pe = by_strike[strike].get("pe") or empty
        out_rows.append(
            {
                "CE OI": ce["oi"],
                "CE Chg in OI": 0.0,
                "CE Volume": ce["volume"],
                "CE IV": ce["iv"],
                "CE LTP": ce["ltp"],
                "CE Bid Qty": ce["bid_qty"],
                "CE Bid": ce["bid"],
                "CE Ask": ce["ask"],
                "CE Ask Qty": ce["ask_qty"],
                "CE Delta": 0.0,
                "CE Theta": 0.0,
                "CE Gamma": 0.0,
                "CE Vega": 0.0,
                "Strike Price": strike,
                "PE Bid Qty": pe["bid_qty"],
                "PE Bid": pe["bid"],
                "PE Ask": pe["ask"],
                "PE Ask Qty": pe["ask_qty"],
                "PE LTP": pe["ltp"],
                "PE IV": pe["iv"],
                "PE Volume": pe["volume"],
                "PE Chg in OI": 0.0,
                "PE OI": pe["oi"],
                "PE Delta": 0.0,
                "PE Theta": 0.0,
                "PE Gamma": 0.0,
                "PE Vega": 0.0,
            }
        )

    chain = pd.DataFrame(out_rows, columns=list(DHAN_OPTION_CHAIN_COLUMNS))
    return chain, atm
