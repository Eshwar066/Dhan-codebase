# IPO Anchor VWAP (registry: IPOBreakout)

**Class:** `IPOBreakout` in `IPOBreakout.py`  
**Strategy name (runtime):** `IPOAnchorVWAP` — registry key is `IPOBreakout`.

Equity strategy for **Dhan** IPO listings: anchor VWAP + staged scale-in after listing stabilization filters.

## Core logic

1. **Anchor VWAP** — cumulative VWAP from listing (updated each bar).
2. **should_evaluate** — `close > anchor_vwap` (break above anchor).
3. **Staged entry** — scale in quarters (¼ → full) using:
   - Listing high / stabilization counters
   - 5-period EMA on highs/lows
   - Stage state per symbol (`_stage_state`)

4. **Exit** — `should_exit` / `on_position_exit` use EMA structure and stage rules (not generic ORB/ADX from old draft docs).

## Context

- `required_context = ["instrument_store"]`
- Universe from `EquityUniverseService` / IPO filter in engine factory

## Eval

- Driven by equity candle feed (not options)
- No `IndiaMktMixins` option chain for entry (mixin used for shared helpers only)

## Roadmap (not implemented)

- Cross-above filter vs simple `close > vwap`
- Minimum % distance from anchor
- Volume expansion filter
- Same-day re-entry block
- Portfolio-level capital allocator

## Run

Configure job in `run/config.py` (`dhan_ipo_breakout` or equivalent enabled job).
