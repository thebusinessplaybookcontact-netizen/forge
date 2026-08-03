"""What day it is, from Kyle's point of view.

An app organised around "today" has to mean *his* today. The server runs in UTC, so
after about 5pm Pacific it would otherwise think tomorrow has started: the prompt would
state the wrong date, "add this for today" would resolve a day late, and a task due
today would render as overdue all evening.

Timestamps are still stored in UTC — only the presentation is local. Converting on the
way out keeps the database unambiguous and means changing the timezone doesn't rewrite
history.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import get_settings

log = logging.getLogger("coach")


@lru_cache
def zone() -> tzinfo:
    """The configured zone, or UTC if it can't be had.

    Windows ships no timezone database — `ZoneInfo("America/Los_Angeles")` raises there
    unless the `tzdata` package is installed, which is why it's in requirements.txt. But
    the fallback must not depend on the same machinery it's catching for: returning
    `ZoneInfo("UTC")` here re-raises the identical error and takes down every request
    that touches a date. `timezone.utc` is built into Python and cannot fail.
    """
    name = get_settings().timezone
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # A typo in config, or a missing tz database, shouldn't take the app down — but
        # it must not be silent either: the symptom (dates off by one, for part of the
        # day) is miserable to diagnose from the outside.
        log.error(
            "Could not load COACH_TIMEZONE %r; falling back to UTC. On Windows this "
            "usually means the tzdata package is missing: pip install tzdata",
            name,
        )
        return timezone.utc


def to_local(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes even from a timezone=True column."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(zone())


def now_local() -> datetime:
    return datetime.now(zone())


def today_local() -> date:
    return now_local().date()
