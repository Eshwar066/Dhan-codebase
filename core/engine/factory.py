"""
EngineFactory: build fully isolated single-venue engines.

One engine = one broker = one OMS stack (PositionManager, RiskManager,
OrderRouter, Broker). No shared instances between venues.

Usage:
    config = EngineConfig(broker_name="DELTA", run_mode=RunMode.LIVE, ...)
    engine = EngineFactory.create_engine(config)
    # then engine.run(...) or engine.start(...)
"""

import os
from pathlib import Path
from typing import Union

from dotenv import load_dotenv

from run.config import RunMode
from run.engine_config import EngineConfig
from core.strategies.registry import STRATEGY_MAP
from core.engine.base_engine import BaseEngine
from core.engine.backtest_engine import BacktestEngine
from core.engine.live_engine import LiveEngine
from core.data.sources.dhan_source import DhanSource
from core.data.sources.delta_source import DeltaSource
from core.data.datalayer import DhanDataProvider, DeltaDataProvider
from core.data.candle_service import CandleService
from core.data.feeds import DeltaWebSocketFeed
from core.broker import (
    DhanBroker,
    DhanBrokerApi,
    DeltaBroker,
    DeltaBrokerApi,
    SimulatedBroker,
)
from core.orderExecution.order_router import OrderRouter
from core.orderExecution.intent_store import IntentStore
from core.orderExecution.position_manager import PositionManager
from core.orderExecution.risk_manager import RiskManager
from core.utils.instruments.instrument_store import InstrumentStore
from logs.logger.trade_logger import TradeLogger
from logs.engine_logger import EngineLogger


class EngineFactory:
    """
    Creates BacktestEngine or LiveEngine with a fully isolated OMS stack.
    No shared state with other engines.
    """

    @staticmethod
    def create_engine(config: EngineConfig) -> Union[BacktestEngine, LiveEngine]:
        """
        Build engine from config. Backtest vs Live is determined by config.run_mode.
        """
        if config.run_mode == RunMode.BACKTEST:
            return EngineFactory.create_backtest_engine(config)
        return EngineFactory.create_live_engine(config)

    @staticmethod
    def create_backtest_engine(config: EngineConfig) -> BacktestEngine:
        """
        Build BacktestEngine with isolated stack for config.broker_name.
        """
        cfg = STRATEGY_MAP.get(config.strategy_name)
        if not cfg:
            raise ValueError(f"Unknown strategy: {config.strategy_name}")
        if config.run_mode.value not in [m.value for m in cfg["allowed_modes"]]:
            raise ValueError(
                f"Strategy {config.strategy_name} not allowed in {config.run_mode}"
            )

        strategy = cfg["strategy"]()

        # ---------- Data (venue-specific) ----------
        if config.broker_name == "DELTA":
            source = DeltaSource(
                testnet=config.delta_testnet,
                india=config.delta_india,
            )
            data_provider = DeltaDataProvider(source)
        else:
            source = DhanSource()
            data_provider = DhanDataProvider(source)

        # ---------- OMS (isolated per engine) ----------
        logger = TradeLogger()
        position_manager = PositionManager(logger=logger)
        intent_store = IntentStore()
        risk_manager = RiskManager(position_manager=position_manager)
        broker = SimulatedBroker(
            position_manager=position_manager,
            intent_store=intent_store,
        )
        order_router = OrderRouter(
            risk_manager=risk_manager,
            broker=broker,
            intent_store=intent_store,
        )

        # ---------- Instruments (venue-specific path) ----------
        instrument_store = EngineFactory._instrument_store(config)

        return BacktestEngine(
            data_provider=data_provider,
            strategy=strategy,
            instrument_store=instrument_store,
            order_router=order_router,
            position_manager=position_manager,
        )

    @staticmethod
    def create_live_engine(config: EngineConfig) -> LiveEngine:
        """
        Build LiveEngine with isolated stack for config.broker_name.
        Dhan: DhanDataProvider, DhanBroker, no WebSocket feed (until DhanWebSocketFeed exists).
        Delta: DeltaDataProvider, DeltaBroker, DeltaWebSocketFeed.
        """
        load_dotenv()
        cfg = STRATEGY_MAP.get(config.strategy_name)
        if not cfg:
            raise ValueError(f"Unknown strategy: {config.strategy_name}")
        if config.run_mode.value not in [m.value for m in cfg["allowed_modes"]]:
            raise ValueError(
                f"Strategy {config.strategy_name} not allowed in {config.run_mode}"
            )

        strategy = cfg["strategy"]()

        # ---------- Data (venue-specific) ----------
        if config.broker_name == "DELTA":
            delta_source = DeltaSource(
                testnet=config.delta_testnet,
                india=config.delta_india,
            )
            data_provider = DeltaDataProvider(delta_source)
        else:
            dhan_source = DhanSource()
            data_provider = DhanDataProvider(dhan_source)

        # ---------- OMS (isolated per engine) ----------
        logger = TradeLogger()
        position_manager = PositionManager(logger=logger)
        intent_store = IntentStore()
        engine_logger = EngineLogger(
            engine_id=config.engine_id,
            venue=config.broker_name,
            strategy=config.strategy_name,
        )
        risk_manager = RiskManager(
            position_manager=position_manager,
            capital=config.capital,
            risk_per_trade_percent=config.risk_per_trade_percent,
            daily_max_loss=config.daily_max_loss,
            engine_logger=engine_logger,
        )

        # ---------- Broker + OrderRouter (venue-specific) ----------
        if config.broker_name == "DELTA":
            broker_api = DeltaBrokerApi(delta_source)
            broker = DeltaBroker(
                api=broker_api,
                position_manager=position_manager,
                intent_store=intent_store,
            )
        else:
            broker_api = DhanBrokerApi(dhan_source)
            broker = DhanBroker(
                api=broker_api,
                position_manager=position_manager,
                intent_store=intent_store,
            )

        order_router = OrderRouter(
            risk_manager=risk_manager,
            broker=broker,
            intent_store=intent_store,
            engine_logger=engine_logger,
            circuit_breaker_threshold=getattr(config, "circuit_breaker_threshold", 5),
            slippage_threshold_pct=getattr(config, "slippage_threshold_pct", None),
        )

        # ---------- Instruments ----------
        instrument_store = EngineFactory._instrument_store(config)

        # ---------- CandleService (uses same data_provider) ----------
        candle_service = CandleService(data_provider)

        # ---------- Realtime feed (Delta only for now) ----------
        realtime_feed = None
        if config.broker_name == "DELTA":
            api_key = os.getenv("DELTA_API_KEY")
            api_secret = os.getenv("DELTA_API_SECRET")
            if api_key and api_secret:
                timeframe = config.backtest.get("timeframe", "60")
                realtime_feed = DeltaWebSocketFeed(
                    api_key=api_key,
                    api_secret=api_secret,
                    symbols=config.symbols,
                    timeframe=timeframe,
                    testnet=config.delta_testnet,
                    india=config.delta_india,
                    subscribe_private=True,
                )
                realtime_feed.start()
        # When DhanWebSocketFeed exists, instantiate here for config.broker_name == "DHAN"

        return LiveEngine(
            strategy=strategy,
            data=data_provider,
            candle_service=candle_service,
            symbols=config.symbols,
            order_router=order_router,
            instrument_store=instrument_store,
            position_manager=position_manager,
            realtime_feed=realtime_feed,
            engine_id=config.engine_id,
            venue=config.broker_name,
            engine_logger=engine_logger,
            allowed_trading_hours=getattr(config, "allowed_trading_hours", None),
            order_state_check_interval_min=getattr(config, "order_state_check_interval_min", 0),
            memory_threshold_percent=getattr(config, "memory_threshold_percent", None),
            strategy_timeout_seconds=getattr(config, "strategy_timeout_seconds", None),
            latency_critical_ms=getattr(config, "latency_critical_ms", 150.0),
            latency_critical_cycles=getattr(config, "latency_critical_cycles", 3),
            symbol_error_threshold=getattr(config, "symbol_error_threshold", 5),
        )

    @staticmethod
    def _instrument_store(config: EngineConfig) -> InstrumentStore:
        """Build venue-specific InstrumentStore (same class, different paths)."""
        deps = config.dependencies_dir
        current_date = __import__("time").strftime("%Y-%m-%d")

        if config.broker_name == "DELTA":
            csv_path = deps / ("delta_instrument_" + current_date + ".csv")
            return InstrumentStore(broker="DELTA", csv_path=csv_path)
        expected_file = "all_instrument" + current_date + ".csv"
        return InstrumentStore(csv_path=deps / expected_file)
