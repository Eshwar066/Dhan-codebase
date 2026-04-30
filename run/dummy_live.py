"""
Run a strategy with DummyRealtimeFeed + CandleAggregator in PAPER mode.

Usage examples:
    python3 -m run.dummy_live
    python3 -m run.dummy_live --job SignalFloodTest --symbols NIFTY --tick-ms 200
    python3 -m run.dummy_live --job NiftyIntradayMagicalLine --stall-after 200 --stall-seconds 65

    python -m run.dummy_live --job dhan_leaps_rsi --symbols NIFTY --start-time "2026-04-25 09:15:00" --start-tz IST
    python -m run.dummy_live --job dhan_oi_positional_buy --symbols NIFTY --start-time "2026-04-25 09:15:00" --start-tz IST
    
"""

from __future__ import annotations

import argparse
import queue
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from core.data.candle_aggregator import CandleAggregator
from core.data.feeds import DummyRealtimeFeed
from core.engine.factory import EngineFactory
from run.config import RunMode, ENGINE_JOBS
from run.main import job_to_engine_config


def _parse_start_datetime(raw: str | None, tz_name: str) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    parsed: datetime | None = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(
                f"Invalid --start-time value: {raw!r}. "
                "Use 'YYYY-MM-DD HH:MM[:SS]' or ISO format."
            ) from exc
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    tz_key = str(tz_name or "UTC").strip().upper()
    if tz_key == "IST":
        ist = timezone(timedelta(hours=5, minutes=30))
        return parsed.replace(tzinfo=ist).astimezone(timezone.utc)
    return parsed.replace(tzinfo=timezone.utc)


def _resolve_job(job_name: str) -> Dict[str, Any]:
    needle = str(job_name or "").strip().lower()
    for job in ENGINE_JOBS:
        engine_id = str(job.get("engine_id", "")).strip().lower()
        if engine_id == needle:
            return dict(job)
        strategies = [str(s).strip().lower() for s in (job.get("strategies") or [])]
        if needle in strategies:
            return dict(job)
    raise ValueError(
        f"Job not found in ENGINE_JOBS by engine_id/strategy: {job_name}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dummy feed integration runner (PAPER mode)."
    )
    parser.add_argument(
        "--job",
        default="SignalFloodTest",
        help="Engine id or strategy name from ENGINE_JOBS (default: SignalFloodTest).",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Override symbols list (default: symbols from selected job).",
    )
    parser.add_argument("--tick-ms", type=int, default=200, help="Tick interval in ms.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument(
        "--start-time",
        type=str,
        default=None,
        help="Dummy feed start time. Example: '2026-04-25 09:15:00' or ISO datetime.",
    )
    parser.add_argument(
        "--start-tz",
        type=str,
        default="UTC",
        help="Timezone for naive --start-time values: UTC or IST (default: UTC).",
    )
    parser.add_argument(
        "--stall-after",
        type=int,
        default=None,
        help="Introduce feed stall after this tick count.",
    )
    parser.add_argument(
        "--stall-seconds",
        type=float,
        default=0.0,
        help="Feed stall duration in seconds.",
    )
    parser.add_argument(
        "--spike-at",
        type=int,
        default=None,
        help="Inject price spike at tick count.",
    )
    parser.add_argument(
        "--spike-amount",
        type=float,
        default=0.0,
        help="Spike amount (absolute).",
    )
    parser.add_argument(
        "--ooo-at",
        type=int,
        default=None,
        help="Inject one out-of-order tick at tick count.",
    )
    parser.add_argument(
        "--ooo-delay-seconds",
        type=float,
        default=10.0,
        help="How far behind to timestamp out-of-order tick.",
    )
    args = parser.parse_args()

    job = _resolve_job(args.job)
    if args.symbols:
        job["symbols"] = [str(s).strip().upper() for s in args.symbols if str(s).strip()]
    symbols = list(job.get("symbols") or [])
    if not symbols:
        raise ValueError("No symbols available. Set symbols in job config or pass --symbols.")

    # Force safe integration mode.
    job["enabled"] = True
    job["run_mode"] = RunMode.PAPER.value

    config = job_to_engine_config(job)
    engine = EngineFactory.create_live_engine(config)

    # Replace any venue websocket with dummy feed.
    if getattr(engine, "realtime_feed", None) is not None:
        try:
            engine.realtime_feed.stop()
        except Exception:
            pass

    tick_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=10000)
    aggregator = CandleAggregator()
    dummy_feed = DummyRealtimeFeed(
        symbols=symbols,
        tick_interval_ms=args.tick_ms,
        seed=args.seed,
        start_datetime=_parse_start_datetime(args.start_time, args.start_tz),
        stall_after_ticks=args.stall_after,
        stall_for_seconds=args.stall_seconds,
        spike_at_tick=args.spike_at,
        spike_amount=args.spike_amount,
        out_of_order_at_tick=args.ooo_at,
        out_of_order_delay_seconds=args.ooo_delay_seconds,
    )
    dummy_feed.set_tick_queue(tick_queue)
    dummy_feed.start()

    engine.realtime_feed = dummy_feed
    engine.tick_queue = tick_queue
    engine.candle_aggregator = aggregator

    live_cfg = config.live or {}
    try:
        engine.start(
            exchange=live_cfg.get("exchange", "INDEX"),
            sector=live_cfg.get("sector", "NO"),
            rsi=live_cfg.get("rsi", "NO"),
        )
    finally:
        dummy_feed.stop()


if __name__ == "__main__":
    main()

