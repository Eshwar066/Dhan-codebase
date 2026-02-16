"""
Supervisor: holds multiple engines, start/stop, health & metrics only.

Does NOT execute trades. Each engine is fully isolated (own OMS).
Use for single-process multi-venue: run Engine_Dhan and Engine_Delta in separate threads.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from run.engine_config import EngineConfig
from core.engine.factory import EngineFactory
from core.engine.live_engine import LiveEngine


@dataclass
class EngineHandle:
    """One engine + its config and optional thread."""
    config: EngineConfig
    engine: Any  # LiveEngine (or BacktestEngine if run once)
    thread: Optional[threading.Thread] = None


class Supervisor:
    """
    Holds multiple engines. Can start/stop them (each in its own thread).
    Monitors health & metrics only; does not execute trades.
    """

    def __init__(self):
        self._handles: List[EngineHandle] = []
        self._stop_events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def register_from_config(self, config: EngineConfig) -> EngineHandle:
        """
        Create engine from config and register. Does not start.
        """
        engine = EngineFactory.create_engine(config)
        handle = EngineHandle(config=config, engine=engine)
        with self._lock:
            self._handles.append(handle)
        return handle

    def register_engine(self, config: EngineConfig, engine: Any) -> EngineHandle:
        """Register an already-created engine."""
        handle = EngineHandle(config=config, engine=engine)
        with self._lock:
            self._handles.append(handle)
        return handle

    def start_all(self) -> None:
        """
        Start all registered live engines in separate threads.
        BacktestEngine handles are ignored (run once, not in loop).
        """
        with self._lock:
            for handle in self._handles:
                if isinstance(handle.engine, LiveEngine):
                    venue = handle.config.broker_name
                    stop_evt = threading.Event()
                    self._stop_events[venue] = stop_evt
                    live_cfg = handle.config.live or {}
                    thread = threading.Thread(
                        target=self._run_live_engine,
                        args=(handle.engine, live_cfg, stop_evt),
                        daemon=True,
                        name=f"LiveEngine_{venue}",
                    )
                    handle.thread = thread
                    thread.start()

    def _run_live_engine(
        self,
        engine: LiveEngine,
        live_cfg: Dict[str, Any],
        stop_evt: threading.Event,
    ) -> None:
        try:
            engine.start(
                exchange=live_cfg.get("exchange", "INDEX"),
                sector=live_cfg.get("sector", "NO"),
                rsi=live_cfg.get("rsi", "NO"),
            )
        except Exception as e:
            if not stop_evt.is_set():
                raise
        # start() is infinite loop; exits only when interrupted

    def stop_all(self) -> None:
        """Signal all engine threads to stop (if they support it)."""
        for evt in self._stop_events.values():
            evt.set()
        # Note: LiveEngine.start() is a while True loop; stopping requires
        # adding a stop flag to LiveEngine or killing the thread. This scaffold
        # just sets the event; engines can check it if we add support later.

    def health_check(self) -> Dict[str, Any]:
        """
        Scaffold: return minimal health per venue.
        Override or extend for real metrics (e.g. feed connected, last candle time).
        """
        with self._lock:
            out = {}
            for handle in self._handles:
                venue = handle.config.broker_name
                out[venue] = {
                    "config_strategy": handle.config.strategy_name,
                    "symbols": handle.config.symbols,
                    "thread_alive": handle.thread.is_alive() if handle.thread else False,
                    "has_realtime_feed": getattr(
                        handle.engine, "realtime_feed", None
                    ) is not None,
                    "feed_connected": (
                        getattr(handle.engine, "realtime_feed", None) is not None
                        and getattr(handle.engine.realtime_feed, "is_connected", lambda: False)()
                    ),
                }
            return out

    @property
    def engines(self) -> List[EngineHandle]:
        with self._lock:
            return list(self._handles)
