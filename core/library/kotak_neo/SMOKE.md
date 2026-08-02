# Kotak Neo dual-broker smoke checklist

Run **DHAN** and **KOTAK** as separate engine processes for ~3 months. Crypto stays on **DELTA**.

## Prerequisites

1. Install deps (Python 3.14 note: do **not** `pip install neo_api_client pyotp`
   together — Neo pins `numpy==2.1.0`, which has no 3.14 wheel and tries to
   compile from source. Neo is usually already installed; only add pyotp):
   ```bash
   pip install pyotp
   # only if missing:
   pip install neo_api_client --no-deps
   ```
   Keep your existing numpy (e.g. 2.4.x). Do not let pip downgrade/rebuild it.
2. NSE instrument master CSV present (same file Dhan uses):
   `Dependencies/all_instrumentYYYY-MM-DD.csv`
3. `.env` Kotak credentials:
   ```
   KOTAK_CONSUMER_KEY=...
   KOTAK_CONSUMER_SECRET=...
   KOTAK_MOBILE=...
   KOTAK_UCC=...
   KOTAK_MPIN=...
   KOTAK_TOTP_SECRET=...   # preferred; or KOTAK_TOTP=123456 for one shot
   KOTAK_ENVIRONMENT=prod  # or uat
   ```
4. Keep existing `DHAN_*` vars for engines still on Dhan.

## Unit tests

```bash
python -m unittest core.broker.internal.kotak.test_kotak_mappings -v
```

## Paper smoke (Kotak)

```bash
python -m run.main --engine-id kotak_nifty_intraday_magical_paper
```

Expect:
- Kotak TOTP + MPIN login succeeds
- Market WS subscribe for NIFTY
- Order-update feed starts
- Orders go to `SimulatedBroker` (PAPER) — no live Neo orders

## Live twin (optional)

Clone the smoke job in `run/config.py`, set `"run_mode": "LIVE"`, `"enabled": False`, then:

```bash
python -m run.main --engine-id <your_kotak_live_engine_id>
```

Place/cancel a tiny MIS order only after paper stability.

## Parallel Dhan

```bash
python -m run.main --venue DHAN
# other terminal:
python -m run.main --venue KOTAK
```

## After Neo is stable (~3 months)

1. Point India `ENGINE_JOBS` / strategy YAML `broker.venue` to `KOTAK`
2. Stop Dhan WS engines (avoid monthly API connect fee)
3. Leave Dhan code in-tree until hist/option CSV migration is decided
