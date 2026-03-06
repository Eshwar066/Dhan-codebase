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
import queue
from datetime import datetime
from pathlib import Path
from typing import Union
import pdb

from dotenv import load_dotenv

from run.config import RunMode
from run.engine_config import EngineConfig
from core.strategies.registry import STRATEGY_MAP
from core.engine.base_engine import BaseEngine
from core.engine.backtest_engine import BacktestEngine
from core.engine.live_engine import LiveEngine
from core.data.sources.dhan_source import DhanSource
from core.data.sources.delta_source import DeltaSource, DELTA_BASE_URL_INDIA_TEST
from core.data.datalayer import DhanDataProvider, DeltaDataProvider
from core.data.candle_service import CandleService
from core.data.candle_aggregator import CandleAggregator
from core.data.feeds import DeltaWebSocketFeed, DhanWebSocketFeed
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
from core.utils.delta_env import get_delta_credentials
from core.utils.instruments.instrument_store import InstrumentStore
from logs.logger.trade_logger import TradeLogger
from logs.engine_logger import EngineLogger

try:
    from core.universe.equity_universe_service import EquityUniverseService
except ImportError:
    EquityUniverseService = None


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
        # ---------- Instruments (needed by OrderRouter) ----------
        instrument_store = EngineFactory._instrument_store(config)
        broker = SimulatedBroker(
            position_manager=position_manager,
            intent_store=intent_store,
        )
        order_router = OrderRouter(
            risk_manager=risk_manager,
            broker=broker,
            intent_store=intent_store,
            position_manager=position_manager,
            instrument_store=instrument_store,
        )
        broker.set_order_router(order_router)

        # ---------- Universe (DHAN equity strategies only) ----------
        universe_service = EngineFactory._universe_service(
            config, data_provider, instrument_store, engine_logger=None
        )

        # ---------- IPOBreakout: resolve symbols from universe if not set ----------
        EngineFactory._resolve_ipo_symbols(config, universe_service)
        return BacktestEngine(
            data_provider=data_provider,
            strategy=strategy,
            instrument_store=instrument_store,
            order_router=order_router,
            position_manager=position_manager,
            universe_service=universe_service,
            broker_name=config.broker_name,
        )

    @staticmethod
    def create_live_engine(config: EngineConfig) -> LiveEngine:
        """
        Build LiveEngine with isolated stack for config.broker_name.
        PAPER: SimulatedBroker (same stack and logs as LIVE; no real orders).
        LIVE + Dhan: DhanDataProvider, DhanBroker, DhanWebSocketFeed when credentials set.
        LIVE + Delta: DeltaDataProvider, DeltaBroker, DeltaWebSocketFeed when credentials set.
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
                symbols=getattr(config, "symbols", None) or [],
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
            max_open_positions=getattr(config, "max_open_positions", None) or 20,
            engine_logger=engine_logger,
        )

        # ---------- Instruments (needed by OrderRouter) ----------
        instrument_store = EngineFactory._instrument_store(config)

        # ---------- Broker + OrderRouter (venue-specific) ----------
        # PAPER: use SimulatedBroker (same logs/safeguards as LIVE; no real orders).
        if config.run_mode == RunMode.PAPER:
            broker = SimulatedBroker(
                position_manager=position_manager,
                intent_store=intent_store,
            )
        elif config.broker_name == "DELTA":
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
            position_manager=position_manager,
            engine_logger=engine_logger,
            instrument_store=instrument_store,
            circuit_breaker_threshold=getattr(config, "circuit_breaker_threshold", 5),
            slippage_threshold_pct=getattr(config, "slippage_threshold_pct", None),
        )
        broker.set_order_router(order_router)

        # ---------- Universe (DHAN equity strategies only) ----------
        universe_service = EngineFactory._universe_service(
            config, data_provider, instrument_store, engine_logger=engine_logger
        )

        # ---------- IPOBreakout: resolve symbols from universe before feed subscription ----------
        EngineFactory._resolve_ipo_symbols(config, universe_service)

        # ---------- CandleService (uses same data_provider) ----------
        candle_service = CandleService(data_provider)

        # ---------- Realtime feed ----------
        realtime_feed = None
        tick_queue = None
        candle_aggregator = None
        if config.broker_name == "DELTA":
            try:
                api_key, api_secret = get_delta_credentials(config.delta_testnet)
            except ValueError:
                api_key, api_secret = None, None
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
                if getattr(strategy, "timeframe", None):
                    tick_queue = queue.Queue(maxsize=50000)
                    candle_aggregator = CandleAggregator()
                    realtime_feed.set_tick_queue(tick_queue)
                realtime_feed.start()
        elif config.broker_name == "DHAN":
            access_token = os.getenv("DHAN_ACCESS_TOKEN")
            client_id = os.getenv("DHAN_CLIENT_CODE")
            if (
                access_token
                and client_id
                and hasattr(instrument_store, "get_feed_instruments")
            ):
                symbols_list = config.symbols or []
                instruments = instrument_store.get_feed_instruments(symbols_list)
                if instruments:
                    realtime_feed = DhanWebSocketFeed(
                        access_token=access_token,
                        client_id=client_id,
                        instruments=instruments,
                    )
                    if getattr(strategy, "timeframe", None):
                        tick_queue = queue.Queue(maxsize=50000)
                        candle_aggregator = CandleAggregator()
                        realtime_feed.set_tick_queue(tick_queue)
                    realtime_feed.start()

        return LiveEngine(
            strategy=strategy,
            data=data_provider,
            candle_service=candle_service,
            symbols=config.symbols or [],
            order_router=order_router,
            instrument_store=instrument_store,
            position_manager=position_manager,
            realtime_feed=realtime_feed,
            tick_queue=tick_queue,
            candle_aggregator=candle_aggregator,
            engine_id=config.engine_id,
            venue=config.broker_name,
            engine_logger=engine_logger,
            feed_stale_seconds=getattr(config, "feed_stale_seconds", None) or 60,
            allowed_trading_hours=getattr(config, "allowed_trading_hours", None),
            order_state_check_interval_min=getattr(
                config, "order_state_check_interval_min", 0
            ),
            memory_threshold_percent=getattr(config, "memory_threshold_percent", None),
            strategy_timeout_seconds=getattr(config, "strategy_timeout_seconds", None),
            latency_critical_ms=getattr(config, "latency_critical_ms", 150.0),
            latency_critical_cycles=getattr(config, "latency_critical_cycles", 3),
            symbol_error_threshold=getattr(config, "symbol_error_threshold", 5),
            universe_service=universe_service,
        )

    @staticmethod
    def _instrument_store(config: EngineConfig) -> InstrumentStore:
        """Build venue-specific InstrumentStore (same class, different paths)."""
        deps = config.dependencies_dir
        current_date = __import__("time").strftime("%Y-%m-%d")

        if config.broker_name == "DELTA":
            csv_path = deps / ("delta_instrument_" + current_date + ".csv")
            base_url = None
            if getattr(config, "delta_testnet", False) and getattr(config, "delta_india", True):
                base_url = DELTA_BASE_URL_INDIA_TEST  # https://cdn-ind.testnet.deltaex.org
            return InstrumentStore(broker="DELTA", csv_path=csv_path, base_url=base_url)
        expected_file = "all_instrument" + current_date + ".csv"
        return InstrumentStore(csv_path=deps / expected_file)

    @staticmethod
    def _resolve_ipo_symbols(config: EngineConfig, universe_service) -> None:
        """
        For IPOBreakout with symbols None/empty: get IPO equities, filter, cap, set config.symbols.
        Filtering happens before feed subscription so we subscribe only to filtered symbols.
        """
        if config.symbols is not None and len(config.symbols) > 0:
            return
        if config.strategy_name != "IPOBreakout" or universe_service is None:
            config.symbols = config.symbols or []
            return
        live_or_backtest = (
            config.live if config.run_mode != RunMode.BACKTEST else config.backtest
        )
        params = live_or_backtest or {}
        ipo_days = params.get("ipo_days", 365)
        filter_conditions = params.get("ipo_filter")
        max_symbols = params.get("ipo_max_symbols", 50)
        as_of = None
        if config.run_mode == RunMode.BACKTEST and config.backtest:
            start_str = config.backtest.get("start_date")
            if start_str:
                try:
                    as_of = datetime.strptime(start_str, "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    pass
        ipo_symbols = universe_service.get_ipo_equities(days=ipo_days, as_of=as_of)
        # filtered = universe_service.filter_engine.filter(
        #     ipo_symbols, filter_conditions, universe_service
        # )

        config.symbols = ipo_symbols[:max_symbols] if ipo_symbols else []
        # Fallback when universe is empty (e.g. NSE file missing) so backtest can still run
        if not config.symbols and params.get("ipo_fallback_symbols"):
            config.symbols = list(params["ipo_fallback_symbols"])[:max_symbols]

    @staticmethod
    def _universe_service(
        config: EngineConfig, data_provider, instrument_store, engine_logger=None
    ):
        """
        Build EquityUniverseService for DHAN equity strategies only.
        Never raises: on missing file or error returns None so engine does not crash.
        """
        if config.broker_name != "DHAN":
            return None
        cfg = STRATEGY_MAP.get(config.strategy_name)
        if not cfg or cfg.get("instrument") != "EQUITY":
            return None
        if EquityUniverseService is None:
            return None
        try:
            base_dir = config.base_dir
            equity_universe_dir = base_dir / "Dependencies" / "equity_universe"
            return EquityUniverseService(
                cache_dir=equity_universe_dir,
                data_provider=data_provider,
                instrument_store=instrument_store,
                engine_logger=engine_logger,
            )
        except Exception as e:
            if engine_logger and hasattr(engine_logger, "log"):
                engine_logger.log("universe_load_error", error=str(e))
            return None
