import time
from pathlib import Path

from run.config import RUN_MODE, RunMode, STRATEGY_JOBS
from core.strategies.registry import STRATEGY_MAP
from core.engine.backtest_engine import BacktestEngine
from core.engine.live_engine import LiveEngine
from core.orderExecution.risk_manager import RiskManager
from core.data.sources.dhan_source import DhanSource
from core.data.datalayer import DhanDataProvider
from core.broker import (
    DhanBroker,
    DhanBrokerApi,
    DeltaBroker,
    DeltaBrokerApi,
    SimulatedBroker,
)
from core.data.candle_service import CandleService
from core.orderExecution.order_router import OrderRouter
from core.orderExecution.intent_store import IntentStore
from core.orderExecution.position_manager import PositionManager
from core.utils.instruments.instrument_store import InstrumentStore
from logs.logger.trade_logger import TradeLogger


# Select broker: "DHAN" | "DELTA" (Delta is stub until API wired)
BROKER_NAME = "DHAN"


def run_job(job):
    cfg = STRATEGY_MAP[job["name"]]

    if RUN_MODE.value not in cfg["allowed_modes"]:
        print(f"❌ {job['name']} not allowed in {RUN_MODE}")
        return

    # ---------- Strategy ----------
    strategy = cfg["strategy"]()

    # ---------- Data layer (feeds engines: LTP, option chain, expiry, candles) ----------
    dhan_source = DhanSource()
    data_provider = DhanDataProvider(dhan_source)

    # ---------- Order management ----------
    position_manager = PositionManager(logger=TradeLogger())
    intent_store = IntentStore()
    risk_manager = RiskManager(position_manager=position_manager)

    # ---------- Instruments ----------
    current_date = time.strftime("%Y-%m-%d")
    expected_file = "all_instrument" + str(current_date) + ".csv"
    BASE_DIR = Path(__file__).resolve().parents[1]
    instrument_store = InstrumentStore(BASE_DIR / "Dependencies" / expected_file)

    # ---------- BACKTEST ----------
    if RUN_MODE == RunMode.BACKTEST:
        bt_cfg = job["backtest"]
        broker = SimulatedBroker(position_manager=position_manager, intent_store=intent_store)
        order_router = OrderRouter(
            risk_manager=risk_manager,
            broker=broker,
            intent_store=intent_store,
        )
        engine = BacktestEngine(
            data_provider=data_provider,
            strategy=strategy,
            order_router=order_router,
            instrument_store=instrument_store,
            position_manager=position_manager,
        )
        engine.run(
            symbols=job["symbols"],
            start_date=bt_cfg["start_date"],
            end_date=bt_cfg["end_date"],
            timeframe=bt_cfg["timeframe"],
            exchange=bt_cfg["exchange"],
            sector=bt_cfg["sector"],
        )

    # ---------- LIVE / PAPER ----------
    else:
        live_cfg = job["live"]
        candle_service = CandleService(data_provider)
        if BROKER_NAME == "DELTA":
            broker_api = DeltaBrokerApi(api_key="", api_secret="", testnet=True)
            broker = DeltaBroker(api=broker_api, position_manager=position_manager, intent_store=intent_store)
        else:
            broker_api = DhanBrokerApi(dhan_source)
            broker = DhanBroker(api=broker_api, position_manager=position_manager, intent_store=intent_store)
        order_router = OrderRouter(
            risk_manager=risk_manager,
            broker=broker,
            intent_store=intent_store,
        )
        engine = LiveEngine(
            strategy=strategy,
            data=data_provider,
            candle_service=candle_service,
            symbols=job["symbols"],
            order_router=order_router,
            instrument_store=instrument_store,
            position_manager=position_manager,
        )
        engine.start(
            exchange=live_cfg["exchange"],
            sector=live_cfg["sector"],
            rsi=live_cfg["rsi"],
        )


if __name__ == "__main__":
    for job in STRATEGY_JOBS:
        if job.get("enabled", True):
            run_job(job)
        else:
            print(f"⚠️ {job['name']} is disabled. Skipping.")
