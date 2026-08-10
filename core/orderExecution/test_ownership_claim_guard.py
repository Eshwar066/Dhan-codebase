"""Ownership claim guards: BTST must not adopt NIFTY LEAPS orphans."""

from __future__ import annotations

import csv
import os
import tempfile
import threading
import unittest
from collections import defaultdict
from unittest.mock import MagicMock

from core.orderExecution.position_manager import Position, PositionManager
from core.utils.instruments.base import Instrument


def _pm() -> PositionManager:
    pm = PositionManager.__new__(PositionManager)
    pm._lock = threading.RLock()
    pm.open_positions_csv_path = None
    pm.position_metadata = {}
    pm.positions = {}
    pm.strategy_pos = defaultdict(dict)
    pm._trade_led_symbol_ts = {}
    pm.trading_paused = False
    pm.last_recon_time = 0
    return pm


def _inst(sym: str, lot: int = 65) -> Instrument:
    return Instrument(
        trading_symbol=sym,
        custom_symbol=sym,
        exchange="NSE",
        segment="NFO",
        instrument_type="OP",
        lot_size=lot,
    )


class TestOwnershipClaimGuard(unittest.TestCase):
    def test_symbol_underlying_root_banknifty_before_nifty(self):
        self.assertEqual(
            PositionManager.symbol_underlying_root("BANKNIFTY-Aug2026-55700-PE"),
            "BANKNIFTY",
        )
        self.assertEqual(
            PositionManager.symbol_underlying_root("NIFTY-Sep2026-23500-PE"),
            "NIFTY",
        )
        self.assertEqual(
            PositionManager.symbol_underlying_root("BANKNIFTY 25 AUG 55700 PUT"),
            "BANKNIFTY",
        )

    def test_btst_may_not_claim_nifty(self):
        self.assertFalse(
            PositionManager.strategy_may_claim_symbol(
                "BankNiftyBTST", "NIFTY-Sep2026-23500-PE"
            )
        )
        self.assertTrue(
            PositionManager.strategy_may_claim_symbol(
                "BankNiftyBTST", "BANKNIFTY-Aug2026-55700-PE"
            )
        )

    def test_reconcile_btst_does_not_stamp_orphan_nifty(self):
        pm = _pm()
        pm.merge_ownership_from_all_strategy_open_positions_csvs = MagicMock()
        pm.reconcile_with_broker(
            {
                "NIFTY-Sep2026-23500-PE": {
                    "qty": -65,
                    "avg_price": 244.5,
                    "lot_size": 65,
                    "segment": "NFO",
                },
                "BANKNIFTY-Aug2026-55700-PE": {
                    "qty": 60,
                    "avg_price": 140.0,
                    "lot_size": 30,
                    "segment": "NFO",
                },
            },
            strategy="BankNiftyBTST",
            claim_underlying="BANKNIFTY",
        )
        nifty = pm.positions["NIFTY-Sep2026-23500-PE"]
        bn = pm.positions["BANKNIFTY-Aug2026-55700-PE"]
        self.assertIsNone(nifty.strategy)
        self.assertEqual(bn.strategy, "BankNiftyBTST")

    def test_merge_skips_nifty_rows_in_btst_csv(self):
        pm = _pm()
        with tempfile.TemporaryDirectory() as tmp:
            leaps = os.path.join(tmp, "LEAPS_RSI")
            btst = os.path.join(tmp, "BankNiftyBTST")
            os.makedirs(leaps)
            os.makedirs(btst)
            primary = os.path.join(leaps, "dhan_leaps_rsi_open_positions.csv")
            poison = os.path.join(btst, "dhan_leaps_rsi_open_positions.csv")
            fieldnames = [
                "timestamp",
                "engine_id",
                "venue",
                "run_mode",
                "source",
                "event",
                "symbol",
                "prev_qty",
                "net_qty",
                "avg_price",
                "strategy",
                "structure_id",
                "tag",
                "intent_id",
                "magicalLine",
                "level",
                "strategy_meta",
            ]
            with open(primary, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
            with open(poison, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerow(
                    {
                        "timestamp": "2026-08-10 07:35:54",
                        "engine_id": "dhan_leaps_rsi",
                        "venue": "DHAN",
                        "run_mode": "LIVE",
                        "source": "broker_reconcile",
                        "event": "SYNC",
                        "symbol": "NIFTY-Sep2026-23500-PE",
                        "prev_qty": "",
                        "net_qty": "-65",
                        "avg_price": "244.5",
                        "strategy": "BankNiftyBTST",
                        "structure_id": "",
                        "tag": "MAIN",
                        "intent_id": "",
                        "magicalLine": "",
                        "level": "",
                        "strategy_meta": "",
                    }
                )
                w.writerow(
                    {
                        "timestamp": "2026-08-10 07:35:54",
                        "engine_id": "dhan_leaps_rsi",
                        "venue": "DHAN",
                        "run_mode": "LIVE",
                        "source": "broker_reconcile",
                        "event": "SYNC",
                        "symbol": "BANKNIFTY-Aug2026-55700-PE",
                        "prev_qty": "",
                        "net_qty": "60",
                        "avg_price": "140",
                        "strategy": "BankNiftyBTST",
                        "structure_id": "BankNiftyBTST:BANKNIFTY:2026-08-05:PE",
                        "tag": "MAIN",
                        "intent_id": "x",
                        "magicalLine": "",
                        "level": "",
                        "strategy_meta": "",
                    }
                )
            pm.open_positions_csv_path = primary
            applied = pm.merge_ownership_from_all_strategy_open_positions_csvs(
                engine_id="dhan_leaps_rsi", logs_root=tmp
            )
            self.assertNotIn("NIFTY-Sep2026-23500-PE", pm.position_metadata)
            self.assertEqual(
                pm.position_metadata["BANKNIFTY-Aug2026-55700-PE"]["strategy"],
                "BankNiftyBTST",
            )
            self.assertGreaterEqual(applied, 0)

    def test_merge_does_not_overwrite_leaps_with_btst(self):
        pm = _pm()
        pm.position_metadata["NIFTY-Sep2026-23500-PE"] = {
            "strategy": "LEAPS_RSI",
            "structure_id": "LEAPS_RSI:NIFTY:RSI_GT_52",
            "tag": "MAIN",
        }
        pm._merge_open_positions_csv_dict(
            {
                "NIFTY-Sep2026-23500-PE": {
                    "strategy": "BankNiftyBTST",
                    "structure_id": "",
                    "tag": "MAIN",
                }
            }
        )
        meta = pm.position_metadata["NIFTY-Sep2026-23500-PE"]
        self.assertEqual(meta["strategy"], "LEAPS_RSI")
        self.assertEqual(meta["structure_id"], "LEAPS_RSI:NIFTY:RSI_GT_52")


class TestBtstExitReconcileClaim(unittest.TestCase):
    def test_exit_reconcile_passes_claim_underlying(self):
        from run.config import RunMode
        from core.strategies.BTST.BankNiftyBTST import BankNiftyBTST as mod
        from core.strategies.BTST.BankNiftyBTST.BankNiftyBTST import (
            EXIT_TIME,
            BankNiftyBTST,
        )
        from datetime import datetime
        from types import SimpleNamespace
        from zoneinfo import ZoneInfo

        IST = ZoneInfo("Asia/Kolkata")
        prev = mod.RUN_MODE
        mod.RUN_MODE = RunMode.LIVE
        try:
            strat = BankNiftyBTST()
            pm = MagicMock()
            broker = MagicMock()
            broker.get_positions_for_recon.return_value = {"X": {"qty": 1}}
            ctx = SimpleNamespace(
                position_store=pm,
                order_router=SimpleNamespace(broker=broker),
            )
            candle = {
                "symbol": "BANKNIFTY",
                "timestamp": datetime(2026, 7, 24, 3, 55, tzinfo=IST),
                "scheduled_slot": EXIT_TIME,
            }
            strat._reconcile_broker_positions_for_exit(candle, ctx)
            kwargs = pm.reconcile_with_broker.call_args.kwargs
            self.assertEqual(kwargs.get("strategy"), "BankNiftyBTST")
            self.assertEqual(kwargs.get("claim_underlying"), "BANKNIFTY")
        finally:
            mod.RUN_MODE = prev


if __name__ == "__main__":
    unittest.main()
