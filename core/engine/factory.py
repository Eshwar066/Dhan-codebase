"""
EngineFactory: build fully isolated single-venue engines.

One engine = one broker = one OMS stack (PositionManager, RiskManager,
OrderRouter, Broker). No shared instances between venues.

Usage:
    config = EngineConfig(broker_name="DELTA", run_mode=RunMode.LIVE, ...)
    engine = EngineFactory.create_engine(config)
    # then engine.run(...) or engine.start(...)
"""

import logging
import os
import queue
from datetime import datetime
from pathlib import Path
from typing import Union, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Temporary headroom while main-loop drain/stall ordering is improved (see utils/cursor.md).
TICK_QUEUE_MAXSIZE = 5000

from run.config import RunMode
from run.engine_config import EngineConfig, configure_process_logging
from core.strategies.registry import get_strategy_config, resolve_registry_key
from core.engine.base_engine import BaseEngine
from core.engine.backtest_engine import BacktestEngine
from core.engine.live_engine import LiveEngine
from core.data.sources.dhan_source import DhanSource
from core.data.sources.delta_source import DeltaSource, DELTA_BASE_URL_INDIA_TEST
from core.data.datalayer import DhanDataProvider, DeltaDataProvider
from core.data.candle_service import CandleService
from core.data.candle_aggregator import (
    CandleAggregator,
    MCX_DEFAULT_SESSION_END_SEC,
    MCX_DEFAULT_SESSION_START_SEC,
    _resolution_to_seconds,
)
from core.data.feeds import DeltaWebSocketFeed, DhanWebSocketFeed
from core.data.feeds.delta_candlestick import resolutions_from_engine_timeframes
from core.data.feeds.dhan_order_update_feed import DhanOrderUpdateFeed
from core.broker import (
    DhanBroker,
    DhanBrokerApi,
    DeltaBroker,
    DeltaBrokerApi,
    SimulatedBroker,
)
from core.orderExecution.order_router import OrderRouter
from core.orderExecution.account_router import AccountRouter
from core.orderExecution.intent_store import IntentStore
from core.orderExecution.position_manager import PositionManager
from core.orderExecution.risk_manager import RiskManager, make_short_option_margin_check
from core.utils.delta_env import get_delta_credentials
from core.utils.instruments.instrument_store import InstrumentStore
from core.utils.telegram_alert import send_telegram_alert
from utils.logger.trade_logger import TradeLogger
from utils.logger.open_positions_logger import OpenPositionsLogger
from utils.logger.engine_logger import EngineLogger

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
    def _attach_engine_context(strategies: list, config: EngineConfig) -> None:
        """Inject per-engine broker flags onto strategy instances (e.g. Delta testnet)."""
        if str(config.broker_name).upper() != "DELTA":
            return
        for s in strategies:
            setattr(s, "_engine_delta_testnet", bool(getattr(config, "delta_testnet", False)))
            setattr(s, "_engine_delta_india", bool(getattr(config, "delta_india", False)))

    @staticmethod
    def _strategy_feed_timeframe(strategies: list) -> str:
        """Finest (smallest) strategy timeframe for Delta WS candle channel."""
        best_tf: Optional[str] = None
        best_sec: Optional[int] = None
        for s in strategies:
            tf = str(getattr(s, "timeframe", "") or "").strip()
            if not tf:
                continue
            sec = int(_resolution_to_seconds(tf))
            if best_sec is None or sec < best_sec:
                best_sec = sec
                best_tf = tf
        return best_tf or "60"

    @staticmethod
    def create_engine(config: EngineConfig) -> Union[BacktestEngine, LiveEngine]:
        """
        Build engine from config. Backtest vs Live is determined by config.run_mode.
        """
        configure_process_logging(config)
        if config.run_mode == RunMode.BACKTEST:
            return EngineFactory.create_backtest_engine(config)
        return EngineFactory.create_live_engine(config)

    @staticmethod
    def create_backtest_engine(config: EngineConfig) -> BacktestEngine:
        """
        Build BacktestEngine with isolated stack for config.broker_name.
        """
        cfg = get_strategy_config(config.strategy_name)
        if not cfg:
            raise ValueError(f"Unknown strategy: {config.strategy_name}")
        if config.run_mode.value not in [m.value for m in cfg["allowed_modes"]]:
            raise ValueError(
                f"Strategy {config.strategy_name} not allowed in {config.run_mode}"
            )

        strategy = cfg["strategy"]()
        if getattr(config, "order_qty_lots", None) is not None:
            setattr(strategy, "order_qty_lots", int(config.order_qty_lots))
        strategies = [strategy]
        EngineFactory._attach_engine_context(strategies, config)

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
        trade_logger = TradeLogger()
        position_manager = PositionManager(
            logger=trade_logger,
            open_positions_logger=None,
        )
        intent_store = IntentStore()
        risk_manager = RiskManager(position_manager=position_manager)
        # ---------- Instruments (needed by OrderRouter) ----------
        instrument_store = EngineFactory._instrument_store(config)
        broker = SimulatedBroker(
            position_manager=position_manager,
            intent_store=intent_store,
        )
        _loaded_strategies_bt = [config.strategy_name] + list(
            getattr(config, "strategy_names", None) or []
        )
        order_router = OrderRouter(
            risk_manager=risk_manager,
            broker=broker,
            intent_store=intent_store,
            position_manager=position_manager,
            instrument_store=instrument_store,
            engine_id=getattr(config, "engine_id", None),
            strategy_id=config.strategy_name,
            known_strategies=_loaded_strategies_bt,
        )
        broker.set_order_router(order_router)
        position_manager.rebuild_position_metadata_from_intent_store(intent_store)
        position_manager.rebuild_structure_slices_from_intent_store(intent_store)
        position_manager.rebuild_position_metadata_from_open_positions_csv()
        exchange = getattr(config, "exchange", None) or "NSE"
        position_manager.rebuild_open_positions_from_open_positions_csv(
            instrument_store,
            exchange=exchange,
        )

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
        cfg = get_strategy_config(config.strategy_name)
        if not cfg:
            raise ValueError(f"Unknown strategy: {config.strategy_name}")
        if config.run_mode.value not in [m.value for m in cfg["allowed_modes"]]:
            raise ValueError(
                f"Strategy {config.strategy_name} not allowed in {config.run_mode}"
            )

        strategy = cfg["strategy"]()
        if getattr(config, "order_qty_lots", None) is not None:
            setattr(strategy, "order_qty_lots", int(config.order_qty_lots))
        strategies = [strategy]
        extra_names = list(getattr(config, "strategy_names", None) or [])
        for strategy_name in extra_names:
            if strategy_name == config.strategy_name:
                continue
            extra_cfg = get_strategy_config(strategy_name)
            if not extra_cfg:
                raise ValueError(f"Unknown strategy in strategy_names: {strategy_name}")
            if config.run_mode.value not in [m.value for m in extra_cfg["allowed_modes"]]:
                raise ValueError(
                    f"Strategy {strategy_name} not allowed in {config.run_mode}"
                )
            extra_strategy = extra_cfg["strategy"]()
            if getattr(config, "order_qty_lots", None) is not None:
                setattr(extra_strategy, "order_qty_lots", int(config.order_qty_lots))
            strategies.append(extra_strategy)
        EngineFactory._attach_engine_context(strategies, config)

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

        telegram_alert = None
        if getattr(config, "telegram_bot_token", None) and getattr(
            config, "telegram_chat_id", None
        ):
            def telegram_alert(message: str) -> None:
                send_telegram_alert(
                    message=message,
                    receiver_chat_id=str(config.telegram_chat_id),
                    bot_token=str(config.telegram_bot_token),
                )

        # ---------- OMS (isolated per engine) ----------
        trade_logger = TradeLogger()
        _engine_id = config.engine_id or "live"
        _strategy_dir = str(config.strategy_name or "GLOBAL").replace("/", "_").replace("\\", "_").replace(" ", "_")
        _open_positions_csv = os.path.join(
            "logs", _strategy_dir, f"{_engine_id}_open_positions.csv"
        )
        open_positions_logger = OpenPositionsLogger(
            engine_id=_engine_id,
            venue=config.broker_name or "",
            run_mode=config.run_mode,
            strategy=config.strategy_name,
        )
        position_manager = PositionManager(
            logger=trade_logger,
            open_positions_logger=open_positions_logger,
            open_positions_csv_path=_open_positions_csv,
        )
        intent_store = IntentStore()
        _loaded_strategies = [config.strategy_name] + list(
            getattr(config, "strategy_names", None) or []
        )
        engine_logger = EngineLogger(
            engine_id=config.engine_id,
            venue=config.broker_name,
            strategy=config.strategy_name,
            telegram_alert=telegram_alert,
            known_strategies=_loaded_strategies,
            debug_mode=bool(getattr(config, "debug_mode", False)),
        )
        risk_manager = RiskManager(
            position_manager=position_manager,
            capital=config.capital,
            risk_per_trade_percent=config.risk_per_trade_percent,
            daily_max_loss=config.daily_max_loss,
            max_open_positions=getattr(config, "max_open_positions", None) or 20,
            max_portfolio_exposure=getattr(config, "max_portfolio_exposure", None)
            or 10000000,
            cooldown_seconds=getattr(config, "cooldown_seconds", None) or 5,
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
                default_leverage=int(getattr(config, "delta_leverage", None) or 1),
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
            engine_id=getattr(config, "engine_id", None),
            strategy_id=config.strategy_name,
            known_strategies=_loaded_strategies,
        )
        # Option shorting: validate SPAN + exposure margin when broker supports it (unless disabled in config)
        if getattr(config, "check_short_option_margin_enabled", True) is not False:
            _margin_check = make_short_option_margin_check(broker)
            if _margin_check is not None:
                order_router.risk.check_short_option_margin = _margin_check
        broker.set_order_router(order_router)
        position_manager.rebuild_position_metadata_from_intent_store(intent_store)
        position_manager.rebuild_structure_slices_from_intent_store(intent_store)
        position_manager.rebuild_position_metadata_from_open_positions_csv()
        exchange = getattr(config, "exchange", None) or "NSE"
        position_manager.rebuild_open_positions_from_open_positions_csv(
            instrument_store,
            exchange=exchange,
        )

        # ---------- Delta: set leverage from config (live only; skip for SimulatedBroker e.g. PAPER) ----------
        if (
            config.broker_name == "DELTA"
            and hasattr(broker, "api")
            and getattr(config, "delta_leverage", None) is not None
            and (getattr(config, "symbols", None) or [])
        ):
            lev = int(config.delta_leverage)
            results = broker.api.set_leverage_for_symbols(config.symbols, lev)
            for sym, res in results.items():
                if res.get("ok"):
                    engine_logger.log(
                        "delta_leverage",
                        f"Delta leverage set: {sym} -> {lev}x (product_id={res.get('product_id')})",
                    )
                else:
                    engine_logger.log(
                        "delta_leverage_warning",
                        f"Delta leverage failed for {sym}: {res.get('message', res)}",
                    )

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
        dhan_order_update_feed = None
        tick_queue = None
        candle_queue = None
        candle_aggregator = None
        if config.broker_name == "DELTA":
            try:
                api_key, api_secret = get_delta_credentials(config.delta_testnet)
            except ValueError as e:
                logger.warning("Delta credentials missing or invalid: %s", e)
                api_key, api_secret = None, None
            if api_key and api_secret:
                timeframe = EngineFactory._strategy_feed_timeframe(strategies)
                eval_modes = getattr(config, "strategy_eval", None) or {}
                feed_symbols = LiveEngine._collect_feed_symbols(
                    config.symbols or [], strategies, eval_modes
                )
                engine_timeframes = LiveEngine._collect_engine_timeframes_from_strategies(
                    strategies, strategy, eval_modes
                )
                candlestick_resolutions, unsupported_tfs = (
                    resolutions_from_engine_timeframes(engine_timeframes)
                )
                for tf in unsupported_tfs:
                    logger.warning(
                        "Delta WS has no candlestick channel for strategy timeframe %s; "
                        "bars will be built from v2/ticker ticks",
                        tf,
                    )
                if not feed_symbols:
                    logger.info(
                        "Delta market WS skipped: no candle-based feed symbols for engine %s",
                        config.engine_id,
                    )
                else:
                    realtime_feed = DeltaWebSocketFeed(
                        api_key=api_key,
                        api_secret=api_secret,
                        symbols=feed_symbols,
                        timeframe=timeframe,
                        candlestick_resolutions=candlestick_resolutions,
                        testnet=config.delta_testnet,
                        india=config.delta_india,
                        subscribe_private=True,
                        engine_logger=engine_logger,
                        telegram_alert=telegram_alert,
                    )
                    if LiveEngine.needs_tick_queue(strategies, eval_modes):
                        tick_queue = queue.Queue(maxsize=TICK_QUEUE_MAXSIZE)
                        candle_queue = queue.Queue(maxsize=5000)
                        candle_aggregator = CandleAggregator(
                            engine_logger=engine_logger,
                            debug_mode=bool(getattr(config, "debug_mode", False)),
                        )
                        realtime_feed.set_tick_queue(tick_queue)
                        realtime_feed.set_candle_queue(candle_queue)
                        mark_native = getattr(
                            candle_aggregator, "set_exchange_native_resolutions", None
                        )
                        if callable(mark_native) and candlestick_resolutions:
                            mark_native(candlestick_resolutions)
                    realtime_feed.start()
                    if hasattr(broker, "set_realtime_feed"):
                        broker.set_realtime_feed(realtime_feed)
            elif not api_key or not api_secret:
                logger.warning("Delta realtime feed skipped: missing API credentials")
        elif config.broker_name == "DHAN":
            access_token = os.getenv("DHAN_ACCESS_TOKEN")
            client_id = os.getenv("DHAN_CLIENT_CODE")
            market_exchange = str(getattr(config, "market_exchange", "") or "").upper()
            is_nse_like = market_exchange in {"NSE", "INDEX", "NSE_INDEX"}
            is_mcx = market_exchange == "MCX"
            if not access_token or not client_id:
                logger.warning("Dhan realtime feed skipped: DHAN_ACCESS_TOKEN or DHAN_CLIENT_CODE not set")
            if (
                access_token
                and client_id
                and hasattr(instrument_store, "get_feed_instruments")
            ):
                eval_modes = getattr(config, "strategy_eval", None) or {}
                feed_symbols = LiveEngine._collect_feed_symbols(
                    config.symbols or [], strategies, eval_modes
                )
                symbols_list = feed_symbols
                if not symbols_list:
                    logger.info(
                        "Dhan market WS skipped: no candle-based feed symbols for engine %s",
                        config.engine_id,
                    )
                instruments = (
                    instrument_store.get_feed_instruments(symbols_list)
                    if symbols_list
                    else []
                )
                if symbols_list and not instruments:
                    logger.warning("Dhan realtime feed skipped: get_feed_instruments returned empty for %s", symbols_list)
                if instruments:
                    realtime_feed = DhanWebSocketFeed(
                        access_token=access_token,
                        client_id=client_id,
                        instruments=instruments,
                        engine_logger=engine_logger,
                        debug_mode=bool(getattr(config, "debug_mode", False)),
                        stall_timeout_seconds=getattr(
                            config, "market_ws_stall_timeout_seconds", None
                        ),
                    )
                    if LiveEngine.needs_tick_queue(strategies, eval_modes):
                        tick_queue = queue.Queue(maxsize=TICK_QUEUE_MAXSIZE)
                        if is_nse_like:
                            candle_aggregator = CandleAggregator(
                                session_start_sec=(9 * 3600) + (15 * 60),
                                session_end_sec=(15 * 3600) + (30 * 60),
                                engine_logger=engine_logger,
                                debug_mode=bool(getattr(config, "debug_mode", False)),
                            )
                        elif is_mcx:
                            # MCX regular session (09:00–23:30 IST): anchor intraday/hourly buckets to
                            # session open; explicit session-end flush finalizes the last partial hour.
                            candle_aggregator = CandleAggregator(
                                session_start_sec=MCX_DEFAULT_SESSION_START_SEC,
                                session_end_sec=MCX_DEFAULT_SESSION_END_SEC,
                                engine_logger=engine_logger,
                                debug_mode=bool(getattr(config, "debug_mode", False)),
                            )
                        else:
                            candle_aggregator = CandleAggregator(
                                engine_logger=engine_logger,
                                debug_mode=bool(getattr(config, "debug_mode", False)),
                            )
                        realtime_feed.set_tick_queue(tick_queue)
                    realtime_feed.start()
            if access_token and client_id:
                dhan_order_update_feed = DhanOrderUpdateFeed(
                    access_token=access_token,
                    client_id=client_id,
                )

        return LiveEngine(
            strategy=strategy,
            strategies=strategies,
            strategy_eval_modes=getattr(config, "strategy_eval", None) or {},
            data=data_provider,
            candle_service=candle_service,
            symbols=config.symbols or [],
            order_router=order_router,
            instrument_store=instrument_store,
            position_manager=position_manager,
            realtime_feed=realtime_feed,
            tick_queue=tick_queue,
            candle_queue=candle_queue,
            candle_aggregator=candle_aggregator,
            engine_id=config.engine_id,
            venue=config.broker_name,
            market_exchange=getattr(config, "market_exchange", None),
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
            run_mode=config.run_mode,
            open_positions_logger=open_positions_logger,
            dhan_order_update_feed=dhan_order_update_feed,
            account_router=AccountRouter(getattr(config, "account_routing", None)),
            oms_rate_limit_per_sec=getattr(config, "oms_rate_limit_per_sec", 5.0),
            intent_queue_maxsize=getattr(config, "intent_queue_maxsize", 1000),
            account_queue_maxsize=getattr(config, "account_queue_maxsize", 500),
            queue_overflow_policy=getattr(config, "queue_overflow_policy", "drop_newest"),
            oms_retry_max_attempts=getattr(config, "oms_retry_max_attempts", 3),
            oms_retry_base_delay_seconds=getattr(
                config, "oms_retry_base_delay_seconds", 0.25
            ),
            oms_token_bucket_capacity=getattr(config, "oms_token_bucket_capacity", 5),
            worker_watchdog_interval_seconds=getattr(
                config, "worker_watchdog_interval_seconds", 5.0
            ),
            max_active_account_symbol_keys=getattr(
                config, "max_active_account_symbol_keys", 200
            ),
            account_circuit_breaker_threshold=getattr(
                config, "account_circuit_breaker_threshold", 5
            ),
            feed_stall_seconds=getattr(config, "feed_stall_seconds", 60.0),
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
        cfg = get_strategy_config(config.strategy_name)
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
