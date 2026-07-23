"""
Dhan broker: instrument loading (CSV) and lookup logic.
SEM_* schema, NSE/NFO/BSE exchange mapping, backtest dummy rows.
"""

import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

DHAN_INSTRUMENT_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
from run.config import RUN_MODE, RunMode
from core.utils.expiry_resolver import ExpiryResolver

from .base import BaseInstrumentStore, Instrument


class DhanInstrumentProvider:
    """Load Dhan instrument master from CSV (e.g. all_instrument{date}.csv)."""

    def __init__(self, csv_path: Path):
        self.csv_path = Path(csv_path).resolve()

    def load(self) -> pd.DataFrame:
        if not self.csv_path.exists():
            self._fetch_master_csv()
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Dhan instrument file not found: {self.csv_path}")
        return pd.read_csv(self.csv_path, low_memory=False)

    def _fetch_master_csv(self) -> None:
        """Download public Dhan scrip master (same source as Tradehull) if file is missing."""
        try:
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Fetching Dhan instrument master from %s -> %s",
                DHAN_INSTRUMENT_MASTER_URL,
                self.csv_path,
            )
            df = pd.read_csv(DHAN_INSTRUMENT_MASTER_URL, low_memory=False)
            if "SEM_CUSTOM_SYMBOL" in df.columns:
                df["SEM_CUSTOM_SYMBOL"] = (
                    df["SEM_CUSTOM_SYMBOL"]
                    .astype(str)
                    .str.strip()
                    .str.replace(r"\s+", " ", regex=True)
                )
            df.to_csv(self.csv_path, index=False, float_format="%.2f")
        except Exception as e:
            logger.warning("Could not auto-download Dhan instrument master: %s", e)


class DhanInstrumentStore(BaseInstrumentStore):
    """Instrument store for Dhan: SEM_* columns, NSE/NFO/BSE mapping, backtest dummies."""

    INSTRUMENT_EXCHANGE = {
        # Strategy/config uses INDEX for Nifty/BankNifty spot feed; scrip master rows use NSE for F&O.
        # Engine venue is often "DHAN" — map to NSE so overnight reconcile / GTT adopt resolve.
        "DHAN": "NSE",
        "INDEX": "NSE",
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NSE",
        "BFO": "BSE",
        "MCX": "MCX",
        "CUR": "NSE",
    }

    dummy_security_counter = 100000

    def __init__(self, csv_path: Path):
        provider = DhanInstrumentProvider(Path(csv_path))
        self.df = provider.load()
        self.df.columns = self.df.columns.str.strip()
        self.df["SEM_EXPIRY_DATE"] = pd.to_datetime(
            self.df["SEM_EXPIRY_DATE"], errors="coerce"
        )
        if hasattr(self.df["SEM_EXPIRY_DATE"].dt, "date"):
            self.df["SEM_EXPIRY_DATE"] = self.df["SEM_EXPIRY_DATE"].dt.date
        self.df["SEM_STRIKE_PRICE"] = pd.to_numeric(
            self.df["SEM_STRIKE_PRICE"], errors="coerce"
        )

    def get_tick_size(self, symbol: str) -> Optional[float]:
        """Return tick size for symbol from instrument data (SEM_TICK_SIZE); None if not found."""
        sym_upper = str(symbol).strip().upper()
        col = "SEM_TICK_SIZE" if "SEM_TICK_SIZE" in self.df.columns else None
        if col is None:
            return None
        match = self.df[
            (self.df["SEM_CUSTOM_SYMBOL"].astype(str).str.upper() == sym_upper)
            | (self.df["SEM_TRADING_SYMBOL"].astype(str).str.upper() == sym_upper)
        ]
        if match.empty:
            return None
        val = match.iloc[0].get(col)
        if val is None:
            return None
        v = pd.to_numeric(val, errors="coerce")
        if pd.isna(v):
            return None
        from core.utils.price_tick import normalize_dhan_tick_size

        return normalize_dhan_tick_size(float(v))

    def get_lot_size(self, symbol: str) -> Optional[int]:
        """Return lot size for symbol from instrument data (LOT_SIZE / SEM_LOT_UNITS); None if not found."""
        sym_upper = str(symbol).strip().upper()
        for col in ("LOT_SIZE", "SEM_LOT_UNITS"):
            if col not in self.df.columns:
                continue
            match = self.df[
                (self.df["SEM_CUSTOM_SYMBOL"].astype(str).str.upper() == sym_upper)
                | (self.df["SEM_TRADING_SYMBOL"].astype(str).str.upper() == sym_upper)
            ]
            if match.empty:
                continue
            val = match.iloc[0].get(col)
            if val is not None:
                v = pd.to_numeric(val, errors="coerce")
                if pd.notna(v) and v >= 1:
                    return int(v)
        return None

    def map_row_to_instrument(self, row) -> Instrument:
        from core.utils.price_tick import normalize_dhan_tick_size

        lot = row.get("LOT_SIZE", row.get("SEM_LOT_UNITS", 1))
        raw_tick = row.get("SEM_TICK_SIZE")
        tick_size = None
        if raw_tick is not None:
            try:
                tick_size = normalize_dhan_tick_size(float(raw_tick))
            except (TypeError, ValueError):
                tick_size = None
        return Instrument(
            trading_symbol=row["SEM_TRADING_SYMBOL"],
            custom_symbol=row["SEM_CUSTOM_SYMBOL"],
            exchange=row["SEM_EXM_EXCH_ID"],
            segment=row["SEM_SEGMENT"],
            instrument_type=row["SEM_EXCH_INSTRUMENT_TYPE"],
            expiry=row.get("SEM_EXPIRY_DATE"),
            strike=row.get("SEM_STRIKE_PRICE"),
            option_type=row.get("SEM_OPTION_TYPE"),
            lot_size=int(lot) if lot is not None else 1,
            instrument_id=row.get("INSTRUMENT_ID") or row.get("SEM_SMST_SECURITY_ID"),
            series=row.get("SEM_SERIES"),
            tick_size=tick_size,
        )

    def equity_intent_creation_details(
        self, trading_symbol: str, exchange: str
    ) -> Optional[Instrument]:
        """Resolve equity (cash) scrip to Instrument for order intent. Used by equity strategies (e.g. IPO breakout)."""
        ex = self.INSTRUMENT_EXCHANGE.get(exchange, exchange)
        # Equity: EQ type or segment/type that indicates cash equity (no expiry)
        eq_mask = (
            (self.df["SEM_TRADING_SYMBOL"] == trading_symbol)
            | (self.df["SEM_CUSTOM_SYMBOL"] == trading_symbol)
        ) & (self.df["SEM_EXM_EXCH_ID"] == ex)
        itype = self.df["SEM_EXCH_INSTRUMENT_TYPE"].astype(str).str.strip().str.upper()
        equity_mask = eq_mask & (itype == "EQ")
        df = self.df[equity_mask]
        if df.empty:
            # Fallback: same symbol+exchange and no expiry (cash segment)
            no_expiry = self.df["SEM_EXPIRY_DATE"].isna()
            df = self.df[eq_mask & no_expiry]
        if df.empty:
            if RUN_MODE in (RunMode.LIVE, RunMode.PAPER):
                logger.warning("No equity instrument found for %s on %s", trading_symbol, exchange)
            return None
        row = df.iloc[0]
        return self.map_row_to_instrument(row)

    @staticmethod
    def _option_type_to_ce_pe(option_type: Any) -> str:
        u = str(option_type or "").strip().upper()
        if u in ("CE", "CALL"):
            return "CE"
        if u in ("PE", "PUT"):
            return "PE"
        return u[:2] if len(u) >= 2 else u

    @staticmethod
    def _underlying_root_from_option_trading_symbol(trading_symbol: str) -> str:
        ts = (trading_symbol or "").strip().upper()
        if not ts:
            return ""
        if " " in ts:
            return ts.split()[0]
        if "-" in ts:
            return ts.split("-")[0]
        return ts

    @staticmethod
    def _sem_expiry_to_date(val: Any) -> Optional[date]:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        try:
            t = pd.Timestamp(val)
            if pd.isna(t):
                return None
            return t.date()
        except (TypeError, ValueError, OverflowError):
            return None

    def _pick_option_row_for_expiry(
        self,
        df: pd.DataFrame,
        expiry: Any,
        *,
        prefer_monthly: bool = False,
    ) -> pd.DataFrame:
        """Narrow candidate rows to the intended calendar expiry (and monthly series when asked)."""
        if df is None or df.empty:
            return pd.DataFrame()
        exp_dt = self._sem_expiry_to_date(expiry)
        if exp_dt is None:
            # Exact SEM_CUSTOM_SYMBOL / SEM_TRADING_SYMBOL hits are already unique;
            # accept the single row when caller has no expiry (broker place-order name).
            if len(df) == 1:
                return df
            return pd.DataFrame()

        def _row_expiry(row) -> Optional[date]:
            return self._sem_expiry_to_date(row.get("SEM_EXPIRY_DATE"))

        exact = df[df.apply(lambda r: _row_expiry(r) == exp_dt, axis=1)]
        if not exact.empty:
            out = exact
        else:
            def _same_month_year(row) -> bool:
                d = _row_expiry(row)
                return bool(d and d.month == exp_dt.month and d.year == exp_dt.year)

            out = df[df.apply(_same_month_year, axis=1)]
            if out.empty:
                return out

        if prefer_monthly and "SEM_EXPIRY_FLAG" in out.columns:
            m_only = out[
                out["SEM_EXPIRY_FLAG"].astype(str).str.upper().str.strip() == "M"
            ]
            if not m_only.empty:
                out = m_only

        if len(out) > 1:
            out = out.assign(
                _dd=out["SEM_EXPIRY_DATE"].apply(
                    lambda v: abs((_row_expiry(v) or exp_dt) - exp_dt).days
                )
            ).sort_values("_dd", ascending=True)
            out = out.drop(columns=["_dd"], errors="ignore")
        return out.head(1)

    def _resolve_option_row_fallback(
        self,
        ex: str,
        trading_symbol: str,
        expiry: Any,
        option_type: Any,
        strike: Any,
        *,
        prefer_monthly: bool = False,
    ) -> pd.DataFrame:
        """
        When SEM_TRADING_SYMBOL / SEM_CUSTOM_SYMBOL do not match ``build_option_symbol`` output
        (e.g. last-Thursday vs NSE monthly Tuesday, or compact ``NIFTY-May2026-25400-CE`` vs
        ``NIFTY 28 MAY 25400 CALL``), match by exchange + strike + CE/PE + underlying + expiry.
        Prefers SEM_EXPIRY_FLAG == M (monthly) when multiple rows share month/year.
        """
        opt = self._option_type_to_ce_pe(option_type)
        if opt not in ("CE", "PE"):
            return pd.DataFrame()
        try:
            strike_f = float(strike)
        except (TypeError, ValueError):
            return pd.DataFrame()
        root = self._underlying_root_from_option_trading_symbol(trading_symbol)
        if not root:
            return pd.DataFrame()

        exp_dt = self._sem_expiry_to_date(expiry)
        df = self.df
        sp = pd.to_numeric(df["SEM_STRIKE_PRICE"], errors="coerce")
        ot = df["SEM_OPTION_TYPE"].astype(str).str.upper().str.strip()
        base = (
            (df["SEM_EXM_EXCH_ID"] == ex)
            & (sp == strike_f)
            & (ot == opt)
            & (df["SEM_EXCH_INSTRUMENT_TYPE"].astype(str).str.upper().str.strip() == "OP")
        )
        # Underlying: SM_SYMBOL_NAME when set; else first token of SEM_CUSTOM_SYMBOL
        cust = df["SEM_CUSTOM_SYMBOL"].fillna("").astype(str).str.upper()
        first_tok = cust.str.split().str[0]
        if "SM_SYMBOL_NAME" in df.columns:
            sm = df["SM_SYMBOL_NAME"].fillna("").astype(str).str.strip().str.upper()
            base = base & (((sm != "") & (sm == root)) | ((sm == "") & first_tok.eq(root)))
        else:
            base = base & first_tok.eq(root)

        cand = df[base]
        if cand.empty:
            return cand
        if exp_dt is None:
            logger.warning(
                "Option row fallback requires expiry; got None for %s strike=%s",
                trading_symbol,
                strike,
            )
            return pd.DataFrame()

        return self._pick_option_row_for_expiry(
            cand, exp_dt, prefer_monthly=prefer_monthly
        )

    def intent_creation_details(
        self,
        trading_symbol,
        exchange,
        expiry,
        option_type,
        strike,
        *,
        prefer_monthly: bool = False,
    ) -> Optional[Instrument]:
        ex = self.INSTRUMENT_EXCHANGE.get(exchange, exchange)

        exp_dt = self._sem_expiry_to_date(expiry)
        if exp_dt is None:
            exp_dt = ExpiryResolver.parse_compact_trading_symbol_expiry(trading_symbol)
        if exp_dt is None:
            space = ExpiryResolver.parse_dhan_space_option_symbol(trading_symbol)
            if space is not None:
                _root, exp_dt, space_strike, space_opt = space
                if strike is None:
                    strike = space_strike
                if option_type is None:
                    option_type = space_opt

        if RUN_MODE in (RunMode.LIVE, RunMode.PAPER):
            root = self._underlying_root_from_option_trading_symbol(trading_symbol)
            lookup_symbols: list[str] = [str(trading_symbol).strip()]
            if exp_dt is not None and root:
                try:
                    lookup_symbols.append(
                        ExpiryResolver.build_dhan_compact_option_symbol(
                            root, exp_dt, strike, option_type
                        )
                    )
                    lookup_symbols.append(
                        ExpiryResolver.build_option_symbol(
                            root, exp_dt, strike, option_type, include_year=True
                        )
                    )
                    lookup_symbols.append(
                        ExpiryResolver.build_option_symbol(
                            root, exp_dt, strike, option_type, include_year=False
                        )
                    )
                except (TypeError, ValueError):
                    pass
            seen: set[str] = set()
            unique_lookups = []
            for sym in lookup_symbols:
                if sym and sym not in seen:
                    seen.add(sym)
                    unique_lookups.append(sym)

            df = pd.DataFrame()
            for sym in unique_lookups:
                hit = self.df[
                    (
                        (self.df["SEM_TRADING_SYMBOL"] == sym)
                        | (self.df["SEM_CUSTOM_SYMBOL"] == sym)
                    )
                    & (self.df["SEM_EXM_EXCH_ID"] == ex)
                ]
                if hit.empty:
                    continue
                narrowed = self._pick_option_row_for_expiry(
                    hit, exp_dt, prefer_monthly=prefer_monthly
                )
                if not narrowed.empty:
                    df = narrowed
                    break

            if df.empty:
                df = self._resolve_option_row_fallback(
                    ex,
                    trading_symbol,
                    exp_dt,
                    option_type,
                    strike,
                    prefer_monthly=prefer_monthly,
                )
            if df.empty:
                logger.warning(
                    "No instrument found for %s on %s expiry=%s strike=%s prefer_monthly=%s",
                    trading_symbol,
                    exchange,
                    expiry,
                    strike,
                    prefer_monthly,
                )
                return None
            inst = self.map_row_to_instrument(df.iloc[0])
            if prefer_monthly and exp_dt is not None:
                resolved = self._sem_expiry_to_date(inst.expiry)
                if resolved is None or (
                    resolved.year != exp_dt.year or resolved.month != exp_dt.month
                ):
                    logger.warning(
                        "Monthly hedge resolve mismatch: wanted %s got %s (%s)",
                        exp_dt,
                        resolved,
                        inst.trading_symbol,
                    )
                    return None
            return inst

        DhanInstrumentStore.dummy_security_counter += 1
        dummy_row = {
            "SEM_EXM_EXCH_ID": ex,
            "SEM_SEGMENT": "D",
            "SEM_SMST_SECURITY_ID": DhanInstrumentStore.dummy_security_counter,
            "SEM_TRADING_SYMBOL": trading_symbol,
            "SEM_CUSTOM_SYMBOL": trading_symbol,
            "SM_SYMBOL_NAME": trading_symbol.split()[0],
            "SEM_EXCH_INSTRUMENT_TYPE": "OP",
            "SEM_OPTION_TYPE": (
                "PE" if option_type in ("PUT", "PE") else "CE"
            ),
            "SEM_STRIKE_PRICE": strike,
            "SEM_EXPIRY_DATE": expiry,
            "SEM_LOT_UNITS": 65,
            "SEM_TICK_SIZE": 5.0,
            "SEM_SERIES": None,
        }
        return self.map_row_to_instrument(pd.Series(dummy_row))

    # Dhan WebSocket feed segment enums
    FEED_SEGMENT_INDEX = "IDX_I"
    FEED_SEGMENT_NSE_EQ = "NSE_EQ"
    FEED_SEGMENT_NSE_FNO = "NSE_FNO"
    FEED_SEGMENT_NSE_CURRENCY = "NSE_CURRENCY"
    FEED_SEGMENT_BSE_EQ = "BSE_EQ"
    FEED_SEGMENT_BSE_FNO = "BSE_FNO"
    FEED_SEGMENT_BSE_CURRENCY = "BSE_CURRENCY"
    FEED_SEGMENT_MCX = "MCX_COMM"

    INDEX_SYMBOLS = {"NIFTY", "NIFTY 50", "BANKNIFTY", "NIFTY BANK", "MIDCPNIFTY", "NIFTY MID SELECT", "FINNIFTY", "NIFTY FIN SERVICE", "SENSEX", "BANKEX", "INDIA VIX"}

    def _exchange_to_feed_segment(self, row: pd.Series) -> str:
        """Map CSV row (SEM_EXM_EXCH_ID, SEM_EXCH_INSTRUMENT_TYPE / SEM_SEGMENT) to feed ExchangeSegment."""
        exchange = str(row.get("SEM_EXM_EXCH_ID", "")).upper()
        seg = str(row.get("SEM_SEGMENT") or "").strip().upper()
        itype = str(row.get("SEM_EXCH_INSTRUMENT_TYPE") or "").strip().upper()
        if exchange == "NSE":
            if itype in ("OP", "FUT", "FUTCOM") or seg == "FNO":
                return self.FEED_SEGMENT_NSE_FNO
            if seg == "CUR" or itype == "CUR":
                return self.FEED_SEGMENT_NSE_CURRENCY
            return self.FEED_SEGMENT_NSE_EQ
        if exchange == "BSE":
            if itype in ("OP", "FUT") or seg == "FNO":
                return self.FEED_SEGMENT_BSE_FNO
            if seg == "CUR":
                return self.FEED_SEGMENT_BSE_CURRENCY
            return self.FEED_SEGMENT_BSE_EQ
        if exchange == "MCX":
            return self.FEED_SEGMENT_MCX
        return self.FEED_SEGMENT_NSE_EQ

    def get_feed_instruments(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        Resolve symbols to WebSocket feed instrument list.
        Returns list of {"ExchangeSegment": "NSE_EQ", "SecurityId": "11536", "symbol": "RELIANCE"}.
        Used by DhanWebSocketFeed. For indices (NIFTY, BANKNIFTY, etc.) uses IDX_I.
        """
        result: List[Dict[str, Any]] = []
        seen: set = set()
        symbols_upper = [s.strip().upper() for s in symbols if s]
        df = self.df
        custom_sym_col = df["SEM_CUSTOM_SYMBOL"].fillna("").astype(str).str.strip().str.upper()
        trading_sym_col = df["SEM_TRADING_SYMBOL"].fillna("").astype(str).str.strip().str.upper()
        exch_col = df.get("SEM_EXM_EXCH_ID", pd.Series([""] * len(df))).fillna("").astype(str).str.strip().str.upper()
        itype_col = df.get("SEM_EXCH_INSTRUMENT_TYPE", pd.Series([""] * len(df))).fillna("").astype(str).str.strip().str.upper()
        sm_name_col = df.get("SM_SYMBOL_NAME", pd.Series([""] * len(df))).fillna("").astype(str).str.strip().str.upper()

        for sym in symbols_upper:
            if sym in seen:
                continue
            # Index: single row per name, use IDX_I
            if sym in self.INDEX_SYMBOLS:
                match = df[
                    (custom_sym_col == sym)
                    | (trading_sym_col == sym)
                ]
                if not match.empty:
                    row = match.iloc[-1]
                    sid = int(row["SEM_SMST_SECURITY_ID"])
                    result.append({
                        "ExchangeSegment": self.FEED_SEGMENT_INDEX,
                        "SecurityId": str(sid),
                        "symbol": sym,
                    })
                    seen.add(sym)
                continue
            # Equity/FNO: take first match (or nearest expiry for FNO)
            match = df[
                (custom_sym_col == sym)
                | (trading_sym_col == sym)
            ]
            # MCX fallback: resolve underlying symbol (e.g. GOLD) to a tradable contract.
            # Prefer FUT/FUTCOM over options, then nearest expiry if available.
            if match.empty:
                mcx_underlying = df[(exch_col == "MCX") & (sm_name_col == sym)]
                if not mcx_underlying.empty:
                    preferred = mcx_underlying[
                        itype_col.loc[mcx_underlying.index].isin(["FUT", "FUTCOM"])
                    ]
                    match = preferred if not preferred.empty else mcx_underlying
            if match.empty:
                continue
            if "SEM_EXPIRY_DATE" in match.columns and match["SEM_EXPIRY_DATE"].notna().any():
                match = match.sort_values("SEM_EXPIRY_DATE").reset_index(drop=True)
            row = match.iloc[0]
            feed_seg = self._exchange_to_feed_segment(row)
            sid = int(row["SEM_SMST_SECURITY_ID"])
            result.append({
                "ExchangeSegment": feed_seg,
                "SecurityId": str(sid),
                "symbol": sym,
            })
            seen.add(sym)
        return result

    def futures_intent_creation_details(
        self, trading_symbol: str, exchange: str, expiry
    ) -> Optional[Instrument]:
        ex = self.INSTRUMENT_EXCHANGE.get(exchange, exchange)

        if RUN_MODE in (RunMode.LIVE, RunMode.PAPER):
            df = self.df[
                (
                    (self.df["SEM_TRADING_SYMBOL"] == trading_symbol)
                    | (self.df["SEM_CUSTOM_SYMBOL"] == trading_symbol)
                )
                & (self.df["SEM_EXM_EXCH_ID"] == ex)
            ]
            if df.empty:
                logger.warning("No FUT instrument found for %s on %s", trading_symbol, exchange)
                return None
            return self.map_row_to_instrument(df.iloc[0])

        DhanInstrumentStore.dummy_security_counter += 1
        dummy_row = {
            "SEM_EXM_EXCH_ID": ex,
            "SEM_SEGMENT": "D",
            "SEM_SMST_SECURITY_ID": DhanInstrumentStore.dummy_security_counter,
            "SEM_TRADING_SYMBOL": trading_symbol,
            "SEM_CUSTOM_SYMBOL": trading_symbol,
            "SM_SYMBOL_NAME": trading_symbol.split("-")[0],
            "SEM_EXCH_INSTRUMENT_TYPE": "FUT",
            "SEM_OPTION_TYPE": None,
            "SEM_STRIKE_PRICE": None,
            "SEM_EXPIRY_DATE": expiry,
            "SEM_LOT_UNITS": 65,
            "SEM_TICK_SIZE": 0.05,
            "SEM_SERIES": "FUT",
        }
        return self.map_row_to_instrument(pd.Series(dummy_row))
