# Event-Driven Strategy Guide

How to add strategies and evolve this codebase toward a cleaner **event-driven** architecture.

## Current architecture (as implemented)

```
Market data events          Strategy events              Execution events
──────────────────          ───────────────              ────────────────
WS tick                     closed 60m bar               OrderIntent created
  → CandleAggregator          → should_evaluate          → intent queue
  → closed bar                → on_candle                → account router
scheduled IST slot            → should_exit              → OMS worker
  → synthetic candle          → on_candle_rollover       → broker place/fill
quote update (GttFallback)    → on_main_entry_filled     → process_trade
                                                         → position_manager
```

The system is **already multi-strategy** and **mostly event-driven** at the edges (ticks, fills, scheduled slots). The main gap is **uniform internal events** — today the live loop polls (`sleep(1)`) and calls strategy hooks directly.

---

## Extension points (use these for new strategies)

### 1. Strategy contract — `BaseStrategy`

| Hook | Purpose |
|------|---------|
| `should_evaluate(candle)` | Gate entry evaluation (crossover, slot, window) |
| `on_candle(candle, ctx)` | Produce ENTRY intents or None |
| `should_exit(pos, candle, ctx)` | Gate exit per open MAIN leg |
| `on_position_exit(pos, candle, ctx)` | EXIT intents |
| `on_candle_rollover(open_positions, candle, ctx)` | Hedge roll (IndiaMktMixins) |
| `on_main_entry_filled(...)` | Arm SL / TARGET after fill |
| `on_main_exit_filled(...)` | Re-entry / cleanup |
| `scheduled_times` | Wall-clock eval (BTST) — set `timeframe = None` |

Class attrs: `name`, `underlying_symbols`, `timeframe`, `api`, `expiryType`, `required_context`.

### Entry vs exit evaluation (live)

On each **closed bar**, `LiveEngine` runs hooks in this order:

1. **`_run_exits_and_rollover_for_closed_bar`** — for every loaded strategy with open MAIN legs:
   - `should_exit` → `on_position_exit`
   - `on_candle_rollover` (hedge roll)
   - Does **not** call `should_evaluate`
2. **`_evaluate_strategies_parallel`** — entry path only:
   - `should_evaluate(candle)` must return true
   - then `on_candle(candle, ctx)`

Implications:

| Concern | Pattern |
|---------|---------|
| Time-based exit (RSI cross, trail, partial) | Implement in `should_exit` / structure hooks; runs every closed bar |
| Entry window (crossover, slot, divergence age) | Gate in `should_evaluate` |
| Scheduled BTST / OI | `eval_mode: scheduled`, `timeframe = None`, `scheduled_times` |
| LEAPS hourly | Exits on every 60m close; entries only when `should_evaluate` allows |

Do **not** rely on `should_evaluate` for managing open positions — exits will not run if you gate the whole strategy there.

### 2. Registration

```python
# core/strategies/registry.py
STRATEGY_MAP["MyStrategy"] = {"strategy": MyStrategy, "allowed_modes": [...]}

# run/strategy_profiles.py
STRATEGY_PROFILES["MyStrategy"] = {"symbols": [...], "live": {...}, "backtest": {...}}

# core/strategies/runtime_spec.py
STRATEGY_RUNTIME_SPEC["MyStrategy"] = {"live": {...}, "backtest": {...}}

# run/config.py — ENGINE_JOBS entry (optional engine_id)
```

### 3. Execution opt-in

```python
metadata_extras = {
    "execution_mode": "HYBRID_GTT",  # or GTT, or omit for LIMIT
    "gtt_fallback": {
        "trigger_field": "ask",
        "trigger_op": "<=",
        "active_until": "15:20",
    },
}
```

Handled by `GttFallbackBook` — no strategy-local polling.

### 4. Shared India options — `IndiaMktMixins`

Chain fetch, expiry (`ExpiryResolver`), hedge intents, rollover, strike-in-premium-range.

### 5. Engine eval mode

- **Candle-driven:** set `timeframe = "60"` (or 5, 15), use `live_feed` eval mode.
- **Clock-driven:** `timeframe = None`, `scheduled_times = [time(9, 20), ...]`.

---

## Recommended optimizations (priority order)

### P0 — Quick wins (low risk)

| Item | Why | Where |
|------|-----|--------|
| **Strategy readme template** | Every new strategy documents hooks + eval mode | `docs/templates/STRATEGY_README.md` |
| **Registry name = `strategy.name`** | Fix IPOBreakout / IPOAnchorVWAP mismatch | `IPOBreakout.name` + `STRATEGY_ALIASES` |
| **LEAPS eval on every closed bar for exits** | Already in `_run_exits_and_rollover`; document | done in live_engine |
| **Scheduled engines subscribe underlying** | BTST/OI get index WS for spot + GttFallback base | `_collect_feed_symbols` |

### P1 — Event bus (implemented)

In-process bus: `core/events/`. Wired from `LiveEngine.start()` via `wire_event_bus()`.

| Event | Publisher | Subscribers |
|-------|-----------|-------------|
| `BarClosed` | LiveEngine | Exits (p10) → Entries (p20) |
| `ScheduledSlot` | LiveEngine clock | Scheduled strategies |
| `QuoteUpdated` | GTT poll | GttFallbackBook |
| `IntentCreated` | Strategy eval | ExecutionEngine enqueue |
| `IntentFilled` | OrderRouter | Audit / hooks |
| `PositionClosed` | OrderRouter | Audit / risk |
| `FeedDisconnected` / `FeedRecovered` | Feed supervisor | Entry pause flags |

See `docs/EVENT_BUS.md`. Audit: `logs/{engine_id}_events.jsonl` (`ALGO_EVENT_TAP=0` to disable).

### P2 — Strategy plugin manifest (implemented)

One `strategy.yaml` per strategy under `core/strategies/**/`. Generator:

```bash
python -m tools.strategy_manifest generate
```

Produces `core/strategies/_generated/` (registry, profiles, runtime spec, meta keys). See `docs/STRATEGY_MANIFEST.md`.

```yaml
id: MyStrategy
implementation: { module: ..., class: MyStrategy }
broker: { venue: DHAN }
schedule: { eval_mode: live_feed }
data: { backtest: { data: { option_chain: ... } } }
profile: { live: {...}, backtest: {...} }
dependencies: { meta_key: my_strategy }
```

Trading logic stays in Python; manifests replace copy-paste across registry files.

### P3 — Unified quote layer

`QuoteService` wrapping feed + REST + instrument_store:

- Single API for strategies, GttFallbackBook, exit refresh
- Push-driven: feed callback → `QuoteUpdated` event
- Removes duplicate `get_best_bid` / `get_quote_v2` paths

### P4 — Execution policy registry

Move fill-gate, HYBRID_GTT, bracket placement into pluggable policies:

```python
EXECUTION_POLICIES = {
    "LIMIT": LimitPolicy(),
    "GTT": GttPolicy(),
    "HYBRID_GTT": HybridGttPolicy(book),
    "HEDGE_GATED_BUNDLE": HedgeGatedBundlePolicy(),
}
```

OrderRouter delegates to policy by `execution_mode` — easier to add `ICEBERG`, `TWAP`, etc.

### P5 — Backtest / live parity tests

Per-strategy golden tests:

- Same candle fixture → same intents in backtest and live `build_context` path
- Expiry resolution unit tests (`LEAPS_ROLL` vs `QUARTERLY`)

### P6 — Observability

- Structured event log (`logs/{engine_id}_events.jsonl`)
- Per-strategy metrics: eval count, intent count, fill latency, GTT fallback rate
- Canvas dashboard for open watches / positions (optional)

---

## Anti-patterns to avoid

| Don't | Do instead |
|-------|------------|
| Poll broker in strategy | Return intents; let OrderRouter + fills drive state |
| Put broker API in strategy | Use `ctx.order_router`, `ctx.position_store` |
| Duplicate expiry logic | `ExpiryResolver` + `expiryType` on class |
| Hardcode IST slots in engine | `scheduled_times` on strategy |
| Document Mar/Jun/Sep quarterly for LEAPS | Document `LEAPS_ROLL` or change code |

---

## Checklist: new strategy in 30 minutes

1. [ ] Subclass `BaseStrategy` (+ `IndiaMktMixins` if options)
2. [ ] Implement `should_evaluate` + `on_candle` (+ exit hooks if positional)
3. [ ] Register in `STRATEGY_MAP` + `STRATEGY_PROFILES` + `STRATEGY_RUNTIME_SPEC`
4. [ ] Add `ENGINE_JOBS` entry in `run/config.py` (if new engine)
5. [ ] Choose eval mode: candle TF vs `scheduled_times`
6. [ ] Choose execution: default LIMIT vs `HYBRID_GTT`
7. [ ] Add `readme.md` next to strategy module (use `docs/templates/STRATEGY_README.md`)
8. [ ] Paper trade → verify logs + intent_store + positions reconcile

---

## Files to read first

| File | Why |
|------|-----|
| `core/strategies/base.py` | Hook contract |
| `core/strategies/registry.py` | Registration + `resolve_registry_key` |
| `core/strategies/meta.py` | Standard `metadata_extras` helpers |
| `docs/STRATEGY_INDEX.md` | Full strategy inventory |
| `core/engine/live_engine.py` | Main loop, scheduled + feed paths |
| `core/orderExecution/order_router.py` | Execution + fills |
| `core/orderExecution/gtt_fallback_book.py` | HYBRID_GTT pattern |
| `core/strategies/IndiaMktMixins.py` | India options shared logic |
| `docs/runtime_flow.md` | End-to-end live flow |

---

## Summary

You can **build many more strategies today** by composing `BaseStrategy` hooks + registry + optional mixins + execution modes — without rewriting the engine.

The highest-value evolution toward **fully event-driven** operation is:

1. **Event bus** (decouple live loop from strategy wiring)
2. **Push quotes** into `GttFallbackBook` (lower latency than 1s poll)
3. **Execution policy registry** (composable broker behaviors)
4. **Strategy manifest** (less copy-paste per new algo)

Implement P1–P2 when you have 5+ active live strategies or multiple engines sharing feeds.
