# DirectionalOptionSelling

> God node · 147 connections · `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`

**Community:** [DirectionalOptionSelling](DirectionalOptionSelling.md)

## Connections by Relation

### calls
- _strategy_for_tf() `EXTRACTED`
- .test_build_entry_skips_duplicate_trading_symbol() `EXTRACTED`
- .test_ensure_meta_reasserts_weekly_sleeve_from_sid() `EXTRACTED`
- .test_restore_does_not_seed_stale_4h_from_meta() `EXTRACTED`
- .test_restore_state_without_strategy_meta() `EXTRACTED`
- .test_risk_supertrend_weekly_never_falls_back_to_1h() `EXTRACTED`
- .test_sleeve_entry_enable_flags() `EXTRACTED`
- .test_symbol_config_btc_vs_eth_and_runtime_isolation() `EXTRACTED`
- .setUp() `EXTRACTED`
- .test_daily_blocked_when_htf_not_both_green() `EXTRACTED`
- .test_entry_qty_lots_differs_by_sleeve() `EXTRACTED`
- .test_entry_qty_lots_monthly_independent() `EXTRACTED`
- .test_entry_qty_lots_morning() `EXTRACTED`
- .test_fallback_meta_uses_symbol_and_structure_id() `EXTRACTED`
- .test_htf_entry_allowed_requires_1d_and_4h_match() `EXTRACTED`
- .test_htf_prefers_indicator_history_over_rest() `EXTRACTED`
- .test_is_morning_entry_slot_0830_ist() `EXTRACTED`
- .test_latest_closed_st_from_df() `EXTRACTED`
- .test_monthly_expiry_rolls_when_dte_low() `EXTRACTED`
- .test_morning_build_entry_skips_daily_htf() `EXTRACTED`
- *…and 3 more `calls` connection(s) not listed (lowest-degree first to go)*

### contains
- DirectionalOptionSelling.py `EXTRACTED`

### imports
- registry_entries.py `EXTRACTED`
- refresh_crypto_indicator_history.py `EXTRACTED`
- test_directional_option_selling.py `EXTRACTED`
- DirectionalOptionSelling/__init__.py `EXTRACTED`

### inherits
- [IndiaMktMixins](IndiaMktMixins.md) `EXTRACTED`
- BaseStrategy `EXTRACTED`
- DeltaMktMixins `EXTRACTED`
- [DosHtfMixin](DosHtfMixin.md) `EXTRACTED`
- [DosTrailSlMixin](DosTrailSlMixin.md) `EXTRACTED`

### method
- ._build_entry() `EXTRACTED`
- .on_candle() `EXTRACTED`
- ._rt() `EXTRACTED`
- ._resolve_underlying() `EXTRACTED`
- ._ensure_meta() `EXTRACTED`
- ._select_live_contract() `EXTRACTED`
- ._bind_symbol() `EXTRACTED`
- ._symbol_cfg() `EXTRACTED`
- ._rollover_intent_if_due() `EXTRACTED`
- ._open_main_positions() `EXTRACTED`
- .on_quote() `EXTRACTED`
- ._timestamp_ist() `EXTRACTED`
- .should_exit() `EXTRACTED`
- ._trail_open_sleeves() `EXTRACTED`
- ._maybe_switch_premium_sl_to_index() `EXTRACTED`
- ._closed_bar_time_ist() `EXTRACTED`
- ._begin_transition() `EXTRACTED`
- .on_position_exit() `EXTRACTED`
- .on_main_entry_filled() `EXTRACTED`
- ._sleeve_entries_enabled() `EXTRACTED`
- *…and 88 more `method` connection(s) not listed (lowest-degree first to go)*

### rationale_for
- Multi-sleeve SuperTrend option selling for BTCUSD / ETHUSD: - Weekly: when 1D… `EXTRACTED`

### references
- [Strategy index](Strategy_index.md) `INFERRED`

### uses
- [DirectionalOptionSellingTests](DirectionalOptionSellingTests.md) `INFERRED`
- [RunMode](RunMode.md) `INFERRED`
- IntentStatus `INFERRED`
- PendingTrailRetry `INFERRED`

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*