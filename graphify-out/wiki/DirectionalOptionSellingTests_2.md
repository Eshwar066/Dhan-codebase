# DirectionalOptionSellingTests

> God node · 73 connections · `core/strategies/crypto/DirectionalOptionSelling/tests/test_directional_option_selling.py`

**Community:** [DirectionalOptionSellingTests](DirectionalOptionSellingTests.md)

## Connections by Relation

### contains
- test_directional_option_selling.py `EXTRACTED`

### method
- .test_rollover_cancels_pending_main_sl_and_exits() `EXTRACTED`
- .test_should_exit_ignores_foreign_underlying_candle() `EXTRACTED`
- .test_live_selection_skips_strikes_inside_spot_gate() `EXTRACTED`
- .test_weekly_trail_does_not_fall_back_to_1h_st() `EXTRACTED`
- .test_trail_sl_modify_fail_keeps_meta_and_retries() `EXTRACTED`
- .test_premium_sl_switches_to_index_when_green_and_st_favorable() `EXTRACTED`
- .test_live_selection_weekly_deeper_otm_skips_nearest() `EXTRACTED`
- .test_morning_1725_flats_without_next_expiry_roll() `EXTRACTED`
- .test_dual_sleeve_weekly_and_daily_can_both_enter() `EXTRACTED`
- .test_monthly_trails_on_1d_supertrend() `EXTRACTED`
- .test_4h_bar_trails_weekly_and_may_enter_when_flat() `EXTRACTED`
- .test_reversal_exit_fill_enters_new_direction_immediately() `EXTRACTED`
- .test_reversal_exit_fill_defers_when_entry_build_fails() `EXTRACTED`
- .test_confirmed_st_flip_exits_on_closed_bar() `EXTRACTED`
- .test_weekly_force_exit_ignores_1h_supertrend() `EXTRACTED`
- .test_on_main_entry_filled_arms_premium_sl_2x() `EXTRACTED`
- .test_premium_sl_stays_when_still_red() `EXTRACTED`
- .test_sl_at_1101_reenters_on_1130_close_same_direction() `EXTRACTED`
- .test_external_close_arms_sl_reentry() `EXTRACTED`
- .test_flat_htf_aligned_does_not_enter_weekly_or_daily_on_1h() `EXTRACTED`
- *…and 50 more `method` connection(s) not listed (lowest-degree first to go)*

### uses
- [DirectionalOptionSelling](DirectionalOptionSelling.md) `INFERRED`
- IntentStatus `INFERRED`

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*