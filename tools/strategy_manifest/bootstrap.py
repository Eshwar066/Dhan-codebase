"""Bootstrap strategy.yaml files (skip if manifest already exists)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.strategy_manifest.loader import STRATEGIES_ROOT

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


def _opt_chain(interval: str, *, live: bool = False) -> Dict[str, Any]:
    block: Dict[str, Any] = {
        "exchange": "NSE",
        "interval": interval,
        "segment": "OPT",
    }
    if not live:
        block["api"] = "DHAN"
        block["expiry_flag"] = "MONTHLY"
    return {"data": {"option_chain": block}}


def _empty() -> Dict[str, Any]:
    return {"data": {}}


def _m(
    *,
    id: str,
    module: str,
    class_name: str,
    instrument: str,
    modes: List[str],
    path: str,
    symbols: Optional[List[str]] = None,
    exchange: str = "NSE",
    venue: str = "DHAN",
    api: Optional[str] = None,
    timeframe: Optional[str] = "60",
    backtest_timeframe: Optional[str] = None,
    schedule: Optional[Dict[str, Any]] = None,
    execution: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
    delta: Optional[Dict[str, Any]] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    documentation: Optional[Dict[str, Any]] = None,
    aliases: Optional[List[str]] = None,
) -> Dict[str, Any]:
    broker: Dict[str, Any] = {"venue": venue}
    if api:
        broker["api"] = api
    if delta:
        broker["delta"] = delta
    raw: Dict[str, Any] = {
        "id": id,
        "implementation": {"module": module, "class": class_name},
        "instrument": instrument,
        "allowed_modes": modes,
        "broker": broker,
        "symbols": symbols,
        "exchange": exchange,
        "timeframe": timeframe,
        "schedule": schedule or {"eval_mode": "live_feed"},
        "data": data or {"default": _empty()},
        "profile": profile or {},
        "dependencies": dependencies or {},
        "documentation": documentation or {},
        "_path": path,
    }
    if backtest_timeframe is not None:
        raw["backtest_timeframe"] = backtest_timeframe
    if execution:
        raw["execution"] = execution
    if aliases:
        raw["aliases"] = aliases
    return raw


BOOTSTRAP_MANIFESTS: List[Dict[str, Any]] = [
    _m(
        id="LEAPS_RSI",
        module="core.strategies.Leaps.LeapsQuatery_RSI_52_32",
        class_name="LeapsQuarterly",
        instrument="OPTION",
        modes=["BACKTEST", "PAPER", "LIVE"],
        path="Leaps/strategy.yaml",
        symbols=["NIFTY"],
        api="DHAN",
        timeframe="60",
        data={
            "backtest": _opt_chain("60"),
            "paper": _opt_chain("60"),
            "live": _opt_chain("1", live=True),
        },
        profile={
            "live": {"exchange": "INDEX", "sector": "YES", "rsi": "YES"},
            "backtest": {
                "start_date": "2026-01-01",
                "end_date": "2026-05-24",
                "timeframe": "60",
                "exchange": "INDEX",
                "sector": "YES",
            },
        },
        dependencies={
            "mixins": ["IndiaMktMixins"],
            "required_context": ["option_chain"],
            "expiry_type": "MONTHLY",
        },
        documentation={
            "title": "LEAPS RSI",
            "overview": "NIFTY monthly option selling on 1h RSI with hedge protection.",
            "run_command": "python -m run.main --engine-id dhan_leaps_rsi",
        },
    ),
    _m(
        id="BankNiftyBTST",
        module="core.strategies.BTST.BankNiftyBTST.BankNiftyBTST",
        class_name="BankNiftyBTST",
        instrument="OPTION",
        modes=["BACKTEST", "PAPER", "LIVE"],
        path="BTST/BankNiftyBTST/strategy.yaml",
        symbols=["BANKNIFTY"],
        api="DHAN",
        timeframe=None,
        backtest_timeframe="5",
        schedule={
            "eval_mode": "scheduled",
            "times": ["09:20", "15:20", "09:25"],
        },
        execution={
            "mode": "HYBRID_GTT",
            "gtt_fallback": {
                "trigger_field": "ask",
                "trigger_op": "<=",
                "active_until": "15:20",
            },
            "bracket_leg_tags": ["MAIN_SL"],
        },
        data={
            "backtest": _opt_chain("5"),
            "paper": _opt_chain("5"),
            "live": _opt_chain("1", live=True),
        },
        profile={
            "live": {"exchange": "INDEX", "sector": "YES"},
            "backtest": {
                "start_date": "2026-01-02",
                "end_date": "2026-02-19",
                "timeframe": "5",
                "exchange": "INDEX",
                "sector": "YES",
            },
        },
        dependencies={
            "mixins": ["IndiaMktMixins"],
            "required_context": ["option_chain"],
            "expiry_type": "MONTHLY",
            "meta_key": "banknifty_btst",
        },
        documentation={
            "title": "Bank Nifty BTST",
            "overview": "Buy CE+PE near 100 premium; SL at 50% of limit; exit T+1 9:25 IST.",
            "run_command": "python -m run.main --engine-id dhan_banknifty_btst",
        },
    ),
    _m(
        id="MagicalLines",
        module="core.strategies.MagicalLines.MagicalLines",
        class_name="MagicalLines",
        instrument="OPTION",
        modes=["BACKTEST", "PAPER", "LIVE"],
        path="MagicalLines/strategy.yaml",
        symbols=["NIFTY"],
        api="DHAN",
        timeframe="DAY",
        data={
            "backtest": _opt_chain("DAY"),
            "paper": _opt_chain("DAY"),
            "live": _opt_chain("1", live=True),
        },
        profile={
            "live": {"exchange": "INDEX", "sector": "YES"},
            "backtest": {
                "start_date": "2026-01-01",
                "end_date": "2026-02-19",
                "timeframe": "DAY",
                "exchange": "INDEX",
                "sector": "YES",
            },
        },
        dependencies={"mixins": ["IndiaMktMixins"], "expiry_type": "MONTHLY"},
        documentation={"title": "Magical Lines", "overview": "NIFTY daily magical-line options."},
    ),
    _m(
        id="NiftyIntradayMagicalLine",
        module="core.strategies.MagicalLines.NiftyIntradayMagicalLine",
        class_name="NiftyIntradayMagicalLine",
        instrument="OPTION",
        modes=["BACKTEST", "PAPER", "LIVE"],
        path="MagicalLines/NiftyIntradayMagicalLine/strategy.yaml",
        symbols=["NIFTY"],
        api="DHAN",
        timeframe="15",
        data={
            "backtest": _opt_chain("15"),
            "paper": _opt_chain("15"),
            "live": _opt_chain("1", live=True),
        },
        profile={
            "live": {"exchange": "INDEX", "sector": "YES"},
            "backtest": {
                "start_date": "2026-01-02",
                "end_date": "2026-02-19",
                "timeframe": "15",
                "exchange": "INDEX",
                "sector": "YES",
            },
        },
        dependencies={
            "mixins": ["IndiaMktMixins"],
            "meta_key": "nifty_intraday_magical_line",
        },
        documentation={"title": "Nifty Intraday Magical Line", "overview": "15m NIFTY intraday magical-line options."},
    ),
    _m(
        id="OneDayMagicalLine",
        module="core.strategies.crypto.oneDayMagicalLine",
        class_name="OneDayMagicalLine",
        instrument="OPTION",
        modes=["BACKTEST", "PAPER", "LIVE"],
        path="crypto/oneDayMagicalLine/strategy.yaml",
        symbols=["BTCUSD"],
        venue="DELTA",
        api="DELTA",
        timeframe="60",
        delta={"india": True, "testnet": False, "leverage": 10},
        data={"default": _empty()},
        profile={
            "live": {"exchange": "DELTA", "sector": "YES"},
            "backtest": {
                "start_date": "2026-02-01",
                "end_date": "2026-02-26",
                "timeframe": "60",
                "exchange": "DELTA",
                "sector": "YES",
            },
        },
        dependencies={
            "mixins": ["IndiaMktMixins"],
            "meta_key": "one_day_magical_line",
            "meta_aliases": {"one_day_ml1": "one_day_magical_line"},
        },
        documentation={
            "title": "One Day Magical Line",
            "overview": "Delta BTCUSD hourly magical-line positional strategy.",
            "run_command": "python -m run.main --engine-id delta_oneday_magicalline",
        },
    ),
    _m(
        id="OIPositionalBuy",
        module="core.strategies.OpenIntrest.OIPostionalBuy.OIPosBuy",
        class_name="OIPositionalBuy",
        instrument="OPTION",
        modes=["BACKTEST", "PAPER", "LIVE"],
        path="OpenIntrest/OIPostionalBuy/strategy.yaml",
        symbols=["NIFTY"],
        api="DHAN",
        timeframe="15",
        data={
            "backtest": _opt_chain("15"),
            "paper": _opt_chain("15"),
            "live": _opt_chain("15"),
        },
        profile={
            "live": {"exchange": "INDEX", "sector": "YES"},
            "backtest": {
                "start_date": "2026-04-01",
                "end_date": "2026-04-28",
                "timeframe": "15",
                "exchange": "INDEX",
                "sector": "YES",
            },
        },
        dependencies={
            "mixins": ["IndiaMktMixins"],
            "required_context": ["option_chain"],
            "meta_key": "oi_positional_buy",
        },
        documentation={"title": "OI Positional Buy", "overview": "NIFTY OI buildup positional options."},
    ),
    _m(
        id="OptionBuildup",
        module="core.strategies.OpenIntrest.optionbuildup",
        class_name="OptionBuildup",
        instrument="OPTION",
        modes=["BACKTEST", "PAPER", "LIVE"],
        path="OpenIntrest/optionbuildup/strategy.yaml",
        symbols=["NIFTY"],
        api="DHAN",
        timeframe="15",
        data={
            "backtest": _opt_chain("15"),
            "paper": _opt_chain("15"),
            "live": _opt_chain("15"),
        },
        profile={
            "live": {"exchange": "INDEX", "sector": "YES"},
            "backtest": {
                "start_date": "2026-04-01",
                "end_date": "2026-04-28",
                "timeframe": "15",
                "exchange": "INDEX",
                "sector": "YES",
            },
        },
        dependencies={"mixins": ["IndiaMktMixins"]},
        documentation={"title": "Option Buildup", "overview": "NIFTY OI buildup scanner."},
    ),
    _m(
        id="FuturesEMAHighLow",
        module="core.strategies.Futures.Futures_EMA.Futures_EMA",
        class_name="FuturesEMAHighLow",
        instrument="FUTURE",
        modes=["BACKTEST", "PAPER", "LIVE"],
        path="Futures/Futures_EMA/strategy.yaml",
        symbols=["NIFTY"],
        api="DHAN",
        timeframe="60",
        data={"default": _empty()},
        profile={
            "live": {"exchange": "INDEX", "sector": "YES"},
            "backtest": {
                "start_date": "2024-02-01",
                "end_date": "2026-03-02",
                "timeframe": "60",
                "exchange": "INDEX",
                "sector": "YES",
            },
        },
        documentation={"title": "Futures EMA High/Low", "overview": "NIFTY index futures EMA band strategy."},
    ),
    _m(
        id="IPOBreakout",
        module="core.strategies.Equity.IPOBreakout.IPOBreakout",
        class_name="IPOBreakout",
        instrument="EQUITY",
        modes=["BACKTEST", "PAPER", "LIVE"],
        path="Equity/IPOBreakout/strategy.yaml",
        symbols=None,
        api="DHAN",
        timeframe="DAY",
        data={
            "backtest": {"data": {"ohlc": {"exchange": "NSE", "interval": "5"}}},
            "paper": {"data": {"ohlc": {"exchange": "NSE", "interval": "5"}}},
            "live": {"data": {"ohlc": {"exchange": "NSE", "interval": "5"}}},
        },
        profile={
            "live": {
                "exchange": "NSE",
                "sector": "NO",
                "ipo_days": 365,
                "ipo_filter": {"price_above": 200, "volume_above": 500000},
                "ipo_max_symbols": 50,
            },
            "backtest": {
                "start_date": "2022-01-01",
                "end_date": "2026-02-20",
                "timeframe": "DAY",
                "exchange": "NSE",
                "sector": "NO",
                "ipo_days": 365,
                "ipo_filter": {"price_above": 200, "volume_above": 500000},
                "ipo_max_symbols": 50,
                "ipo_fallback_symbols": ["RELIANCE"],
            },
        },
        dependencies={
            "mixins": ["IndiaMktMixins"],
            "required_context": ["instrument_store"],
        },
        aliases=["IPOAnchorVWAP"],
        documentation={
            "title": "IPO Breakout",
            "overview": "Dhan IPO listings: anchor VWAP + staged scale-in.",
            "run_command": "python -m run.main --engine-id dhan_ipo_breakout",
        },
    ),
    _m(
        id="Futures_EMA_Momentum",
        module="core.strategies.Futures.Futures_EMA_Momentum.Futures_EMA_Momentum",
        class_name="FuturesEMAMomentum",
        instrument="FUTURE",
        modes=["BACKTEST", "PAPER", "LIVE"],
        path="Futures/Futures_EMA_Momentum/strategy.yaml",
        symbols=["BTCUSD"],
        venue="DELTA",
        api="DELTA",
        timeframe="60",
        delta={"india": True, "testnet": False, "leverage": 1},
        data={"default": _empty()},
        profile={
            "live": {"exchange": "INDEX", "sector": "YES"},
            "backtest": {
                "start_date": "2024-09-01",
                "end_date": "2026-03-13",
                "timeframe": "60",
                "exchange": "INDEX",
                "sector": "YES",
            },
        },
        documentation={
            "title": "Futures EMA Momentum",
            "overview": "Delta crypto futures EMA momentum.",
            "run_command": "python -m run.main --engine-id delta_futures_ema_momentum",
        },
    ),
    _m(
        id="RSIBreadAndButter",
        module="core.strategies.crypto.RSIBreadAndButter.RSIBreadAndButter",
        class_name="RSIBreadAndButter",
        instrument="FUTURE",
        modes=["BACKTEST", "PAPER", "LIVE"],
        path="crypto/RSIBreadAndButter/strategy.yaml",
        symbols=["BTCUSD"],
        venue="DELTA",
        api="DELTA",
        timeframe="1",
        delta={"india": True, "testnet": False, "leverage": 5},
        data={"default": _empty()},
        profile={
            "live": {"exchange": "DELTA", "sector": "YES"},
            "backtest": {
                "start_date": "2026-07-02",
                "end_date": "2026-07-03",
                "timeframe": "1",
                "exchange": "DELTA",
                "sector": "YES",
            },
        },
        dependencies={
            "mixins": ["MarketStructureMixin", "IndiaMktMixins"],
            "meta_key": "rsi_bread_butter",
        },
        documentation={
            "title": "RSI Bread and Butter",
            "overview": "Delta BTCUSD 1m RSI divergence + structure entries.",
            "run_command": "python -m run.main --engine-id delta_rsi_bread_butter",
        },
    ),
    _m(
        id="LiquiditySweepStrategy",
        module="core.strategies.crypto.LiquiditySweepStrategy.LiquiditySweepStrategy",
        class_name="LiquiditySweepStrategy",
        instrument="FUTURE",
        modes=["BACKTEST", "PAPER", "LIVE"],
        path="crypto/LiquiditySweepStrategy/strategy.yaml",
        symbols=["BTCUSD", "ETHUSD"],
        venue="DELTA",
        api="DELTA",
        timeframe="1",
        delta={"india": True, "testnet": False, "leverage": 5},
        data={"default": _empty()},
        profile={
            "live": {"exchange": "DELTA", "sector": "YES"},
            "backtest": {
                "start_date": "2026-06-02",
                "end_date": "2026-07-03",
                "timeframe": "1",
                "exchange": "DELTA",
                "sector": "YES",
            },
        },
        dependencies={
            "mixins": ["MarketStructureMixin", "IndiaMktMixins"],
            "meta_key": "liquidity_sweep",
        },
        documentation={
            "title": "Liquidity Sweep",
            "overview": "Delta crypto PDH/PDL sweep + reversal sub-strategies.",
        },
    ),
    _m(
        id="SignalFloodTest",
        module="core.strategies.PipelineTest.signal_flood_test",
        class_name="SignalFloodTestStrategy",
        instrument="FUTURE",
        modes=["PAPER", "LIVE"],
        path="PipelineTest/strategy.yaml",
        symbols=None,
        api="DHAN",
        timeframe="1",
        data={"default": _empty()},
        profile={
            "live": {"exchange": "INDEX", "sector": "YES"},
            "backtest": {
                "start_date": "2024-03-20",
                "end_date": "2024-03-25",
                "timeframe": "1",
                "exchange": "INDEX",
                "sector": "YES",
            },
        },
        documentation={
            "title": "Signal Flood Test",
            "overview": "OMS pipeline stress test — not for production.",
        },
    ),
]


def bootstrap_manifests(*, force: bool = False) -> List[Path]:
    if yaml is None:
        raise RuntimeError("PyYAML required: pip install PyYAML")

    written: List[Path] = []
    for raw in BOOTSTRAP_MANIFESTS:
        rel = raw["_path"]
        payload = {k: v for k, v in raw.items() if k != "_path"}
        dest = STRATEGIES_ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and not force:
            continue
        dest.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        written.append(dest)
    return written
