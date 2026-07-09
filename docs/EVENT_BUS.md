# Event bus (live engine)

In-process publish/subscribe layer decoupling market, schedule, execution, and feed health flows.

## Package

```
core/events/
  types.py           EventType, Event, make_event()
  bus.py             EventBus (sync, priority-ordered)
  context.py         EngineEventContext
  subscriptions.py   Resolve strategy.yaml → enabled events / filters
  wiring.py          wire_event_bus(engine) — manifest-driven registration
  handlers/          BarClosed, ScheduledSlot, IntentCreated, QuoteUpdated, fills, feed
```

## Events

| Event | Publisher | Subscribers |
|-------|-----------|-------------|
| `BarClosed` | LiveEngine (closed bar pipeline) | Exit handler (p10) → Entry handler (p20) |
| `ScheduledSlot` | LiveEngine scheduler | ScheduledEvalHandler |
| `QuoteUpdated` | Feed tick drain (watched GTT symbols); maintenance every loop | GttFallbackBook `on_quote` / `maintenance_tick` |
| `IntentCreated` | Strategy eval / `_run_strategy` | ExecutionHandler → OMS enqueue |
| `IntentFilled` | OrderRouter `process_fill` | Fill audit |
| `PositionClosed` | OrderRouter when flat | Fill audit |
| `FeedDisconnected` | Feed stall detector | FeedSupervisor |
| `FeedRecovered` | Feed stall cleared | FeedSupervisor |

## Wiring (manifest-driven)

`LiveEngine.start()` calls `wire_event_bus(self)`.

Handlers are registered from the **union** of loaded strategies' `subscriptions` (generated into `core/strategies/_generated/subscriptions.py`). When `subscriptions:` is omitted in `strategy.yaml`, defaults come from `schedule.eval_mode` and `execution` (GTT → `QuoteUpdated`).

Always-on for any live engine: `IntentCreated`, `IntentFilled`, `PositionClosed`, `FeedDisconnected`, `FeedRecovered`.

`BarClosed` handlers use a filter built from each strategy's `timeframes` / `symbols` lists (empty = any).

## QuoteUpdated (push, not poll)

```
WS tick → tick_queue → _drain_tick_queue
  → candle_aggregator.on_tick
  → if symbol in GttFallbackBook.active_trading_symbols:
       publish QuoteUpdated {symbol, bid, ask, ltp, source: feed}
  → GttQuoteHandler → book.on_quote(symbol, quote)
```

Main loop still calls `_run_gtt_fallback_tick` for **maintenance** only (`source: gtt_maintenance` → fill sync + `active_until`). If no feed quote for ≥3s while watches are active, falls back to `book.tick()` (QuoteProvider: feed cache + REST).

Scheduled-only engines (empty timeframes) still get a tick queue when `subscriptions.QuoteUpdated` is enabled (`LiveEngine.needs_tick_queue`), and drain ticks while GTT watches are active.

## Audit log

Set `ALGO_EVENT_TAP=0` to disable JSONL tap. Default: `logs/{engine_id}_events.jsonl`.

## Adding a strategy subscriber

Prefer `strategy.yaml` — no `wiring.py` / `live_engine.py` edits:

```yaml
subscriptions:
  BarClosed:
    enabled: true
    timeframes: ["15"]
  QuoteUpdated: false
```

Then:

```bash
python -m tools.strategy_manifest generate
```

Ad-hoc handler (infra / debugging only):

```python
engine.event_bus.subscribe(
    EventType.BAR_CLOSED,
    my_handler,
    priority=15,
    name="my_handler",
    filter_fn=lambda e: e.payload.get("symbol") == "NIFTY",
)
```

## Tests

```bash
python -c "from tests.test_event_bus import *; tests=[test_publish_priority_order,test_filter_skips_handler,test_handler_exception_does_not_block_others,test_default_subscriptions_live_feed,test_default_subscriptions_scheduled_gtt,test_resolve_subscriptions_override,test_collect_enabled_events_union,test_bar_closed_filter_timeframe,test_resolve_strategy_subscriptions_from_table,test_gtt_quote_handler_push_calls_on_quote,test_gtt_quote_handler_maintenance]; [t() for t in tests]; print(f'{len(tests)} ok')"
```
