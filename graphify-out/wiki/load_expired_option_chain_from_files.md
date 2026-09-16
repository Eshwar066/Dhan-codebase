# load_expired_option_chain_from_files

> 23 nodes

## Key Concepts

- **load_expired_option_chain_from_files()** (15 connections) — `core/utils/dhan_expired_option_chain_files.py`
- **.get_expired_optionchain()** (10 connections) — `core/data/sources/dhan_source.py`
- **leg_csv_path()** (7 connections) — `core/utils/dhan_expired_option_chain_files.py`
- **strikes_to_atm_folder_labels()** (7 connections) — `core/utils/dhan_expired_option_chain_files.py`
- **default_expired_option_chain_root()** (6 connections) — `core/utils/dhan_expired_option_chain_files.py`
- **resolve_atm_wise_root()** (5 connections) — `core/utils/dhan_expired_option_chain_files.py`
- **Path** (5 connections)
- **._dhan_fetch_plan()** (4 connections) — `core/data/sources/dhan_source.py`
- **_normalize_expiry_str()** (4 connections) — `core/utils/dhan_expired_option_chain_files.py`
- **read_leg_csv()** (4 connections) — `core/utils/dhan_expired_option_chain_files.py`
- **datetime** (4 connections)
- **._coerce_expired_option_side_df()** (3 connections) — `core/data/sources/dhan_source.py`
- **date** (3 connections)
- **_option_right_filename()** (2 connections) — `core/utils/dhan_expired_option_chain_files.py`
- **Any** (2 connections)
- **DataFrame** (2 connections)
- **Map requested bar size to a Dhan-native fetch interval. Returns…** (1 connections) — `core/data/sources/dhan_source.py`
- **Pick CALL/CE or PUT/PE frame from DHAN rolling-option API payload.** (1 connections) — `core/data/sources/dhan_source.py`
- **Backtest option OHLC: prefer CSVs under ``DHAN_EXPIRED_OPTION_CHAIN_ROOT`` (or…** (1 connections) — `core/data/sources/dhan_source.py`
- **Map numeric strikes (or precomputed ``ATM`` / ``ATM±n`` folder names) to folder…** (1 connections) — `core/utils/dhan_expired_option_chain_files.py`
- **Load and concatenate one leg (CALL or PUT) across multiple strike folders. Rows…** (1 connections) — `core/utils/dhan_expired_option_chain_files.py`
- **If ``DHAN_EXPIRED_OPTION_CHAIN_ROOT`` is unset, look under…** (1 connections) — `core/utils/dhan_expired_option_chain_files.py`
- **Return directory that contains ``ATM Wise data``, or None.** (1 connections) — `core/utils/dhan_expired_option_chain_files.py`

## Relationships

- [typing](typing.md) (11 shared connections)
- [DhanSource](DhanSource.md) (3 shared connections)
- [logging.py](logging.py.md) (3 shared connections)
- [historical_cache.py](historical_cache.py.md) (2 shared connections)
- [.as_calendar_date](as_calendar_date.md) (2 shared connections)
- [IndiaMktMixins](IndiaMktMixins.md) (1 shared connections)

## Source Files

- `core/data/sources/dhan_source.py`
- `core/utils/dhan_expired_option_chain_files.py`

## Audit Trail

- EXTRACTED: 56 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*