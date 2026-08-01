"""Per-engine process lock — one live OS process per engine_id (prevents duplicate Dhan WS)."""

from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path
from typing import IO, Optional

_LOCK_HANDLES: dict[str, IO[str]] = {}


def _lock_path(engine_id: str) -> Path:
    safe = str(engine_id or "default").strip().replace("/", "_").replace("\\", "_")
    root = Path(__file__).resolve().parents[1]
    return root / "logs" / "locks" / f"{safe}.lock"


def acquire_engine_lock(engine_id: Optional[str]) -> None:
    """Exit if another process already holds the lock for this engine_id."""
    eid = str(engine_id or "").strip()
    if not eid:
        return
    path = _lock_path(eid)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        other_pid = ""
        try:
            handle.seek(0)
            other_pid = handle.read().strip()
        except Exception:
            pass
        handle.close()
        print(
            f"[FATAL] Engine {eid!r} is already running"
            + (f" (pid {other_pid})" if other_pid else "")
            + f". Lock: {path}. "
            "Stop the other process before starting a second instance.",
            file=sys.stderr,
        )
        sys.exit(1)
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _LOCK_HANDLES[eid] = handle
