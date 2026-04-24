from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EngineActionRequest(BaseModel):
    action: str = Field(description="start|stop|restart")


class StrategyToggleRequest(BaseModel):
    strategy_name: str
    enabled: bool


class AddStrategyRequest(BaseModel):
    strategy_name: str


class EngineStatus(BaseModel):
    engine_id: str
    venue: str
    run_mode: str
    enabled: bool
    strategies: List[str]
    runtime_status: str
    symbols: Optional[List[str]] = None
    live: Dict[str, Any] = Field(default_factory=dict)
    backtest: Dict[str, Any] = Field(default_factory=dict)
    control: Dict[str, Any] = Field(default_factory=dict)

