# core/strategies/registry.py
from run.config import RunMode
from core.strategies.Inside_bar_candle.inside_bar import InsideBarStrategy
from core.strategies.Leaps.LeapsQuatery_RSI_52_32 import LeapsQuarterly
from core.strategies.Futures.Futures_EMA.Futures_EMA import FuturesEMAHighLow
from core.instruments import EquityInstrument, OptionInstrument, FutureInstrument


INSTRUMENT_MAP = {
    "EQUITY": EquityInstrument,
    "OPTION": OptionInstrument,
    "FUTURE": FutureInstrument,
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
    "FuturesEMAHighLow": {
        "strategy": FuturesEMAHighLow,
        "instrument": "FUTURE",
        "allowed_modes": [
            RunMode.BACKTEST,
            RunMode.PAPER,
            RunMode.LIVE,
        ],
    },
}
