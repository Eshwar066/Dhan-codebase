"""
Multi-venue entry point. Uses EngineFactory to build isolated engines per venue.

Single process, single venue (filter by --venue):
    python -m run.main --venue DHAN
    python -m run.main --venue DELTA

Two processes (parallel Dhan + Delta):
    Process 1: python -m run.main --venue DHAN
    Process 2: python -m run.main --venue DELTA

Optional: use Supervisor in code to run both venues in one process (two threads).
"""

import argparse
import logging
import sys

from run.config import (
    RUN_MODE,
    RunMode,
    ENGINE_JOBS,
    DEFAULT_VENUE,
    DEFAULT_ROOT_LOG_LEVEL,
    DEFAULT_LIBRARY_LOG_LEVEL,
)

logger = logging.getLogger(__name__)
from run.engine_config import EngineConfig, configure_process_logging
from core.engine.factory import EngineFactory


def job_to_engine_config(job: dict) -> EngineConfig:
    """Build EngineConfig from either ENGINE_JOBS or legacy STRATEGY_JOBS shape."""
    venue = job.get("venue", DEFAULT_VENUE)
    backtest = job.get("backtest") or {}
    live = job.get("live") or {}
    strategies = list(job.get("strategies") or [])
    primary_strategy = job.get("name") or (strategies[0] if strategies else None)
    extra_strategies = (
        list(job.get("strategy_names") or [])
        if job.get("strategy_names") is not None
        else strategies[1:]
    )
    if not primary_strategy:
        raise ValueError(
            f"Invalid job config for engine_id={job.get('engine_id')}: missing strategy name."
        )
    # Per-job run_mode: "PAPER" | "LIVE" | "BACKTEST"; if omitted or invalid, use global RUN_MODE
    run_mode_raw = job.get("run_mode")
    try:
        run_mode = RunMode(str(run_mode_raw).upper()) if run_mode_raw else RUN_MODE
    except (ValueError, AttributeError):
        run_mode = RUN_MODE
    telegram_cfg = job.get("telegram") or {}
    telegram_bot_token = job.get("telegram_bot_token") or telegram_cfg.get("bot_token")
    telegram_chat_id = job.get("telegram_chat_id") or telegram_cfg.get("chat_id")
    return EngineConfig(
        broker_name=venue,
        run_mode=run_mode,
        strategy_name=primary_strategy,
        strategy_names=extra_strategies,
        symbols=job["symbols"],
        enabled=job.get("enabled", True),
        engine_id=job.get("engine_id"),
        market_exchange=job.get("exchange"),
        capital=job.get("capital"),
        risk_per_trade_percent=job.get("risk_per_trade_percent"),
        daily_max_loss=job.get("daily_max_loss"),
        max_open_positions=job.get("max_open_positions"),
        max_portfolio_exposure=job.get("max_portfolio_exposure"),
        cooldown_seconds=job.get("cooldown_seconds"),
        order_qty_lots=job.get("ORDER_QTY_LOTS"),
        check_short_option_margin_enabled=job.get("check_short_option_margin_enabled"),
        feed_stale_seconds=job.get("feed_stale_seconds"),
        market_ws_stall_timeout_seconds=job.get("market_ws_stall_timeout_seconds"),
        backtest=backtest,
        live=live,
        delta_testnet=job.get("delta_testnet", True),
        delta_india=job.get("delta_india", False),
        delta_leverage=job.get("delta_leverage"),
        order_state_check_interval_min=job.get("order_state_check_interval_min", 0),
        memory_threshold_percent=job.get("memory_threshold_percent"),
        strategy_timeout_seconds=job.get("strategy_timeout_seconds"),
        latency_critical_ms=job.get("latency_critical_ms", 150.0),
        latency_critical_cycles=job.get("latency_critical_cycles", 3),
        symbol_error_threshold=job.get("symbol_error_threshold", 5),
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        root_log_level=str(job.get("log_level") or DEFAULT_ROOT_LOG_LEVEL),
        library_log_level=str(job.get("library_log_level") or DEFAULT_LIBRARY_LOG_LEVEL),
    )


def run_engine(config: EngineConfig) -> None:
    """Create one engine from config and run it (backtest or live)."""
    if not config.enabled:
        print(f"[WARN] {config.strategy_name} ({config.broker_name}) is disabled. Skipping.")
        return

    loaded_strategies = [config.strategy_name] + list(config.strategy_names or [])
    logger.info(
        "Loaded strategies for %s (%s): %s",
        config.engine_id or f"{config.broker_name.lower()}_{config.strategy_name.lower()}",
        config.broker_name,
        ", ".join(loaded_strategies),
    )
    print(f"[RUN] Running {config.strategy_name} ({config.broker_name})...")
    engine = EngineFactory.create_engine(config)

    symbols = config.symbols or []
    if not symbols and config.strategy_name == "IPOBreakout":
        print(
            "[WARN] IPOBreakout: no symbols from universe (NSE EQUITY_L missing/failed or filter returned empty). "
            "Strategy will not receive any candles. Ensure Dependencies/equity_universe/EQUITY_L_latest.csv exists or set symbols in config."
        )

    if config.run_mode == RunMode.BACKTEST:
        bt = config.backtest or {}
        engine.run(
            symbols=symbols,
            start_date=bt.get("start_date", ""),
            end_date=bt.get("end_date", ""),
            timeframe=bt.get("timeframe", "60"),
            exchange=bt.get("exchange", "INDEX"),
            sector=bt.get("sector", "NO"),
        )
        print("Done.")
    else:
        live_cfg = config.live or {}
        engine.start(
            exchange=live_cfg.get("exchange", "INDEX"),
            sector=live_cfg.get("sector", "NO"),
            rsi=live_cfg.get("rsi", "NO"),
        )


def main():
    parser = argparse.ArgumentParser(
        description="Multi-venue trading: Dhan (India) + Delta (Crypto)"
    )
    parser.add_argument(
        "--venue",
        choices=["DHAN", "DELTA"],
        default=None,
        help="Run only jobs for this venue. If omitted, run all jobs (each with its own isolated engine).",
    )
    args = parser.parse_args()

    configs = [job_to_engine_config(job) for job in ENGINE_JOBS]
    if args.venue:
        configs = [c for c in configs if c.broker_name == args.venue]
        if not configs:
            configure_process_logging(None)
            logger.warning("No enabled jobs for venue %s", args.venue)
            print(f"No enabled jobs for venue {args.venue}")
            sys.exit(0)

    configure_process_logging(configs[0] if configs else None)

    mode_summary = ", ".join(f"{c.strategy_name}({c.run_mode.value})" for c in configs)
    print(f"Default run mode: {RUN_MODE.value} | Jobs: {mode_summary}")
    for config in configs:
        run_engine(config)


if __name__ == "__main__":
    main()
