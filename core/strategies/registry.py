# core/strategies/registry.py
from run.config import RunMode
from core.strategies.Leaps.LeapsQuatery_RSI_52_32 import LeapsQuarterly
from core.strategies.MagicalLines.MagicalLines import MagicalLines
from core.strategies.MagicalLines.NiftyIntradayMagicalLine import NiftyIntradayMagicalLine
from core.strategies.Intraday.oneDayMagicalLine import OneDayMagicalLine
from core.strategies.Futures.Futures_EMA.Futures_EMA import FuturesEMAHighLow
from core.strategies.Futures.Futures_EMA_Momentum.Futures_EMA_Momentum import (
    FuturesEMAMomentum,
)
from core.strategies.PipelineTest.signal_flood_test import SignalFloodTestStrategy
from core.strategies.Equity.IPOBreakout.IPOBreakout import IPOBreakout
from core.instruments import EquityInstrument, OptionInstrument, FutureInstrument


INSTRUMENT_MAP = {
    "EQUITY": EquityInstrument,
    "OPTION": OptionInstrument,
    "FUTURE": FutureInstrument,
}

STRATEGY_MAP = {
    "LEAPS_RSI": {
        "strategy": LeapsQuarterly,
        "instrument": "OPTION",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.LIVE,
        ],
    },
    "MagicalLines": {
        "strategy": MagicalLines,
        "instrument": "OPTION",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.PAPER,
            RunMode.LIVE,
        ],
    },
    "NiftyIntradayMagicalLine": {
        "strategy": NiftyIntradayMagicalLine,
        "instrument": "OPTION",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.PAPER,
            RunMode.LIVE,
        ],
    },
    "OneDayMagicalLine": {
        "strategy": OneDayMagicalLine,
        "instrument": "OPTION",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.PAPER,
            RunMode.LIVE,
        ],
    },
    "FuturesEMAHighLow": {
        "strategy": FuturesEMAHighLow,
        "instrument": "FUTURE",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.PAPER,
            RunMode.LIVE,
        ],
    },
    "IPOBreakout": {
        "strategy": IPOBreakout,
        "instrument": "EQUITY",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.PAPER,
            RunMode.LIVE,
        ],
    },
    "Futures_EMA_Momentum": {
        "strategy": FuturesEMAMomentum,
        "instrument": "FUTURE",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.PAPER,
            RunMode.LIVE,
        ],
    },
    "SignalFloodTest": {
        "strategy": SignalFloodTestStrategy,
        "instrument": "FUTURE",
        "allowed_modes": [
            RunMode.PAPER,
            RunMode.LIVE,
        ],
    },
}
