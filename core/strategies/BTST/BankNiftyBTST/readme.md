# Bank Nifty BTST

## Rules (Indian market)

1. **9:20 IST** — find Bank Nifty CE and PE strikes with premium **80–120** (target ~100); place **HYBRID_GTT** live entry at **premium × 1.5** (e.g. 100 → limit 150).
2. **After MAIN fill** — arm **SL-M SELL** (`MAIN_SL`) at **50% of limit price** (limit 150 → SL trigger 75). SL uses limit_price from BTST meta, not fill price.
3. **15:20 IST** — cancel unfilled ENTRY (GTT, fallback LIMIT, and GttFallbackBook watches).
4. **If SL not hit** — exit next session at **9:25 IST** (BTST square-off).

## HYBRID_GTT execution (live only)

`execution_mode: HYBRID_GTT` via `GttFallbackBook` (`core/orderExecution/gtt_fallback_book.py`):

1. Place Dhan **Forever (GTT)** LIMIT BUY at trigger/limit = limit_price.
2. Engine watches **ask** on subscribed option symbols via **push** `QuoteUpdated` from feed ticks (`source: feed` → `GttFallbackBook.on_quote`); REST/provider `tick()` only if feed quiet ≥3s.
3. When **ask <= limit_price** and GTT still unfilled → cancel Forever order → place **resting LIMIT BUY @ limit_price**.
4. Fill from either path triggers `on_main_entry_filled` → SL-M as above.

`gtt_fallback` spec on intent:
```json
{
  "trigger_field": "ask",
  "trigger_op": "<=",
  "active_until": "15:20"
}
```

Backtest / paper: plain LIMIT at limit_price (no GTT, no fallback).

## Eval mode

| Mode | Path |
|------|------|
| **Live** | `scheduled_times` [9:20, 15:20, 9:25] — wall-clock, no candle aggregator |
| **Backtest** | `backtest_timeframe = 5` — 5m bar close aligned to scheduled slots |

## Option series

- `expiryType = MONTHLY`
- `dhan_monthly_expiry_weekday = 1` (Tuesday, BANKNIFTY monthly)
- `dhan_monthly_rollover_days_before_expiry = 3` — roll to next monthly series 3 days before expiry

## Run

```bash
python -m run.main --engine-id dhan_banknifty_btst
```

## Wiring

| Item | Location |
|------|----------|
| Strategy | `core/strategies/BTST/BankNiftyBTST/BankNiftyBTST.py` |
| Registry | `STRATEGY_MAP["BankNiftyBTST"]` |
| GTT fallback | `order_router.gtt_fallback_book` |
| Engine job | `run/config.py` → `dhan_banknifty_btst` |
| Symbol | `BANKNIFTY` |
| Dhan securityId | `25` (`dhan_option_security_id`) |

## Backtest data

DHAN expired option CSVs or rolling-option API. Prefer **5m** bars under `DHAN_EXPIRED_OPTION_CHAIN_ROOT` for Bank Nifty monthly series.
