# NiftyDOS Strategy - Complete Scenarios & Test Cases

> **Strategy**: NIFTY Supertrend + MA9 + ADX Directional Option Selling  
> **File**: `/root/Dhan-codebase/core/strategies/IBBM/NiftyDOS/NiftyDOS.py`  
> **Generated**: 2026-08-22

---

## 🎯 Strategy Overview

| Parameter | Value |
|-----------|-------|
| **Underlying** | NIFTY |
| **Expiry** | Weekly (Tuesday) |
| **Timeframe** | 30-min candles (eval at close), 5-min TP/SL checks |
| **Indicators** | Supertrend(16,2), SMA9, ADX(14) |
| **Position** | Hedged structure: Short MAIN + Long HEDGE (500 pts OTM) |
| **Premium Range** | 80 - 105 (strict) |
| **Margin/Lot** | ₹50,000 (configurable) |

---

## 📊 INDICATOR HISTORY INTEGRATION

The strategy now integrates with the shared indicator history system (`logs/indicators/NIFTY/30/indicator_history.jsonl`). 

### How it works:
1. **Live mode**: `IndicatorManager` computes Supertrend, SMA, ADX on each closed 30-min bar and appends to shared JSONL
2. **Strategy reads**: `enrich_candle_for_strategy` merges computed indicators into the candle dict
3. **Strategy signals**: Uses `supertrend_direction`, `supertrend_is_bullish`, `sma9`, `adx_14` from candle dict
4. **Backtest mode**: `prepare_indicators()` computes indicators locally (same column names)

### Key attributes for indicator_manager:
| Attribute | Value | Purpose |
|-----------|-------|---------|
| `supertrend_length` | 16 | Supertrend ATR period |
| `supertrend_factor` | 2.0 | Supertrend multiplier |
| `sma_period` | 9 | SMA period |
| `adx_period` | 14 | ADX period |

### Persisted indicator keys (written to JSONL):
- `supertrend`, `supertrend_direction`, `supertrend_is_bullish`, `supertrend_upper`, `supertrend_lower`, `supertrend_atr`
- `sma9`, `prev_sma9`
- `adx_14`, `adx_di_plus_14`, `adx_di_minus_14`

### Legacy aliases (kept for backward compatibility):
- `supertrend_atr_period` → maps to `supertrend_length`
- `supertrend_multiplier` → maps to `supertrend_factor`
- `ma_period` → maps to `sma_period`

---

## 1️⃣ ENTRY SCENARIOS

| # | Scenario | Conditions | Expected Behavior |
|---|----------|------------|-------------------|
| **E1** | **Normal Bullish Entry** | ST=BULLISH, non-expiry day, valid PUT strike 80-105 on current weekly | Enter Short PUT + Long PUT hedge on current weekly |
| **E2** | **Normal Bearish Entry** | ST=BEARISH, non-expiry day, valid CALL strike 80-105 on current weekly | Enter Short CALL + Long CALL hedge on current weekly |
| **E3** | **Expiry Day Entry** | Any ST signal, **Tuesday (weekly expiry)** | **Force NEXT_WEEKLY expiry** even if valid strike on current weekly |
| **E4** | **Current Weekly No Strike** | Non-expiry day, no OTM strike 80-105 on current weekly | Auto-roll to NEXT_WEEKLY, enter there |
| **E5** | **Both Weeks No Strike** | No valid strike 80-105 on WEEKLY or NEXT_WEEKLY | Skip entry, log warning |
| **E6** | **Holiday/Event Day** | NSE holiday or `event_no_trade_dates` | No evaluation, no entry |
| **E7** | **Weekly Expiry Day** | `_is_weekly_expiry_day()` = True | **Allow entry** - `_build_entry_intents` forces NEXT_WEEKLY expiry |
| **E8** | **After 3:15 PM** | Time ≥ 15:15, ADX < 25 | No new initial entry |
| **E9** | **After 3:15 PM with ADX ≥ 25** | Time ≥ 15:15, ADX ≥ 25 | Allow entry (reentry only per rules) |
| **E10** | **Duplicate Signal Prevention** | Same structure_id + bar_open_key in `_entry_signaled_keys` | Skip duplicate entry |
| **E11** | **Position Already Exists** | Open MAIN position for structure_id | Skip entry |
| **E12** | **Pending Intent Exists** | Intent store has pending ENTRY for structure_id | Skip entry |
| **E13** | **9:45 AM Entry (No Open Position)** | 9:45 AM candle, no open MAIN position, ST=BULLISH/BEARISH | Enter Short PUT/CALL on current weekly (or NEXT_WEEKLY on expiry day) |
| **E14** | **9:45 AM Entry (Position Exists)** | 9:45 AM candle, MAIN position already open | Skip entry (no duplicate) |

---

## 2️⃣ EXIT SCENARIOS

| # | Scenario | Trigger | Exit Logic |
|---|----------|---------|------------|
| **X1** | **Stop Loss Hit** | Combined P&L ≤ -3.5% of margin | Exit MAIN + HEDGE, schedule SL reentry next candle |
| **X2** | **Take Profit Hit** | Combined P&L ≥ 3.7% of margin | Exit MAIN + HEDGE, immediate TP reentry same candle |
| **X3** | **EOD Exit (Post 3PM)** | After 15:15, \|P&L\| ≥ 3% of margin | Exit MAIN + HEDGE, no immediate reentry |
| **X4** | **Supertrend Flip: PUT→BEARISH** | Holding Short PUT, ST flips to BEARISH | Exit PUT, **immediate CALL reentry same candle** |
| **X5** | **Supertrend Flip: CALL→BULLISH** | Holding Short CALL, ST flips to BULLISH | Exit CALL, **immediate PUT reentry same candle** |
| **X6** | **9:15 AM Price Opposite Signal** | 9:15 AM, price < MA9 (bullish ST) or price > MA9 (bearish ST) | Exit handled in position management |

---

## 3️⃣ REENTRY SCENARIOS

| # | Reentry Type | Timing | Conditions | Behavior |
|---|--------------|--------|------------|----------|
| **R1** | **SL Reentry** | **Next 30-min candle** | ADX > 25, MA aligned, candle favors trend | Enter same direction |
| **R2** | **TP Reentry** | **Same 5-min candle** | MA aligned (no ADX/candle check) | Enter same direction |
| **R3** | **ST Flip Reentry** | **Same 5-min candle** | Only ADX ≥ 25 after 3:15 PM check | Enter **opposite direction** |
| **R4** | **SL Reentry Blocked** | Next candle | Holiday/expiry day, after 3:15 PM ADX<25, MA misaligned, candle against trend | Skip, log reason |
| **R5** | **TP Reentry Blocked** | Same candle | Holiday/expiry day, after 3:15 PM ADX<25 | Skip |
| **R6** | **ST Flip Reentry Blocked** | Same candle | Holiday/expiry day, after 3:15 PM ADX<25 | Skip |

---

## 4️⃣ EDGE CASES & BOUNDARY CONDITIONS

| # | Edge Case | Handling |
|---|-----------|----------|
| **B1** | **Margin Calculation Fails** | Falls back: Dhan API → Broker API → `margin_per_lot` config |
| **B2** | **Premium Unavailable (Live)** | `_get_current_premium` returns None → P&L = 0 → No TP/SL trigger |
| **B3** | **Hedge Missing** | P&L calculated from MAIN only |
| **B4** | **ST Signal NaN** | `_get_supertrend_signal` returns None → No entry/exit |
| **B5** | **MA/ADX NaN** | Reentry conditions fail gracefully |
| **B6** | **Multiple SL Hits Same Candle** | `_sl_hit_structure.clear()` after processing - only 1 reentry per candle |
| **B7** | **ST Flip + TP Same Candle** | Both `_tp_hit_pending` and `_st_flip_reentry_pending` can trigger |
| **B8** | **Premium Exactly at Boundary** | Premium 80.0 or 105.0 → **REJECTED** (strict `< min_prem` or `> max_prem`) |
| **B9** | **Strike Not OTM** | `_strike_is_otm` rejects ITM/ATM strikes |
| **B10** | **Trade Date ≥ Expiry** | Entry blocked in `_build_entry_intents` line 752 |

---

## 6️⃣ TIME-BASED SCENARIOS

| Time | Scenario | Behavior |
|------|----------|----------|
| **9:15 AM** | Price opposite to ST signal | Exit signal generated (handled in position mgmt) |
| **9:45 AM** | No open position | **Create position on Supertrend direction** (PUT if BULLISH, CALL if BEARISH) |
| **9:45 AM** | Position already open | Skip entry |
| **9:45 AM on Expiry Day** | No open position | Create position on NEXT_WEEKLY expiry |
| **9:15-15:15** | Normal trading | All entry/exit/reentry logic active |
| **15:15-15:30** | EOD zone | No new initial entry if ADX<25; EOD exit check active; reentry allowed if ADX≥25 |
| **Post 15:30** | Market closed | No evaluation (live mode) |

---

## 7️⃣ TEST CASE MATRIX (Executable Pseudocode)

### Entry Tests
```python
# TC-E1: Normal entry - bullish
# Given: ST=BULLISH, MA9 bullish, ADX=30, spot=24500, PUT 24400 premium=92, non-expiry Wed
# Expect: Short PUT 24400 + Long PUT 23900 (hedge) on current weekly

# TC-E2: Normal entry - bearish  
# Given: ST=BEARISH, MA9 bearish, ADX=30, spot=24500, CALL 24600 premium=92, non-expiry Wed
# Expect: Short CALL 24600 + Long CALL 25100 on current weekly

# TC-E3: Expiry day forces next weekly
# Given: Tuesday (expiry), ST=BULLISH, PUT 24400 premium=92 on current weekly, 24450 premium=90 on next weekly
# Expect: Short PUT 24450 on NEXT_WEEKLY (not current weekly)

# TC-E4: Current weekly no strike → next weekly
# Given: Wed, ST=BULLISH, no PUT 80-105 on current weekly, PUT 24450 premium=95 on next weekly
# Expect: Short PUT 24450 on NEXT_WEEKLY

# TC-E5: Holiday - no entry
# Given: NSE holiday, ST=BULLISH
# Expect: should_evaluate()=False, no entry

# TC-E6: 9:45 AM entry - bullish, no position
# Given: 9:45 AM Wed, ST=BULLISH, no open position, PUT 24400 premium=92
# Expect: Short PUT 24400 + Long PUT 23900 on current weekly

# TC-E7: 9:45 AM entry - bearish, no position
# Given: 9:45 AM Wed, ST=BEARISH, no open position, CALL 24600 premium=92
# Expect: Short CALL 24600 + Long CALL 25100 on current weekly

# TC-E8: 9:45 AM entry on expiry day
# Given: 9:45 AM Tuesday (expiry), ST=BULLISH, no open position, PUT 24450 premium=90 on next weekly
# Expect: Short PUT 24450 + Long PUT 23950 on NEXT_WEEKLY

# TC-E9: 9:45 AM entry skipped - position exists
# Given: 9:45 AM Wed, ST=BULLISH, Short PUT already open from 9:15
# Expect: No new entry, existing position continues
```

### Exit Tests
```python
# TC-X1: SL hit
# Given: Short PUT, margin=50000, entry_premium=92, current_premium=110 (loss > 3.5%=1750)
# Expect: should_exit()=True, _sl_hit_structure set

# TC-X2: TP hit  
# Given: Short CALL, margin=50000, entry_premium=95, current_premium=70 (profit > 3.7%=1850)
# Expect: should_exit()=True, _tp_hit_pending set

# TC-X3: EOD exit
# Given: 15:20, P&L=±1600 (3.2% of 50000)
# Expect: should_exit()=True (EOD)

# TC-X4: ST flip PUT→BEARISH
# Given: Holding Short PUT, ST flips BEARISH
# Expect: should_exit()=True, _st_flip_reentry_pending={struct_id: "CALL"}

# TC-X5: ST flip CALL→BULLISH
# Given: Holding Short CALL, ST flips BULLISH
# Expect: should_exit()=True, _st_flip_reentry_pending={struct_id: "PUT"}
```

### Reentry Tests
```python
# TC-R1: SL reentry success
# Given: SL hit prev candle, next candle: ADX=30, MA bullish, green candle, ST=BULLISH
# Expect: _attempt_sl_reentry() returns new PUT entry intents

# TC-R2: SL reentry fail - ADX low
# Given: SL hit, next candle ADX=20
# Expect: Reentry skipped, logged

# TC-R3: TP reentry success
# Given: TP hit, same candle: MA bullish (for PUT)
# Expect: _attempt_immediate_reentry() returns new PUT entry intents

# TC-R4: ST flip reentry success
# Given: ST flip PUT→BEARISH, same candle: ADX=30, after 15:15
# Expect: _attempt_st_flip_reentry() returns new CALL entry intents

# TC-R5: ST flip reentry fail - after 15:15 ADX<25
# Given: ST flip at 15:20, ADX=20
# Expect: Reentry skipped
```

### Margin/P&L Tests
```python
# TC-M1: Margin from Dhan API
# Given: Valid Dhan credentials, positions exist
# Expect: _get_structure_capital() returns Dhan API margin

# TC-M2: Margin fallback chain
# Given: Dhan API fails, broker API fails
# Expect: Returns margin_per_lot * qty (50000 * lots)

# TC-M3: P&L calculation MAIN only
# Given: Hedge position missing
# Expect: P&L = MAIN P&L only
```

---

## 8️⃣ STATE TRACKING VARIABLES (for test verification)

| Variable | Purpose | Key Test Assertions |
|----------|---------|---------------------|
| `_entry_signaled_keys` | Prevent duplicate entries | Size increases on entry, key format: `struct_id\|bar_time` |
| `_evaluated_signal_keys` | One eval per 30-min bar | Size increases on `should_evaluate()` |
| `_sl_hit_structure` | SL reentry queue | Populated on SL, cleared in `on_candle` after processing |
| `_tp_hit_pending` | TP immediate reentry | Populated on TP, consumed in `on_position_exit` |
| `_st_flip_reentry_pending` | ST flip immediate reentry | Populated on ST flip, consumed in `on_position_exit` |
| `_structure_main_entry_price` | TP/SL calc | Set on entry, cleared on exit |
| `_structure_hedge_entry_price` | TP/SL calc | Set on entry, cleared on exit |
| `_structure_type` | CALL/PUT for TP/SL % | Set on entry, cleared on exit |

---

## 9️⃣ CONFIGURATION PARAMETERS (strategy.yaml overrideable)

```yaml
params:
  # Indicator parameters (for indicator_manager)
  supertrend_length: 16
  supertrend_factor: 2.0
  sma_period: 9
  adx_period: 14
  # Legacy aliases (also supported)
  supertrend_atr_period: 16
  supertrend_multiplier: 2.0
  ma_period: 9
  premium_min: 80
  premium_max: 105
  hedge_distance_points: 500
  weekly_expiry_weekday: 1  # Tuesday
  call_sl_pct: 3.5
  call_tp_pct: 3.7
  put_sl_pct: 3.5
  put_tp_pct: 3.7
  margin_per_lot: 50000
  reentry_adx_threshold: 25
  eod_exit_pct: 3.0

event_no_trade_dates:
  - "2024-01-26"  # Republic Day
  - "2024-03-08"  # Holi
```

---

## 🔟 BACKTEST VS LIVE DIFFERENCES

| Aspect | Backtest | Live |
|--------|----------|------|
| `should_evaluate` | Every closed 30-min bar | Only within 5 min after bar close |
| Premium data | `get_option_price_at_candle` | Option chain snapshot |
| Margin | Fallback to `margin_per_lot` | Dhan API → Broker → Fallback |
| Order execution | Simulated | Real Dhan API via `dhan_live_order_placement.py` |

---

## 📝 Key Implementation Notes

### Recent Changes (This Session)
1. **ST Flip Immediate Reentry** (NEW): On Supertrend reversal, exit current position AND immediately enter opposite direction on same candle
2. **Expiry Day Forced Next Weekly** (NEW): On Tuesday expiry, always use NEXT_WEEKLY expiry for new entries
3. **TP Immediate Reentry** (EXISTING): On TP hit, reenter same direction same candle
4. **SL Next-Candle Reentry** (EXISTING): On SL hit, reenter next candle with full MA/ADX/candle checks

### Critical Code Locations
| Logic | Method | Lines |
|-------|--------|-------|
| Entry gating | `should_evaluate` | ~840-870 |
| Entry building | `_build_entry_intents` | ~660-830 |
| Expiry day logic | `_build_entry_intents` | ~690-730 |
| 9:45 AM entry | `on_candle` | ~927-960 |
| Exit checks | `should_exit` | ~1170-1220 |
| ST flip detection | `should_exit` | ~1190-1220 |
| Position exit | `on_position_exit` | ~1220-1285 |
| SL reentry | `_attempt_sl_reentry` | ~1325-1365 |
| TP reentry | `_attempt_immediate_reentry` | ~1365-1380 |
| ST flip reentry | `_attempt_st_flip_reentry` | ~1380-1400 |
| Indicator preparation | `prepare_indicators` | ~310-345 |
| Persisted keys | `persisted_indicator_keys` | ~345-370 |
| Signal methods | `_get_supertrend_signal`, `_get_ma_signal`, `_get_adx_value` | ~650-680 |

---

## ✅ Test Coverage Checklist

- [ ] Entry: Normal bullish/bearish
- [ ] Entry: Expiry day forces next weekly
- [ ] Entry: Fallback to next weekly
- [ ] Entry: Holiday/event day blocked
- [ ] Entry: After 3:15 PM blocked (ADX<25)
- [ ] Entry: 9:45 AM - no position (bullish/bearish)
- [ ] Entry: 9:45 AM - expiry day (uses NEXT_WEEKLY)
- [ ] Entry: 9:45 AM - position exists (skipped)
- [ ] Exit: SL hit
- [ ] Exit: TP hit
- [ ] Exit: EOD (post 3PM)
- [ ] Exit: ST flip PUT→BEARISH
- [ ] Exit: ST flip CALL→BULLISH
- [ ] Reentry: SL (next candle, full checks)
- [ ] Reentry: TP (same candle, MA only)
- [ ] Reentry: ST flip (same candle, opposite direction)
- [ ] Reentry: Blocked scenarios
- [ ] Indicator History: Live 30-min bar logs to JSONL with correct keys
- [ ] Indicator History: Strategy reads supertrend_direction, supertrend_is_bullish, sma9, adx_14
- [ ] Indicator History: Backtest computes same column names
- [ ] Margin: Dhan API → Broker → Fallback chain
- [ ] P&L: MAIN only (hedge missing)
- [ ] State: Tracking vars updated/cleared correctly