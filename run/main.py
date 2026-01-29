from run.config import RUN_MODE, RunMode, STRATEGY_JOBS
from core.strategies.registry import STRATEGY_MAP
from core.engine.backtest_engine import BacktestEngine
from core.engine.live_engine import LiveEngine
from core.portfolio import Portfolio
from core.risk_manager import RiskManager
from core.data.sources.dhan_source import DhanSource
from core.broker.dhanbroker import DhanBroker
from core.data.candle_service import CandleService


def run_job(job):
    cfg = STRATEGY_MAP[job["name"]]

    if RUN_MODE.value not in cfg["allowed_modes"]:
        print(f"❌ {job['name']} not allowed in {RUN_MODE}")
        return

    # ---------- CORE ----------
    strategy = cfg["strategy"]()
    portfolio = Portfolio(job["capital"])

    # ---------- DATA / BROKER ----------
    broker_data = DhanSource()

    # ---------- BACKTEST ----------
    if RUN_MODE == RunMode.BACKTEST:
        bt_cfg = job["backtest"]

        engine = BacktestEngine(
            data_provider=broker_data,
            portfolio=portfolio,
            strategy=strategy,
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
        live_data = broker_data
        candle_service = CandleService(broker_data)
        broker = DhanBroker(dhan_source=live_data, portfolio=portfolio)
        risk_manager = RiskManager(portfolio=portfolio)

        engine = LiveEngine(
            broker=broker,
            portfolio=portfolio,
            strategy=strategy,
            risk_manager=risk_manager,
            data=live_data,
            candle_service=candle_service,
            symbols=job["symbols"],
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
