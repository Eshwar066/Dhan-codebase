# OI Positional Buy (OIPositionalBuy)

Registry: `STRATEGY_MAP["OIPositionalBuy"]`  
Implementation: `core/strategies/OpenIntrest/OIPostionalBuy/OIPosBuy.py`

## Schedule (IST)

| Slot | Action |
|------|--------|
| **09:30** | Full option chain snapshot (benchmark for day) |
| **10:45** | OI review + optional entry |
| **15:15** | OI review + optional entry / overnight hold decision |

Eval uses **15m** bars; `on_candle` gates by IST slot time.

## Expiry

`dhan_monthly_rollover_after_calendar_day = 15`:
- Trade day **1–15** → current month series
- Trade day **16+** → next month series

Strikes: **100-point** steps (`otm_strike_step = 100`).

## Entry

- Premium band **170–220** for CE/PE scan
- vs 09:30 snapshot: pattern must be **long buildup** or **short covering**
- Premium must **not** be up ≥**80%** vs 09:30 benchmark (`MAX_PREM_RISE_VS_930_PCT`)
- One structure per symbol/side per day (guards in strategy)

## Bracket exits (resting SL-M on broker / sim)

After MAIN BUY fill, `on_main_entry_filled` arms:

| Leg | Rule |
|-----|------|
| **MAIN_TARGET** | SL-M SELL when premium ≥ **1.5×** entry (`TARGET_MULT`) |
| **MAIN_SL** | SL-M SELL when premium ≤ **40%** below entry (`STOP_LOSS_FRAC = 0.40`) |

Target fill → optional **re-entry** at next slot near prior premium (`on_main_exit_filled`).  
SL fill → **no re-entry** for symbol that day.

## OI slot review (10:45 / 15:15)

If position open: compare current strike OI/premium pattern vs 09:30 benchmark.
- **long buildup** or **short covering** → hold (15:15 may hold overnight)
- **short buildup** or **long unwinding** → exit

If flat after review: same entry rules as above.

**15:15 defer:** if 15:15 snapshot missing, EOD review can defer to next check.

## Live vs backtest

- Live: 15m feed + option chain snapshots under `logs/OIPositionalBuy/`
- Backtest: DHAN expired-option CSVs per `STRATEGY_RUNTIME_SPEC`

## Note on readme vs old “intraday loop” wording

Target/SL are **broker resting SL-M legs**, not a per-tick premium loop in `on_candle`.
