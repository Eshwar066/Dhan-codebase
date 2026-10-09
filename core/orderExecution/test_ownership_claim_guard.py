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
    pm.strategy_pos = defaultdict(lambda: defaultdict(int))
    pm._trade_led_symbol_ts = {}
    pm._trade_led_baseline_qty = {}
    pm._structure_slices = defaultdict(dict)
    pm._forced_exit_partial_ts = {}
    pm.logger = None
    pm.open_positions_logger = None
    pm.on_structure_exit = None
    pm.on_main_entry_fill = None
    pm.on_main_exit_fill = None
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


class TestFillSideAndOrphanHedgePair(unittest.TestCase):
    def test_normalize_fill_side(self):
        from core.orderExecution.position_manager import normalize_fill_side

        self.assertEqual(normalize_fill_side("buy"), "BUY")
        self.assertEqual(normalize_fill_side("SELL"), "SELL")
        self.assertIsNone(normalize_fill_side(""))
        self.assertIsNone(normalize_fill_side(None))

    def test_empty_side_does_not_open_short(self):
        pm = _pm()
        inst = _inst("NIFTY-Oct2026-24500-CE")
        closed, pnl = pm.on_fill(
            instrument=inst,
            side="",
            qty=65,
            price=57.75,
            tag="HEDGE",
            action="ENTRY",
            strategy="LEAPS_RSI",
        )
        self.assertFalse(closed)
        self.assertEqual(pnl, 0.0)
        self.assertNotIn("NIFTY-Oct2026-24500-CE", pm.positions)

    def test_empty_side_then_rest_buy_stays_long(self):
        pm = _pm()
        inst = _inst("NIFTY-Oct2026-24500-CE")
        pm.on_fill(
            instrument=inst,
            side="",
            qty=65,
            price=57.75,
            tag="HEDGE",
            action="ENTRY",
            strategy="LEAPS_RSI",
        )
        pm.on_fill(
            instrument=inst,
            side="BUY",
            qty=65,
            price=57.75,
            tag="HEDGE",
            action="ENTRY",
            strategy="LEAPS_RSI",
            structure_id="LEAPS_RSI:NIFTY:RSI_LT_32:QTR",
            intent_id="16e56e8aef594572badf499e2228701d",
        )
        self.assertEqual(pm.positions[inst.trading_symbol].net_qty, 65)

    def test_hedge_buy_then_duplicate_buy_does_not_flatten(self):
        pm = _pm()
        inst = _inst("NIFTY-Oct2026-24500-CE")
        pm.on_fill(
            instrument=inst,
            side="BUY",
            qty=65,
            price=57.75,
            tag="HEDGE",
            action="ENTRY",
            strategy="LEAPS_RSI",
            structure_id="LEAPS_RSI:NIFTY:RSI_LT_32:QTR",
        )
        self.assertEqual(pm.positions[inst.trading_symbol].net_qty, 65)
        closed, _ = pm.on_fill(
            instrument=inst,
            side="BUY",
            qty=65,
            price=57.75,
            tag="HEDGE",
            action="ENTRY",
            strategy="LEAPS_RSI",
            structure_id="LEAPS_RSI:NIFTY:RSI_LT_32:QTR",
        )
        self.assertFalse(closed)
        self.assertEqual(pm.positions[inst.trading_symbol].net_qty, 130)

    def test_reconcile_pairs_leaps_calendar_hedge(self):
        pm = _pm()
        pm.merge_ownership_from_all_strategy_open_positions_csvs = MagicMock()
        pm.position_metadata["NIFTY-Dec2026-24000-CE"] = {
            "strategy": "LEAPS_RSI",
            "structure_id": "LEAPS_RSI:NIFTY:RSI_LT_32:QTR",
            "tag": "MAIN",
            "intent_id": "47b174d9350b44969b0a6425a664d4b2",
        }
        pm.reconcile_with_broker(
            {
                "NIFTY-Dec2026-24000-CE": {
                    "qty": -65,
                    "avg_price": 425.95,
                    "lot_size": 65,
                    "segment": "NFO",
                },
                "NIFTY-Oct2026-24500-CE": {
                    "qty": 65,
                    "avg_price": 57.75,
                    "lot_size": 65,
                    "segment": "NFO",
                },
            },
            strategy=None,
        )
        hedge = pm.positions["NIFTY-Oct2026-24500-CE"]
        self.assertEqual(hedge.strategy, "LEAPS_RSI")
        self.assertEqual(hedge.tag, "HEDGE")
        self.assertEqual(hedge.structure_id, "LEAPS_RSI:NIFTY:RSI_LT_32:QTR")
        self.assertEqual(hedge.net_qty, 65)


if __name__ == "__main__":
    unittest.main()
