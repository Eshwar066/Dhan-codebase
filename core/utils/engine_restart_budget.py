"""
Track consecutive startup failures per engine_id and cap automated restarts.

Used with systemd Restart=on-failure + StartLimitBurst. After MAX_FAILURES,
sends one Telegram alert (if configured) and exits 0 so the service stops restarting.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

MAX_STARTUP_FAILURES = int(os.getenv("ALGO_ENGINE_MAX_STARTUP_FAILURES", "5"))
_STATE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "logs",
    ".engine_restart_budget",
)


class ExitBudgetExceeded(Exception):
    """Raised when startup failure budget is exhausted (caller should exit 0)."""


def _state_path(engine_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(engine_id or "unknown"))
    os.makedirs(_STATE_ROOT, exist_ok=True)
    return os.path.join(_STATE_ROOT, f"{safe}.json")


def _load_state(engine_id: str) -> Dict[str, Any]:
    path = _state_path(engine_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"failures": 0, "notified": False, "last_detail": ""}


def _save_state(engine_id: str, state: Dict[str, Any]) -> None:
    path = _state_path(engine_id)
    state["updated_at"] = time.time()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        logger.warning("Could not persist restart budget for %s: %s", engine_id, e)


def reset_startup_success(engine_id: str) -> None:
    """Clear failure counter after a successful startup (e.g. reconciliation passed)."""
    _save_state(
        engine_id,
        {"failures": 0, "notified": False, "last_detail": ""},
    )


def on_startup_failure(
    engine_id: str,
    detail: str,
    notify: Optional[Callable[[str], None]] = None,
) -> None:
    """
    Record a startup failure. If budget exceeded, send Telegram once and raise ExitBudgetExceeded.
    Otherwise caller should sys.exit(1) to let systemd retry after RestartSec.
    """
    state = _load_state(engine_id)
    failures = int(state.get("failures") or 0) + 1
    state["failures"] = failures
    state["last_detail"] = str(detail or "")[:500]
    _save_state(engine_id, state)

    if failures < MAX_STARTUP_FAILURES:
        logger.error(
            "Engine %s startup failure %s/%s: %s",
            engine_id,
            failures,
            MAX_STARTUP_FAILURES,
            detail,
        )
        return

    if not state.get("notified") and notify:
        unit = f"{engine_id.replace('_', '-')}.service"
        msg = (
            f"🛑 [{engine_id}] Engine stopped after {MAX_STARTUP_FAILURES} failed startups. "
            f"No further automatic restarts. Last error: {state['last_detail']}. "
            f"After fix: systemctl reset-failed {unit} && systemctl start {unit}"
        )
        try:
            notify(msg)
        except Exception as e:
            logger.warning("Telegram notify on budget exceeded failed: %s", e)
        state["notified"] = True
        _save_state(engine_id, state)

    logger.critical(
        "Engine %s startup failure budget exhausted (%s). Stopping restart cycle.",
        engine_id,
        MAX_STARTUP_FAILURES,
    )
    raise ExitBudgetExceeded()
