# TestGttBrokerPositionAdopt

> 9 nodes

## Key Concepts

- **TestGttBrokerPositionAdopt** (14 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **.test_position_detected_adopts_fill_not_just_skip_limit()** (5 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **.test_rebind_attaches_metadata_without_shadow_sl_hook()** (5 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **._intent_rec()** (4 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **.test_restore_from_disk_rebuilds_intent_stub()** (4 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **.test_alnum_match_adopts_dhan_place_order_symbol()** (3 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **.test_cutoff_cancel_adopts_before_cancelling_gtt()** (2 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **_apply()** (1 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`
- **Regression 2026-07-24: rebind+ensure both armed MAIN_SL → duplicates.** (1 connections) — `core/orderExecution/test_gtt_broker_position_adopt.py`

## Relationships

- [GttFallbackBook](GttFallbackBook.md) (4 shared connections)
- [GttFallbackWatch](GttFallbackWatch.md) (4 shared connections)
- [RunMode](RunMode.md) (3 shared connections)
- [IntentStore](IntentStore.md) (3 shared connections)
- [BidAskLtp](BidAskLtp.md) (2 shared connections)
- [OrderRouter](OrderRouter.md) (1 shared connections)

## Source Files

- `core/orderExecution/test_gtt_broker_position_adopt.py`

## Audit Trail

- EXTRACTED: 20 (71%)
- INFERRED: 8 (29%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*