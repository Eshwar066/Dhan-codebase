"""
Offline / cron fetcher for high-impact USD macro schedule.

Best-effort scrape of free government pages. Failures leave the previous
JSON cache untouched. Never called on the live trade path.
"""

from __future__ import annotations

import logging
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape
from typing import List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from core.utils.calendar.economic_events import (
    EconomicEvent,
    merge_events,
    write_events_json,
)

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_RELEASE_CALENDAR_URL = "https://www.bls.gov/schedule/news_release/"
BEA_RELEASE_CALENDAR_URL = "https://www.bea.gov/news/schedule"

# FOMC statement 14:00 ET; press conference typically 14:30 ET (Fed PR).
FOMC_STATEMENT_HOUR_ET = 14
FOMC_STATEMENT_MINUTE_ET = 0
FOMC_PRESS_HOUR_ET = 14
FOMC_PRESS_MINUTE_ET = 30

# Common US data-print times (ET).
US_DATA_DEFAULT_ET = (8, 30)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _et_to_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    local = datetime(year, month, day, hour, minute, tzinfo=ET)
    return local.astimezone(timezone.utc)


def _fetch_text(url: str, *, timeout: float = 30.0) -> Optional[str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            charset = "utf-8"
            ctype = resp.headers.get_content_charset()
            if ctype:
                charset = ctype
            return raw.decode(charset, errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Calendar fetch failed for %s: %s", url, exc)
        return None


def classify_event_title(title: str) -> Optional[Tuple[str, str]]:
    """
    Map free-text title -> (event_key, display_name) for HIGH USD events we care about.
    Returns None for unknown / non-target titles.
    """
    t = " ".join(unescape(title or "").upper().split())
    if not t:
        return None

    # Prefer more specific matches first.
    if "FOMC" in t and ("PRESS" in t or "NEWS CONFERENCE" in t or "CONFERENCE" in t):
        return "FOMC", "FOMC Press Conference"
    if "FOMC" in t and (
        "STATEMENT" in t
        or "RATE" in t
        or "DECISION" in t
        or "MEETING" in t
        or "ISSUES FOMC" in t
    ):
        return "FOMC", "FOMC Rate Decision"
    if re.search(r"\bFOMC\b", t) and "MINUTES" not in t:
        return "FOMC", "FOMC Rate Decision"

    if "CORE CPI" in t or ("CPI" in t and "CORE" in t):
        return "CPI", "US Core CPI"
    if re.search(r"\bCPI\b", t) or "CONSUMER PRICE INDEX" in t:
        return "CPI", "US CPI"

    if (
        "NONFARM" in t
        or "NON-FARM" in t
        or "EMPLOYMENT SITUATION" in t
        or re.search(r"\bNFP\b", t)
    ):
        return "NFP", "US NFP"

    if "CORE PCE" in t or ("PCE" in t and "CORE" in t):
        return "PCE", "US Core PCE"
    if re.search(r"\bPCE\b", t) or "PERSONAL CONSUMPTION" in t:
        return "PCE", "US PCE"

    if re.search(r"\bGDP\b", t) or "GROSS DOMESTIC PRODUCT" in t:
        return "GDP", "US GDP"

    speech_markers = (
        "SPEECH",
        "REMARKS",
        "TESTIMONY",
        "SEMIANNUAL",
        "HUMPHREY",
        "CHAIR POWELL",
        "CHAIRMAN POWELL",
        "JEROME POWELL",
    )
    if any(m in t for m in speech_markers) and (
        "FED" in t or "POWELL" in t or "FOMC" in t or "RESERVE" in t
    ):
        return "FED_SPEECH", title.strip() or "Fed Speech"

    return None


def _strip_tags(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return unescape(re.sub(r"\s+", " ", text))


def parse_fomc_calendar_html(html: str, *, years: Optional[Sequence[int]] = None) -> List[EconomicEvent]:
    """
    Parse FOMC meeting calendar page.

    Meeting blocks look like ``January 27-28`` under a ``#### 2026 FOMC Meetings`` heading.
    Statement / press times use Fed convention (14:00 / 14:30 ET on the second day).
    """
    text = _strip_tags(html)
    target_years = set(years) if years else None
    events: List[EconomicEvent] = []

    # Split by year headings.
    year_chunks = re.split(r"(\d{4})\s+FOMC\s+Meetings", text, flags=re.IGNORECASE)
    # year_chunks: [preamble, year1, body1, year2, body2, ...]
    i = 1
    while i + 1 < len(year_chunks):
        year_s, body = year_chunks[i], year_chunks[i + 1]
        i += 2
        try:
            year = int(year_s)
        except ValueError:
            continue
        if target_years is not None and year not in target_years:
            continue
        # e.g. "January 27-28" or "March 17-18*"
        for m in re.finditer(
            r"(January|February|March|April|May|June|July|August|September|"
            r"October|November|December)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\*?",
            body,
            flags=re.IGNORECASE,
        ):
            month = _MONTHS[m.group(1).lower()]
            day2 = int(m.group(3))
            try:
                statement_utc = _et_to_utc(
                    year, month, day2, FOMC_STATEMENT_HOUR_ET, FOMC_STATEMENT_MINUTE_ET
                )
                press_utc = _et_to_utc(
                    year, month, day2, FOMC_PRESS_HOUR_ET, FOMC_PRESS_MINUTE_ET
                )
            except ValueError:
                continue
            events.append(
                EconomicEvent(
                    event="FOMC Rate Decision",
                    time=statement_utc,
                    impact="HIGH",
                    currency="USD",
                    source="fed",
                    event_key="FOMC",
                )
            )
            events.append(
                EconomicEvent(
                    event="FOMC Press Conference",
                    time=press_utc,
                    impact="HIGH",
                    currency="USD",
                    source="fed",
                    event_key="FOMC",
                )
            )
    return events


def _parse_schedule_rows(
    html: str,
    *,
    source: str,
    default_hour_et: int = 8,
    default_minute_et: int = 30,
) -> List[EconomicEvent]:
    """
    Best-effort parse of BLS-style schedule HTML.

    Looks for titles near ``Month Day, Year`` (optional time).
    """
    text = _strip_tags(html)
    events: List[EconomicEvent] = []
    date_pat = (
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),?\s+(\d{4})"
        r"(?:\s+(\d{1,2}):(\d{2})\s*(AM|PM))?"
    )
    for m in re.finditer(date_pat, text, flags=re.IGNORECASE):
        start = max(0, m.start() - 120)
        window = text[start : m.end()]
        classified = classify_event_title(window)
        if classified is None:
            continue
        event_key, display = classified
        month = _MONTHS[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3))
        hour, minute = default_hour_et, default_minute_et
        if m.group(4) and m.group(5) and m.group(6):
            hour = int(m.group(4))
            minute = int(m.group(5))
            ampm = m.group(6).upper()
            if ampm == "PM" and hour != 12:
                hour += 12
            if ampm == "AM" and hour == 12:
                hour = 0
        try:
            when = _et_to_utc(year, month, day, hour, minute)
        except ValueError:
            continue
        events.append(
            EconomicEvent(
                event=display,
                time=when,
                impact="HIGH",
                currency="USD",
                source=source,
                event_key=event_key,
            )
        )
    return events


def parse_bea_schedule_html(html: str) -> List[EconomicEvent]:
    """
    Parse BEA news schedule.

    Rows look like::
        July 30 8:30 AM News GDP (Advance Estimate), 2nd Quarter 2026
        July 31 8:30 AM News Personal Income and Outlays, June 2026
    """
    text = _strip_tags(html)
    events: List[EconomicEvent] = []
    row_pat = re.compile(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2})\s+(\d{1,2}):(\d{2})\s*(AM|PM)\s+"
        r"(.{0,160}?)(?="
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2}\s+\d{1,2}:\d{2}\s*(?:AM|PM)|"
        r"To Be Announced|$)",
        flags=re.IGNORECASE,
    )
    year_hint = datetime.now(timezone.utc).year
    # Prefer an explicit "Year 20XX" marker near the start of the schedule block.
    ym = re.search(r"Clear Year\s+(\d{4})", text, flags=re.IGNORECASE)
    if ym:
        year_hint = int(ym.group(1))
    ym2 = re.search(r"\bYear\s+(\d{4})\s+Release", text, flags=re.IGNORECASE)
    if ym2:
        year_hint = int(ym2.group(1))

    for m in row_pat.finditer(text):
        title = " ".join(m.group(6).split())
        title_u = title.upper()
        # Skip regional / non-headline prints.
        if any(
            bad in title_u
            for bad in (
                "STATE GDP",
                "GDP BY COUNTY",
                "BY STATE",
                "STATE PCE",
                "STATE PERSONAL",
                "INTERNATIONAL TRADE",
                "MULTINATIONAL",
                "OUTDOOR RECREATION",
                "SERVICES SUPPLIED",
            )
        ):
            continue

        event_key: Optional[str] = None
        display: Optional[str] = None
        if re.search(r"\bGDP\b", title_u) and "PERSONAL INCOME AND OUTLAYS" not in title_u:
            event_key, display = "GDP", "US GDP"
        elif "PERSONAL INCOME AND OUTLAYS" in title_u:
            # Monthly PCE / core PCE print.
            event_key, display = "PCE", "US PCE"
        else:
            classified = classify_event_title(title)
            if classified is None:
                continue
            event_key, display = classified
            if event_key not in {"GDP", "PCE"}:
                continue

        month = _MONTHS[m.group(1).lower()]
        day = int(m.group(2))
        hour = int(m.group(3))
        minute = int(m.group(4))
        ampm = m.group(5).upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        if ampm == "AM" and hour == 12:
            hour = 0
        # Title often ends with ", 2nd Quarter 2026" or ", June 2026" — prefer that year.
        year = year_hint
        y_in_title = re.search(r"\b(20\d{2})\b", title)
        if y_in_title:
            year = int(y_in_title.group(1))
        try:
            when = _et_to_utc(year, month, day, hour, minute)
        except ValueError:
            continue
        events.append(
            EconomicEvent(
                event=display,
                time=when,
                impact="HIGH",
                currency="USD",
                source="bea",
                event_key=event_key,
            )
        )
    return events


def fetch_fomc_events() -> List[EconomicEvent]:
    html = _fetch_text(FOMC_CALENDAR_URL)
    if not html:
        return []
    now_year = datetime.now(timezone.utc).year
    return parse_fomc_calendar_html(html, years=(now_year, now_year + 1))


def fetch_bls_events() -> List[EconomicEvent]:
    # BLS often returns 403 to datacenter IPs; best-effort with a few URLs.
    urls = (
        BLS_RELEASE_CALENDAR_URL,
        "https://www.bls.gov/schedule/2026/home.htm",
        "https://www.bls.gov/schedule/news_release/cpi.htm",
        "https://www.bls.gov/schedule/news_release/empsit.htm",
    )
    events: List[EconomicEvent] = []
    for url in urls:
        html = _fetch_text(url)
        if not html:
            continue
        events.extend(
            e
            for e in _parse_schedule_rows(html, source="bls")
            if e.event_key in {"CPI", "NFP"}
        )
        if events:
            break
    return events


def fetch_bea_events() -> List[EconomicEvent]:
    html = _fetch_text(BEA_RELEASE_CALENDAR_URL)
    if not html:
        return []
    return parse_bea_schedule_html(html)


def collect_economic_events(
    *,
    include_fomc: bool = True,
    include_bls: bool = True,
    include_bea: bool = True,
) -> List[EconomicEvent]:
    collected: List[EconomicEvent] = []
    if include_fomc:
        collected.extend(fetch_fomc_events())
    if include_bls:
        collected.extend(fetch_bls_events())
    if include_bea:
        collected.extend(fetch_bea_events())
    # Drop non-HIGH / non-USD / unknown keys (defensive).
    filtered = [
        e
        for e in collected
        if e.impact.upper() == "HIGH"
        and e.currency.upper() == "USD"
        and (e.event_key is None or e.event_key in {"FOMC", "CPI", "NFP", "PCE", "GDP", "FED_SPEECH"})
    ]
    return merge_events(filtered, [])


def refresh_economic_calendar_cache(
    output_path: str,
    *,
    dry_run: bool = False,
) -> Tuple[bool, int, Optional[str]]:
    """
    Fetch and write atomic JSON cache.

    Returns (ok, event_count, error_message). On parse/fetch failure with zero
    events, does not overwrite existing cache.
    """
    try:
        events = collect_economic_events()
    except Exception as exc:
        logger.exception("Economic calendar refresh crashed: %s", exc)
        return False, 0, str(exc)

    if not events:
        msg = "No events parsed from free sources; leaving existing cache unchanged"
        logger.warning(msg)
        return False, 0, msg

    if dry_run:
        logger.info("Dry-run: would write %d events to %s", len(events), output_path)
        return True, len(events), None

    try:
        write_events_json(output_path, events)
    except OSError as exc:
        logger.error("Failed to write calendar cache %s: %s", output_path, exc)
        return False, 0, str(exc)

    logger.info("Wrote %d economic events to %s", len(events), output_path)
    return True, len(events), None
