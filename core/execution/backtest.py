import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import os
import sys
from dotenv import load_dotenv
from Dhan_Tradehull import Tradehull
from core.strategies.Inside_bar_candle.inside_bar import InsideBarStrategy
from core.strategies.Inside_bar_candle.historical_dhan import HistoricalDhanData
from core.engine import BacktestEngine
from core.portfolio import Portfolio
from core.instruments import EquityInstrument

load_dotenv()
client_code = os.getenv("DHAN_CLIENT_CODE")
token_id = os.getenv("DHAN_ACCESS_TOKEN")
tsl = Tradehull(client_code, token_id)

data = HistoricalDhanData(tsl)

engine = BacktestEngine(
    data_provider=data,
    portfolio=Portfolio(100000),
    instrument=EquityInstrument(),
    strategy=InsideBarStrategy(),
)

engine.run(
    symbols=["INFY", "ITC", "HINDALCO"],
    start_date="2025-12-01",
    end_date="2025-12-31",
)
