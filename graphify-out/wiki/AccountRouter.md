# AccountRouter

> 18 nodes

## Key Concepts

- **AccountRouter** (14 connections) — `core/orderExecution/account_router.py`
- **Scale plan: many strategies + many accounts** (8 connections) — `docs/SCALE_MULTI_ACCOUNT.md`
- **.__init__()** (4 connections) — `core/orderExecution/account_router.py`
- **_dedupe_keep_order()** (4 connections) — `core/orderExecution/account_router.py`
- **.route()** (3 connections) — `core/orderExecution/account_router.py`
- **Target topology (recommended)** (3 connections) — `docs/SCALE_MULTI_ACCOUNT.md`
- **AccountRoutingConfig** (2 connections) — `core/orderExecution/account_router.py`
- **.all_accounts()** (2 connections) — `core/orderExecution/account_router.py`
- **Any** (2 connections)
- **Bottom line** (2 connections) — `docs/SCALE_MULTI_ACCOUNT.md`
- **Priority change list** (2 connections) — `docs/SCALE_MULTI_ACCOUNT.md`
- **Product model (pick one)** (2 connections) — `docs/SCALE_MULTI_ACCOUNT.md`
- **What you have today** (2 connections) — `docs/SCALE_MULTI_ACCOUNT.md`
- **SCALE_MULTI_ACCOUNT.md** (1 connections) — `docs/SCALE_MULTI_ACCOUNT.md`
- **Rough packing** (1 connections) — `docs/SCALE_MULTI_ACCOUNT.md`
- **Rules of thumb** (1 connections) — `docs/SCALE_MULTI_ACCOUNT.md`
- **What not to do** (1 connections) — `docs/SCALE_MULTI_ACCOUNT.md`
- **Deterministic, side-effect-free mapping from intent -> account ids.** (1 connections) — `core/orderExecution/account_router.py`

## Relationships

- [factory.py](factory.py.md) (5 shared connections)
- [.create_live_engine](create_live_engine.md) (2 shared connections)
- [Any](Any.md) (1 shared connections)
- [LiveEngine](LiveEngine.md) (1 shared connections)
- [EngineConfig](EngineConfig.md) (1 shared connections)
- [Phased plan](Phased_plan.md) (1 shared connections)

## Source Files

- `core/orderExecution/account_router.py`
- `docs/SCALE_MULTI_ACCOUNT.md`

## Audit Trail

- EXTRACTED: 27 (82%)
- INFERRED: 6 (18%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*