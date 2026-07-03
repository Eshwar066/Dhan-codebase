# core/strategies/registry.py
# Strategy-level defaults (symbols, live/backtest, eval mode): run/strategy_profiles.py
from run.config import RunMode
from core.strategies.Leaps.LeapsQuatery_RSI_52_32 import LeapsQuarterly
from core.strategies.MagicalLines.MagicalLines import MagicalLines
from core.strategies.MagicalLines.NiftyIntradayMagicalLine import NiftyIntradayMagicalLine
from core.strategies.crypto.oneDayMagicalLine import OneDayMagicalLine
from core.strategies.OpenIntrest.OIPostionalBuy.OIPosBuy import OIPositionalBuy
from core.strategies.OpenIntrest.optionbuildup import OptionBuildup
from core.strategies.Futures.Futures_EMA.Futures_EMA import FuturesEMAHighLow
from core.strategies.BTST.BankNiftyBTST.BankNiftyBTST import BankNiftyBTST
from core.strategies.Futures.Futures_EMA_Momentum.Futures_EMA_Momentum import (
    FuturesEMAMomentum,
)
from core.strategies.crypto.RSIBreadAndButter.RSIBreadAndButter import RSIBreadAndButter
from core.strategies.crypto.LiquiditySweepStrategy.LiquiditySweepStrategy import (
    LiquiditySweepStrategy,
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
            RunMode.PAPER,
        ],
    },
    "BankNiftyBTST": {
        "strategy": BankNiftyBTST,
        "instrument": "OPTION",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.PAPER,
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
    "OIPositionalBuy": {
        "strategy": OIPositionalBuy,
        "instrument": "OPTION",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.PAPER,
            RunMode.LIVE,
        ],
    },
    "OptionBuildup": {
        "strategy": OptionBuildup,
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
    "RSIBreadAndButter": {
        "strategy": RSIBreadAndButter,
        "instrument": "FUTURE",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.PAPER,
            RunMode.LIVE,
        ],
    },
    "LiquiditySweepStrategy": {
        "strategy": LiquiditySweepStrategy,
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
