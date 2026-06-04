# Bank Nifty BTST

## Rules (Indian market)

1. **9:20 IST** — find Bank Nifty CE and PE strikes near **~100 premium**; place **LIMIT BUY** on both legs at **premium × 1.5** (e.g. premium 100 → limit 150).
2. **After fill** — arm **SL-M SELL** at **50% of limit price** (e.g. limit 150 → SL 75).
3. **If SL not hit** — exit next session at **9:25 IST** (BTST square-off).

## Run

```powershell
python -m run.main --engine-id dhan_banknifty_btst
```

## Wiring

| Item | Location |
|------|----------|
| Strategy | `core/strategies/BTST/BankNiftyBTST/BankNiftyBTST.py` |
| Registry | `STRATEGY_MAP["BankNiftyBTST"]` |
| Runtime spec | 5m option chain (backtest/paper), live 1m |
| Engine job | `run/config.py` → `dhan_banknifty_btst` |
| Symbol | `BANKNIFTY` |
| Dhan securityId | `25` (via `dhan_option_security_id` on strategy class) |

## Backtest data

Uses DHAN expired option CSVs or rolling-option API (same as LEAPS / NIML). Prefer local **5m** bars under `DHAN_EXPIRED_OPTION_CHAIN_ROOT` for Bank Nifty monthly series.
