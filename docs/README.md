# Runtime documentation

Architecture and execution-flow docs for the current codebase (module names match the repo).

| Document | Contents |
|----------|----------|
| **[EVENT_DRIVEN_STRATEGY_GUIDE.md](EVENT_DRIVEN_STRATEGY_GUIDE.md)** | **Add strategies, hooks, execution modes, optimization roadmap** |
| [module_map.md](module_map.md) | Package / layer diagram and responsibilities |
| [runtime_flow.md](runtime_flow.md) | Live engine startup, main loop, feeds, candles |
| [oms_flow.md](oms_flow.md) | Intent routing, OMS workers, token bucket, circuit breaker |
| [retry_state_machine.md](retry_state_machine.md) | Order retry attempts and outcomes |
| [watchdog.md](watchdog.md) | Worker health checks and restart policy |
| [sequence_flow.md](sequence_flow.md) | Candle→intent, fills, entry handoff sequences |
| [templates/STRATEGY_README.md](templates/STRATEGY_README.md) | Copy-paste template for new strategy readmes |

Diagrams use [Mermaid](https://mermaid.js.org/); render in GitHub, VS Code, or Cursor markdown preview.

Previously monolithic: `PROJECT_FLOW_CHART.md` at repo root (now a pointer).
