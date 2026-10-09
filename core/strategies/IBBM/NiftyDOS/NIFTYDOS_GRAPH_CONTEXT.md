# NiftyDOS — Graph Context (for graphify / Cursor)

Quick map of live-trading control flow after recent fixes. Read `graphify-out/wiki/NiftyDOS.md` for AST neighbors; use this for **when** things run.

## Signal gating (`should_evaluate` + `eval_signal_log_message`)

30m `signal_generated` / `on_candle` entry eval runs only when `_eval_signal_reason()` returns:

| Reason | Trigger |
|--------|---------|
| `9:45_ENTRY` | First 30m bar; open 9:15–9:18, close 9:45–9:48 IST (`entry_945_buffer_minutes=3`) |
| `ST_FLIP` | Supertrend direction changed vs `_prev_st_signal` |
| `SL_REENTRY` | `_sl_hit_structure` pending; reentry on next 30m after broker flat |
| `TP_REENTRY` / `ST_FLIP_REENTRY` | `_reentry_after_close` after TP or ST-flip exit |

Unchanged Supertrend on 30m → **no** eval, **no** `signal_generated`. Normal ST entry requires `_pending_eval_reason == "ST_FLIP"`.

5m bars: eval for TP/SL monitoring when tracking open; `eval_signal_log_message` returns `None` (no log spam).

## Strategy-scoped broker flat checks

All open/flat checks use `_strategy_open_positions()` → `get_open_positions(..., strategy=self.name)` plus `pos.strategy == self.name`.

- `_structure_still_open_at_broker` / `_is_structure_flat_at_broker` — per `structure_id`
- `_has_open_main_for_strategy` — blocks duplicate MAIN for NiftyDOS only (ignores LEAPS/other strategies on NIFTY)
- `_find_hedge_by_structure` — filters `strategy=NiftyDOS`, `tag=HEDGE`

## Exit / reentry pipeline

1. `should_exit` / `_check_tp_sl_on_5min` → `on_position_exit` → `_pending_exit_structure_ids`
2. `_finalize_pending_exits` clears tracking when `_is_structure_flat_at_broker`
3. SL: stays in `_sl_hit_structure`; reentry on next 30m via `_attempt_sl_reentry`
4. TP / ST flip: `_reentry_after_close` → `_check_and_execute_pending_reentries` when flat

## IST timestamps

`_candle_open_ts_ist`, `_candle_close_ts_ist`, `_candle_ts_ist` — prefer `bucket_ts`; coerce UTC-naive engine timestamps to IST for 9:45 and intent `candle_ts`.

## Tests

`tests/test_nifty_dos_critical_fixes.py` — signal gating, 9:45 buffer, strategy-scoped flat, IST, pending exits.

## Regenerate graph

From repo root: `graphify update .` then `graphify export wiki`.
