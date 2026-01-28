import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from core.live import LiveEngine
from core.strategies.LeapsQuatery_RSI_52_32.live_adapter import LiveStrategyAdapter
from core.strategies.LeapsQuatery_RSI_52_32.main import LeapsQuaterly
from core.portfolio.live_portfolio import LivePortfolio
from core.risk.manager import RiskManager
from core.broker.dhan import DhanBroker
from core.data.live_data import LiveData

load_dotenv()
client_code = os.getenv("DHAN_CLIENT_CODE")
token_id = os.getenv("DHAN_ACCESS_TOKEN")
tsl = Tradehull(client_code, token_id)
# --------------------
# Infrastructure
# --------------------
broker = DhanBroker()
data = LiveData()
portfolio = LivePortfolio(broker)

# --------------------
# Strategy + Adapter
# --------------------
strategy = LeapsQuaterly()

strategy_adapter = LiveStrategyAdapter(
    strategy=strategy,
    data_provider=data,
    portfolio=portfolio,
    symbol="NIFTY",  # ✅ REQUIRED
    max_candles=200,
)

# 🔥 VERY IMPORTANT
strategy_adapter.warmup(interval="1h")

# --------------------
# Risk + Engine
# --------------------
risk_manager = RiskManager()

engine = LiveEngine(
    broker=broker,
    strategy_adapter=strategy_adapter,
    risk_manager=risk_manager,
    data=data,
)

engine.start()
