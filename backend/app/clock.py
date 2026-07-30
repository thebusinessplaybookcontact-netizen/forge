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
from datetime import date, datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import get_settings

log = logging.getLogger("coach")


@lru_cache
def zone() -> ZoneInfo:
    name = get_settings().timezone
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # A typo in config shouldn't take the app down, but it must not be silent —
        # the symptom (dates off by one, some of the day) is miserable to diagnose.
        log.error("Unknown COACH_TIMEZONE %r; falling back to UTC", name)
        return ZoneInfo("UTC")


def to_local(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes even from a timezone=True column."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(zone())


def now_local() -> datetime:
    return datetime.now(zone())


def today_local() -> date:
    return now_local().date()
