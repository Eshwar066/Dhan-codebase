"""Unit tests for Kotak → DHAN-shaped option chain builder."""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from core.data.data_router import DataRouter
from core.data.option_chain.kotak_chain import (
    DHAN_OPTION_CHAIN_COLUMNS,
    build_dhan_shaped_chain,
    list_option_expiries,
    option_rows_for_expiry,
    resolve_expiry,
)


class _DummyProvider:
    pass


def _sample_instruments() -> pd.DataFrame:
    rows = []
    for strike, ce_id, pe_id in (
        (24900.0, 1, 2),
        (25000.0, 3, 4),
        (25100.0, 5, 6),
    ):
        for opt, sid in (("CE", ce_id), ("PE", pe_id)):
            rows.append(
                {
                    "SEM_INSTRUMENT_NAME": "OPTIDX",
                    "SEM_CUSTOM_SYMBOL": f"NIFTY 04 AUG {int(strike)} {'CALL' if opt=='CE' else 'PUT'}",
                    "SM_SYMBOL_NAME": "",
                    "SEM_EXPIRY_DATE": "2026-08-04 14:30:00",
                    "SEM_STRIKE_PRICE": strike,
                    "SEM_OPTION_TYPE": opt,
                    "SEM_SMST_SECURITY_ID": sid,
                    "SEM_EXPIRY_FLAG": "W",
                }
            )
    rows.append(
        {
            "SEM_INSTRUMENT_NAME": "OPTIDX",
            "SEM_CUSTOM_SYMBOL": "NIFTYNXT50 04 AUG 25000 CALL",
            "SM_SYMBOL_NAME": "",
            "SEM_EXPIRY_DATE": "2026-08-04 14:30:00",
            "SEM_STRIKE_PRICE": 25000.0,
            "SEM_OPTION_TYPE": "CE",
            "SEM_SMST_SECURITY_ID": 99,
            "SEM_EXPIRY_FLAG": "W",
        }
    )
    return pd.DataFrame(rows)


class TestKotakChain(unittest.TestCase):
    def test_list_expiries_and_rows(self):
        df = _sample_instruments()
        exps = list_option_expiries(df, "NIFTY")
        self.assertEqual(exps, [date(2026, 8, 4)])
        rows = option_rows_for_expiry(df, "NIFTY", date(2026, 8, 4))
        self.assertEqual(len(rows), 6)
        self.assertEqual(set(rows["SEM_SMST_SECURITY_ID"].astype(int)), {1, 2, 3, 4, 5, 6})

    def test_build_dhan_shaped_chain_columns(self):
        df = _sample_instruments()
        rows = option_rows_for_expiry(df, "NIFTY", date(2026, 8, 4))
        quotes = {
            "3": {
                "ltp": 100.0,
                "bp": 99.0,
                "sp": 101.0,
                "bq": 50,
                "sq": 40,
                "oi": 10,
                "v": 1,
            },
            "4": {
                "ltp": 80.0,
                "bp": 79.0,
                "sp": 81.0,
                "bq": 30,
                "sq": 20,
                "oi": 12,
                "v": 2,
            },
        }
        chain, atm = build_dhan_shaped_chain(
            rows, quotes, spot_price=25010.0, strikes_around_atm=10
        )
        self.assertEqual(atm, 25000.0)
        self.assertEqual(list(chain.columns), list(DHAN_OPTION_CHAIN_COLUMNS))
        hit = chain.loc[chain["Strike Price"] == 25000.0].iloc[0]
        self.assertEqual(float(hit["CE LTP"]), 100.0)
        self.assertEqual(float(hit["PE LTP"]), 80.0)
        self.assertEqual(float(hit["CE Bid"]), 99.0)
        self.assertEqual(float(hit["PE Ask"]), 81.0)

    def test_resolve_expiry_same_month(self):
        exps = [date(2026, 8, 4), date(2026, 8, 11), date(2026, 9, 1)]
        self.assertEqual(
            resolve_expiry(
                exps, expiry_date=date(2026, 8, 25), expiry_match_same_month=True
            ),
            date(2026, 8, 11),
        )

    def test_data_router_default_api_overrides_dhan(self):
        router = DataRouter(_DummyProvider(), default_api="KOTAK")
        self.assertEqual(router.resolve_api("DHAN"), "KOTAK")
        self.assertEqual(router.resolve_api("NSE"), "NSE")
        adapter = router.from_candle({"api": "DHAN"})
        self.assertEqual(adapter.__class__.__name__, "KotakAdapter")


if __name__ == "__main__":
    unittest.main()
