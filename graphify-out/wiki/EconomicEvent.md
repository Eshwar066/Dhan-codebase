# EconomicEvent

> 34 nodes

## Key Concepts

- **EconomicEvent** (30 connections) — `core/utils/calendar/economic_events.py`
- **fetch_economic_calendar.py** (28 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **parse_bea_schedule_html()** (9 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **parse_fomc_calendar_html()** (8 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **refresh_economic_calendar.py** (8 connections) — `utils/delta/refresh_economic_calendar.py`
- **collect_economic_events()** (7 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **_parse_schedule_rows()** (7 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **write_events_json()** (6 connections) — `core/utils/calendar/economic_events.py`
- **classify_event_title()** (6 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **refresh_economic_calendar_cache()** (6 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **_et_to_utc()** (5 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **fetch_bea_events()** (5 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **fetch_bls_events()** (5 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **fetch_fomc_events()** (5 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **TestFetcherHelpers** (4 connections) — `core/utils/calendar/test_economic_events.py`
- **_fetch_text()** (4 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **_strip_tags()** (4 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **.test_classify_titles()** (2 connections) — `core/utils/calendar/test_economic_events.py`
- **.test_parse_bea_html_fixture()** (2 connections) — `core/utils/calendar/test_economic_events.py`
- **.test_parse_fomc_html_fixture()** (2 connections) — `core/utils/calendar/test_economic_events.py`
- **main()** (2 connections) — `utils/delta/refresh_economic_calendar.py`
- **datetime** (2 connections)
- **Atomic JSON write used by the offline fetcher.** (1 connections) — `core/utils/calendar/economic_events.py`
- **Offline / cron fetcher for high-impact USD macro schedule. Best-effort scrape…** (1 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- **Map free-text title -> (event_key, display_name) for HIGH USD events we care…** (1 connections) — `core/utils/calendar/fetch_economic_calendar.py`
- *... and 9 more nodes in this community*

## Relationships

- [test_economic_events.py](test_economic_events.py.md) (11 shared connections)
- [economic_events.py](economic_events.py.md) (9 shared connections)
- [EventCalendarService](EventCalendarService.md) (7 shared connections)
- [EventBlackoutGuard](EventBlackoutGuard.md) (4 shared connections)
- [logging.py](logging.py.md) (3 shared connections)
- [RunMode](RunMode.md) (2 shared connections)
- [historical_cache.py](historical_cache.py.md) (1 shared connections)
- [typing](typing.md) (1 shared connections)
- [indicator_history_path](indicator_history_path.md) (1 shared connections)

## Source Files

- `core/utils/calendar/economic_events.py`
- `core/utils/calendar/fetch_economic_calendar.py`
- `core/utils/calendar/test_economic_events.py`
- `utils/delta/refresh_economic_calendar.py`

## Audit Trail

- EXTRACTED: 100 (96%)
- INFERRED: 4 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*