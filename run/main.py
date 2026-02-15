import os
import time
from pathlib import Path

from dotenv import load_dotenv
from run.config import RUN_MODE, RunMode, STRATEGY_JOBS
from core.strategies.registry import STRATEGY_MAP
from core.engine.backtest_engine import BacktestEngine
from core.engine.live_engine import LiveEngine
from core.orderExecution.risk_manager import RiskManager
from core.data.sources.dhan_source import DhanSource
from core.data.sources.delta_source import DeltaSource
from core.data.datalayer import DhanDataProvider, DeltaDataProvider
from core.data.feeds import DeltaWebSocketFeed
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


# Select broker: "DHAN" | "DELTA" (Delta uses core/library/delta_rest_client)
BROKER_NAME = "DELTA"


def run_job(job):
    cfg = STRATEGY_MAP[job["name"]]

    if RUN_MODE.value not in cfg["allowed_modes"]:
        print(f"❌ {job['name']} not allowed in {RUN_MODE}")
        return

    # ---------- Strategy ----------
    strategy = cfg["strategy"]()

    # ---------- Data layer (feeds engines: LTP, option chain, expiry, candles) ----------
    if BROKER_NAME == "DELTA":
        delta_source = DeltaSource(testnet=True, india=False)
        data_provider = DeltaDataProvider(delta_source)
    else:
        dhan_source = DhanSource()
        data_provider = DhanDataProvider(dhan_source)

    # ---------- Order management ----------
    position_manager = PositionManager(logger=TradeLogger())
    intent_store = IntentStore()
    risk_manager = RiskManager(position_manager=position_manager)

    # ---------- Instruments (broker-specific: Dhan CSV or Delta cache in Dependencies) ----------
    current_date = time.strftime("%Y-%m-%d")
    BASE_DIR = Path(__file__).resolve().parents[1]
    deps = BASE_DIR / "Dependencies"
    if BROKER_NAME == "DELTA":
        delta_cache = deps / ("delta_instrument_" + current_date + ".csv")
        instrument_store = InstrumentStore(broker="DELTA", csv_path=delta_cache)
    else:
        expected_file = "all_instrument" + current_date + ".csv"
        instrument_store = InstrumentStore(csv_path=deps / expected_file)
    # ---------- BACKTEST ----------
    if RUN_MODE == RunMode.BACKTEST:
        bt_cfg = job["backtest"]
        broker = SimulatedBroker(
            position_manager=position_manager, intent_store=intent_store
        )
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
        load_dotenv()
        live_cfg = job["live"]
        candle_service = CandleService(data_provider)
        realtime_feed = None

        if BROKER_NAME == "DELTA":
            broker_api = DeltaBrokerApi(delta_source)
            broker = DeltaBroker(
                api=broker_api,
                position_manager=position_manager,
                intent_store=intent_store,
            )
            # Delta WebSocket feed for real-time ticker/candles (and optional orders/positions)
            delta_api_key = os.getenv("DELTA_API_KEY")
            delta_api_secret = os.getenv("DELTA_API_SECRET")
            if delta_api_key and delta_api_secret:
                realtime_feed = DeltaWebSocketFeed(
                    api_key=delta_api_key,
                    api_secret=delta_api_secret,
                    symbols=job["symbols"],
                    timeframe=job.get("backtest", {}).get("timeframe", "60"),
                    testnet=False,
                    india=True,
                    subscribe_private=True,
                )
                realtime_feed.start()
            # When Dhan WebSocket is added, create DhanWebSocketFeed here for BROKER_NAME == "DHAN"
        else:
            broker_api = DhanBrokerApi(dhan_source)
            broker = DhanBroker(
                api=broker_api,
                position_manager=position_manager,
                intent_store=intent_store,
            )
            # TODO: add DhanWebSocketFeed when Dhan WebSocket API is integrated

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
            realtime_feed=realtime_feed,
        )
        engine.start(
            exchange=live_cfg["exchange"],
            sector=live_cfg["sector"],
            rsi=live_cfg.get("rsi", "NO"),
        )


if __name__ == "__main__":
    for job in STRATEGY_JOBS:
        if job.get("enabled", True):
            run_job(job)
        else:
            print(f"⚠️ {job['name']} is disabled. Skipping.")
