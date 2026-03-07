# Order Execution

**Purpose:** Route intents from strategies through risk checks to the broker and update positions. Uses **OrderIntent** (dataclass) and **StrategyContext** (typed context from engine).

## Flow

```
Strategy.on_candle(candle, ctx: StrategyContext)
    → returns OrderIntent(s)
        → OrderRouter.process_intent(intent, price_map)
            → RiskManager.allow_intent(intent, price_map)
            → Broker.place_order(intent, execution_price)
            → IntentStore.update(...)
            → (on fill) PositionManager.on_fill(...)
```

## Files

| File                  | Role                                                                                                             |
| --------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `order_router.py`     | `process_intent(intent, price_map)` – risk check, slippage, broker.place_order, intent_store update              |
| `risk_manager.py`     | `allow_intent(intent, price_map, candle_ts)` – position limits, exposure, duplicate prevention                   |
| `intent_store.py`     | Intent lifecycle: CREATED → SENT → FILLED / REJECTED; idempotency                                                |
| `position_manager.py` | Positions, `on_fill()`, `get_open_positions()`, `get_hedge_for()`, `has_open_structure()`, reconcile_with_broker |
| `order_state.py`      | Order state tracking (if used)                                                                                   |
| `slippage.py`         | Slippage model for execution price                                                                               |

## Intent lifecycle

- **CREATED** – strategy produced intent
- **VALIDATED** – risk manager allowed (conceptually; router may not persist this)
- **SENT** – passed to broker
- **FILLED** / **REJECTED** – after broker response / fill

## Dependencies

- **OrderIntent** from `core.models.order_intent`
- **Broker** (BaseBroker impl) from `core.broker`
- **StrategyContext** built in `core.engine.base_engine.build_context()`

## Risk Manager

Answers: _“Is this intent safe to execute given current positions and limits?”_

Can include: portfolio exposure, per-symbol limits, max position size, no double-direction entries, strategy-level limits, cooldown. Extend in `risk_manager.py`.

=============================================================
## order router--> order slicing

Perfect. ✅
Now you’re talking about execution layer slicing, not strategy scaling.

You want:

In each account
If qty is large
Slice order
Place slices at best bid / best ask
Do this consistently across all accounts

Good. This belongs 100% inside OrderRouter / Execution layer, not strategy.

🎯 What You Want Conceptually

Instead of:

BUY 1000 lots → single LIMIT @ best_bid

You want:

BUY 1000 lots →
50 lots @ best_bid
wait
50 lots @ best_bid
wait
...
until filled

And same logic applied per account.

🏗 Correct Architecture Placement

Do NOT put slicing in:

Strategy ❌

Broker ❌

Put it inside:

OrderRouter

Because:

Strategy decides direction + size.

Router decides how to execute.

Clean separation.

🧠 Execution Design (Production Clean Version)
Step 1 — Add execution config

Inside strategy or engine config:

self.slice_size = 50
self.slice_interval_sec = 1
self.max_retries = 5
Step 2 — Modify OrderRouter

Instead of:

broker.place_order(intent)

Do:

if intent.qty > self.slice_size:
self.\_execute_sliced(intent)
else:
broker.place_order(intent)
🔥 Core Slicing Logic

Pseudo clean implementation:

def \_execute_sliced(self, intent):
remaining_qty = intent.qty

    while remaining_qty > 0:
        slice_qty = min(self.slice_size, remaining_qty)

        # get fresh best bid/ask
        best_bid = self.data_feed.get_best_bid(intent.symbol)
        best_ask = self.data_feed.get_best_ask(intent.symbol)

        if intent.side == "BUY":
            price = best_bid
        else:
            price = best_ask

        slice_intent = intent.copy_with_new_qty(slice_qty, price)

        self.broker.place_order(slice_intent)

        remaining_qty -= slice_qty

        time.sleep(self.slice_interval_sec)

🚨 Very Important: Refresh L2 Each Slice

Do NOT reuse old best_bid.

Each slice must:

Pull fresh L2

Recompute price

Otherwise you’ll stack behind yourself.

🧠 Why This Works

You are:

Staying passive (maker)

Reducing footprint

Reducing slippage

Avoiding book sweep

This is passive liquidity harvesting.

⚠️ But There Is One More Real-World Issue

If:

Best bid size = 10 BTC
You place 50 BTC

You become the book.

Then:

Next slice uses same price.

You're effectively layering your own orders.

That’s fine — but understand behavior.

🧠 Advanced Improvement (Optional Later)

Instead of fixed slice size:

Use liquidity-aware slice:

available = best_bid_size
slice_qty = min(available \* 0.5, remaining_qty)

So you never exceed 50% of visible liquidity.

More professional.

🔥 For Multi-Account Case

If you have:

5 accounts × 200 lots each

You simply call same slicing logic per broker instance.

Each account runs identical slicing loop independently.

Architecture stays clean.

📌 Important: Track Fills

Right now you are assuming:

Place → fully filled.

For slicing to work properly, you should:

Listen to order updates

Track filled_qty

Reduce remaining based on actual fills

Otherwise partial fills break accounting.

🧠 Clean Execution Flow After Upgrade
Strategy → Intent (1000)
OrderRouter
→ Split by account
→ For each account:
→ Execute sliced loop
→ Pull fresh L2
→ Place LIMIT @ best_bid/ask
→ Wait
→ Track fills
→ Continue
Broker
Exchange

Now you have real execution engine.

🎯 Final Answer

Yes — slice in OrderRouter.

Yes — apply per account.

Yes — refresh L2 every slice.

No — do not change strategy.

If you want next, we can design:

A non-blocking async slicing engine
(so your system doesn’t freeze while slicing)

That’s the next professional upgrade.
