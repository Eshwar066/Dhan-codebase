# core/strategies/registry.py
from run.config import RunMode
from core.strategies.Inside_bar_candle.inside_bar import InsideBarStrategy
from core.strategies.Leaps.LeapsQuatery_RSI_52_32 import LeapsQuarterly
from core.instruments import EquityInstrument, OptionInstrument


INSTRUMENT_MAP = {
    "EQUITY": EquityInstrument,
    "OPTION": OptionInstrument,
}

STRATEGY_MAP = {
    "INSIDE_BAR": {
        "strategy": InsideBarStrategy,
        "instrument": "EQUITY",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.PAPER,
            RunMode.LIVE,
        ],
    },
    "LEAPS_RSI": {
        "strategy": LeapsQuarterly,
        "instrument": "OPTION",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.LIVE,
        ],
    },
}
