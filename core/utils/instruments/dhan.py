"""
Dhan broker: instrument loading (CSV) and lookup logic.
SEM_* schema, NSE/NFO/BSE exchange mapping, backtest dummy rows.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)
from run.config import RUN_MODE, RunMode

from .base import BaseInstrumentStore, Instrument


class DhanInstrumentProvider:
    """Load Dhan instrument master from CSV (e.g. all_instrument{date}.csv)."""

    def __init__(self, csv_path: Path):
        self.csv_path = Path(csv_path).resolve()

    def load(self) -> pd.DataFrame:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Dhan instrument file not found: {self.csv_path}")
        return pd.read_csv(self.csv_path, low_memory=False)


class DhanInstrumentStore(BaseInstrumentStore):
    """Instrument store for Dhan: SEM_* columns, NSE/NFO/BSE mapping, backtest dummies."""

    INSTRUMENT_EXCHANGE = {
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
        return None if pd.isna(v) else float(v)

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
        lot = row.get("LOT_SIZE", row.get("SEM_LOT_UNITS", 1))
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
            instrument_id=row.get("INSTRUMENT_ID"),
            series=row.get("SEM_SERIES"),
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

    def intent_creation_details(
        self, trading_symbol, exchange, expiry, option_type, strike
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
                logger.warning("No instrument found for %s on %s", trading_symbol, exchange)
                return None
            return self.map_row_to_instrument(df.iloc[0])

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
        for sym in symbols_upper:
            if sym in seen:
                continue
            # Index: single row per name, use IDX_I
            if sym in self.INDEX_SYMBOLS:
                match = df[
                    (df["SEM_CUSTOM_SYMBOL"].str.upper() == sym)
                    | (df["SEM_TRADING_SYMBOL"].str.upper() == sym)
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
                (df["SEM_CUSTOM_SYMBOL"].str.upper() == sym)
                | (df["SEM_TRADING_SYMBOL"].str.upper() == sym)
            ]
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
