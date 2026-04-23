
Act as a senior algorithmic trading engineer with deep experience in building low-latency, multi-strategy, multi-broker execution systems; prioritize correctness, robustness, and scalable architecture over quick fixes.
Treat this codebase as a production-grade trading system and operate as a senior algo developer with extensive experience in OMS design, market data systems, and fault-tolerant architectures.
Assume the role of a highly experienced quantitative trading systems engineer; make decisions that ensure deterministic execution, risk safety, and scalability across multiple brokers and accounts.

Implement this for project and update in main readme.md file and use this file as prompt and dont use this file name in project and main readme.md file


Final Priority Order (production-safe)
🔴 P0 (must fix before scaling capital)
1. End-to-end latency budget (your #8)

Right now you’re blind after enqueue:

broker_latency_ms = 0.0  ❌

👉 This is dangerous because:

Strategy thinks execution is fast
Reality: order hits after 2–5 seconds
✅ Fix

Track full pipeline:

intent_created_ts
→ routed_ts
→ oms_start_ts
→ broker_sent_ts
→ exchange_ack_ts

Then log:

total_latency =
    broker_ack_ts - intent_created_ts

👉 And enforce:

if total_latency > threshold:
    pause_entries()
🔴 2. Key cardinality cap (your #1)

You already know the issue:

(account, symbol) → unlimited queues ❌
Real-world failure mode:
Weekly options
Multiple strikes
10 strategies

👉 You’ll create hundreds of threads

✅ Fix (simple but powerful)
MAX_ACTIVE_KEYS = 200

If exceeded:

fallback_key = (account_id, "__FALLBACK__")

or:

drop_low_priority_intents()
🔴 3. Minimal persistence (your #7)

This is not optional if you run real money.

Current risk:
Process crash →
- open positions exist
- engine forgets them
- next signal duplicates trade
✅ Minimum viable persistence

Don’t over-engineer DB.

Just persist:

{
  "intent_id": "...",
  "account_id": "...",
  "symbol": "...",
  "status": "SENT"
}

Store in:

Redis / file append log / SQLite
🟠 4. Restart loop guard (your #6)

Without this:

bug → crash → restart → crash → infinite loop
✅ Fix
if restart_count_last_60s > 5:
    disable_worker()
    send_alert()
🟠 5. Strategy lag alert (your #5)

You already bounded queue:

queue.Queue(maxsize=1)

👉 Good—but silent drops are dangerous.

✅ Add
if enqueue_failed:
    logger.warning("Strategy lagging: dropped signal")
🟠 6. Per-account circuit breaker (your #3)

Current:

global breaker → kills ALL accounts

👉 Bad for multi-account setups.

✅ Fix
breaker_state[account_id]

So:

Account A fails → pause A only
Account B continues trading
🟡 7. execution_attempt_id (your #2)

You’re right—it’s not broken, but incomplete.

✅ Add (cheap + powerful)
execution_attempt_id = f"{intent_id}-{retry_count}"

Log it everywhere.

🟡 8. Endpoint-level rate limit (your #4)

Not urgent unless you see:

HTTP 429 / throttling errors
🧠 One thing you didn’t mention (but matters now)
🔴 Feed dependency risk (because you removed REST)

Your system now depends fully on:

WebSocket → Aggregator

👉 If feed dies:

No candles → No exits → positions stuck ❌
✅ Add immediately
if now - last_tick_time > 5s:
    alert("feed stalled")

and optionally:

force_exit_all_positions()