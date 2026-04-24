import asyncio
import os
from glob import glob
from typing import Dict, List

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from control_api.schemas import (
    AddStrategyRequest,
    EngineActionRequest,
    EngineStatus,
    StrategyToggleRequest,
)
from control_api.service import get_system_metrics, list_engines
from control_api.state_store import RuntimeStateStore

app = FastAPI(title="Trading Control API", version="1.0.0")

_default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://trader.yourdomain.com",
]
_origins_env = os.getenv("UI_ALLOWED_ORIGINS", ",".join(_default_origins))
_allowed_origins = [o.strip() for o in _origins_env.split(",") if o.strip()]
_allow_wildcard = "*" in _allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins if not _allow_wildcard else ["*"],
    allow_credentials=not _allow_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATE_PATH = os.getenv("TRADER_RUNTIME_STATE_PATH", "logs/runtime_state.json")
store = RuntimeStateStore(path=STATE_PATH)


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/engines", response_model=List[EngineStatus])
def engines() -> List[EngineStatus]:
    return list_engines(store.get())


@app.post("/api/engines/{engine_id}/action")
def engine_action(engine_id: str, req: EngineActionRequest) -> Dict[str, str]:
    action = req.action.lower().strip()
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(status_code=400, detail="action must be start|stop|restart")
    runtime_status = "running" if action in {"start", "restart"} else "stopped"
    store.upsert_engine(engine_id, {"runtime_status": runtime_status, "last_action": action})
    # NOTE: this endpoint records operator intent; process control hook can be wired later.
    return {"engine_id": engine_id, "action": action, "runtime_status": runtime_status}


@app.post("/api/engines/{engine_id}/strategies/toggle")
def toggle_strategy(engine_id: str, req: StrategyToggleRequest) -> Dict[str, str]:
    key = f"strategy:{req.strategy_name}"
    patch = {"strategy_overrides": {key: bool(req.enabled)}}
    current = store.get().get("engines", {}).get(engine_id, {})
    merged = dict(current.get("strategy_overrides", {}))
    merged[key] = bool(req.enabled)
    store.upsert_engine(engine_id, {"strategy_overrides": merged})
    return {"engine_id": engine_id, "strategy_name": req.strategy_name, "enabled": str(req.enabled)}


@app.post("/api/engines/{engine_id}/strategies/add")
def add_strategy(engine_id: str, req: AddStrategyRequest) -> Dict[str, str]:
    current = store.get().get("engines", {}).get(engine_id, {})
    dynamic = list(current.get("dynamic_strategies", []))
    if req.strategy_name not in dynamic:
        dynamic.append(req.strategy_name)
    store.upsert_engine(engine_id, {"dynamic_strategies": dynamic})
    return {"engine_id": engine_id, "strategy_name": req.strategy_name, "status": "added"}


@app.get("/api/system/metrics")
def system_metrics() -> Dict[str, object]:
    return get_system_metrics()


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket) -> None:
    await ws.accept()
    sent: Dict[str, int] = {}
    try:
        while True:
            for path in glob("logs/*/*.log"):
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                prev = sent.get(path, 0)
                if size <= prev:
                    continue
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(prev)
                    chunk = f.read()
                sent[path] = size
                for line in chunk.splitlines():
                    if line.strip():
                        await ws.send_text(line)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return

