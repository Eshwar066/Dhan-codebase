"""
Dhan broker: instrument loading (CSV) and lookup logic.
SEM_* schema, NSE/NFO/BSE exchange mapping, backtest dummy rows.
"""

from pathlib import Path
from typing import Optional

import pandas as pd
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

    def map_row_to_instrument(self, row) -> Instrument:
        return Instrument(
            trading_symbol=row["SEM_TRADING_SYMBOL"],
            custom_symbol=row["SEM_CUSTOM_SYMBOL"],
            exchange=row["SEM_EXM_EXCH_ID"],
            segment=row["SEM_SEGMENT"],
            instrument_type=row["SEM_EXCH_INSTRUMENT_TYPE"],
            expiry=row.get("SEM_EXPIRY_DATE"),
            strike=row.get("SEM_STRIKE_PRICE"),
            option_type=row.get("SEM_OPTION_TYPE"),
            lot_size=row.get("LOT_SIZE", 1),
            instrument_id=row.get("INSTRUMENT_ID"),
            series=row.get("SEM_SERIES"),
        )

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
                print(f"❌ No instrument found for {trading_symbol} on {exchange}")
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
                print(f"❌ No FUT instrument found for {trading_symbol} on {exchange}")
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
