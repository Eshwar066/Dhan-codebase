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
import os
import sys
from pathlib import Path
import pdb

from run.config import RUN_MODE, RunMode, STRATEGY_JOBS, DEFAULT_VENUE
from run.engine_config import EngineConfig
from core.engine.factory import EngineFactory


def job_to_engine_config(job: dict) -> EngineConfig:
    """Build EngineConfig from a STRATEGY_JOBS entry."""
    venue = job.get("venue", DEFAULT_VENUE)
    backtest = job.get("backtest") or {}
    live = job.get("live") or {}
    return EngineConfig(
        broker_name=venue,
        run_mode=RUN_MODE,
        strategy_name=job["name"],
        symbols=job["symbols"],
        enabled=job.get("enabled", True),
        engine_id=job.get("engine_id"),
        capital=job.get("capital"),
        risk_per_trade_percent=job.get("risk_per_trade_percent"),
        daily_max_loss=job.get("daily_max_loss"),
        max_open_positions=job.get("max_open_positions"),
        max_portfolio_exposure=job.get("max_portfolio_exposure"),
        cooldown_seconds=job.get("cooldown_seconds"),
        check_short_option_margin_enabled=job.get("check_short_option_margin_enabled"),
        feed_stale_seconds=job.get("feed_stale_seconds"),
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
        telegram_bot_token=(
            (job.get("telegram") or {}).get("bot_token") if isinstance(job.get("telegram"), dict) else None
        ) or os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=(
            (job.get("telegram") or {}).get("chat_id") if isinstance(job.get("telegram"), dict) else None
        ) or os.getenv("TELEGRAM_CHAT_ID"),
    )


def run_engine(config: EngineConfig) -> None:
    """Create one engine from config and run it (backtest or live)."""
    if not config.enabled:
        print(f"⚠️ {config.strategy_name} ({config.broker_name}) is disabled. Skipping.")
        return

    print(f"▶ Running {config.strategy_name} ({config.broker_name})...")
    engine = EngineFactory.create_engine(config)

    symbols = config.symbols or []
    if not symbols and config.strategy_name == "IPOBreakout":
        print(
            "⚠️ IPOBreakout: no symbols from universe (NSE EQUITY_L missing/failed or filter returned empty). "
            "Strategy will not receive any candles. Ensure Dependencies/equity_universe/EQUITY_L_latest.csv exists or set symbols in config."
        )

    if RUN_MODE == RunMode.BACKTEST:
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

    configs = [job_to_engine_config(job) for job in STRATEGY_JOBS]
    if args.venue:
        configs = [c for c in configs if c.broker_name == args.venue]
        if not configs:
            print(f"No enabled jobs for venue {args.venue}")
            sys.exit(0)

    print(f"Run mode: {RUN_MODE.value} | Jobs: {[c.strategy_name for c in configs]}")
    for config in configs:
        run_engine(config)


if __name__ == "__main__":
    main()
