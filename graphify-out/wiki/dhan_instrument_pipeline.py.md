# dhan_instrument_pipeline.py

> 13 nodes

## Key Concepts

- **dhan_instrument_pipeline.py** (11 connections) — `core/utils/dhan_instrument_pipeline.py`
- **sync_with_alert()** (7 connections) — `core/utils/dhan_instrument_pipeline.py`
- **diff_against_previous()** (6 connections) — `core/utils/dhan_instrument_pipeline.py`
- **Path** (5 connections)
- **download_scrip_master()** (4 connections) — `core/utils/dhan_instrument_pipeline.py`
- **prune_stale_instrument_csvs()** (4 connections) — `core/utils/dhan_instrument_pipeline.py`
- **file_sha256()** (3 connections) — `core/utils/dhan_instrument_pipeline.py`
- **Any** (2 connections)
- **Daily / on-demand Dhan instrument master sync (scrip master CSV). Source URL…** (1 connections) — `core/utils/dhan_instrument_pipeline.py`
- **Download to ``all_instrument{date}.csv``, diff vs previous day's file if…** (1 connections) — `core/utils/dhan_instrument_pipeline.py`
- **Download full scrip master to dest_csv (parent dirs created).** (1 connections) — `core/utils/dhan_instrument_pipeline.py`
- **Compare row count and content hash to previous file. Returns dict with…** (1 connections) — `core/utils/dhan_instrument_pipeline.py`
- **Delete ``all_instrument*.csv`` files in ``deps_dir`` except ``keep``. Returns…** (1 connections) — `core/utils/dhan_instrument_pipeline.py`

## Relationships

- [typing](typing.md) (2 shared connections)
- [delta_rest_client.py](delta_rest_client.py.md) (1 shared connections)
- [logging.py](logging.py.md) (1 shared connections)
- [RunMode](RunMode.md) (1 shared connections)

## Source Files

- `core/utils/dhan_instrument_pipeline.py`

## Audit Trail

- EXTRACTED: 26 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*