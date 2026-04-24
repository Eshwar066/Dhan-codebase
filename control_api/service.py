import json
import os
from collections import deque
from glob import glob
from typing import Any, Dict, List, Optional

import psutil

from run.config import ENGINE_JOBS


def _tail_jsonl(path: str, max_lines: int = 200) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    q: deque[str] = deque(maxlen=max_lines)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if s:
                q.append(s)
    out: List[Dict[str, Any]] = []
    for line in q:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def get_latest_engine_event(engine_id: str) -> Optional[Dict[str, Any]]:
    candidates = glob(f"logs/*/{engine_id}.log")
    if not candidates:
        return None
    events: List[Dict[str, Any]] = []
    for p in candidates:
        events.extend(_tail_jsonl(p, max_lines=20))
    if not events:
        return None
    events.sort(key=lambda x: str(x.get("timestamp") or ""))
    return events[-1]


def list_engines(runtime_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    state_engines = runtime_state.get("engines", {})
    out: List[Dict[str, Any]] = []
    for job in ENGINE_JOBS:
        engine_id = str(job.get("engine_id") or "unknown_engine")
        control = state_engines.get(engine_id, {})
        latest = get_latest_engine_event(engine_id)
        runtime_status = str(control.get("runtime_status") or "unknown")
        if latest and str(latest.get("event_type")) == "engine_start":
            runtime_status = "running"
        out.append(
            {
                "engine_id": engine_id,
                "venue": str(job.get("venue") or ""),
                "run_mode": str(job.get("run_mode") or ""),
                "enabled": bool(job.get("enabled", True)),
                "strategies": list(job.get("strategies") or []),
                "runtime_status": runtime_status,
                "symbols": job.get("symbols"),
                "live": dict(job.get("live") or {}),
                "backtest": dict(job.get("backtest") or {}),
                "control": control,
            }
        )
    return out


def get_system_metrics() -> Dict[str, Any]:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "memory_percent": mem.percent,
        "memory_used_mb": round(mem.used / (1024 * 1024), 2),
        "memory_total_mb": round(mem.total / (1024 * 1024), 2),
        "disk_percent": disk.percent,
        "disk_used_gb": round(disk.used / (1024 * 1024 * 1024), 2),
        "disk_total_gb": round(disk.total / (1024 * 1024 * 1024), 2),
        "load_avg": {"1m": load[0], "5m": load[1], "15m": load[2]},
    }

