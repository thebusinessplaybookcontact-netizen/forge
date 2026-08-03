"""Whose "today" the app means.

The bug these pin: the server runs in UTC, so from late afternoon Pacific onward it
believed tomorrow had started. The prompt stated the wrong date, "add this for today"
resolved a day late, and a task due today read as overdue all evening.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import clock  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.memory import build_system_blocks  # noqa: E402
from app.models import Goal, Horizon, Summary, CheckInSession  # noqa: E402


@pytest.fixture()
def tz():
    """Set the configured timezone, clearing the cache either side."""
    saved = get_settings().timezone

    def _set(name: str):
        get_settings().timezone = name
        clock.zone.cache_clear()

    yield _set
    get_settings().timezone = saved
    clock.zone.cache_clear()


def test_defaults_to_utc(tz):
    tz("UTC")
    assert clock.zone().key == "UTC"


def test_survives_a_machine_with_no_timezone_database(tz, monkeypatch):
    """Windows ships no tz database, and the fallback used to need one too.

    `ZoneInfo("America/Los_Angeles")` raises there without the tzdata package. That was
    caught — and the handler then called `ZoneInfo("UTC")`, which raises identically and
    wasn't. Every request that touched a date became a 500, which on the dashboard is
    every request there is. A fallback that depends on the machinery it's catching for
    is not a fallback.
    """

    def no_database(*_args, **_kwargs):
        raise ZoneInfoNotFoundError("No time zone found")

    monkeypatch.setattr(clock, "ZoneInfo", no_database)
    tz("America/Los_Angeles")

    assert clock.zone().utcoffset(None) == timedelta(0), "should be UTC, not an exception"
    assert isinstance(clock.today_local(), date)
    assert clock.to_local(datetime(2026, 7, 30, 12, 0)).tzinfo is not None

    # And the thing that actually broke: the dashboard's own dependencies.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.add(Goal(text="Fitness", horizon=Horizon.lifetime))
        db.commit()
        assert "## Habits" in build_system_blocks(db)[1]["text"]
    Base.metadata.drop_all(bind=engine)


def test_uses_the_configured_zone(tz):
    tz("America/Los_Angeles")
    assert clock.zone().key == "America/Los_Angeles"


def test_evening_in_california_is_still_the_same_day(tz):
    """The exact case that was broken: 8pm Pacific is already tomorrow in UTC."""
    tz("America/Los_Angeles")
    utc_moment = datetime(2026, 7, 31, 3, 0, tzinfo=timezone.utc)  # 8pm PDT on the 30th

    assert utc_moment.date() == date(2026, 7, 31), "UTC has already rolled over"
    assert clock.to_local(utc_moment).date() == date(2026, 7, 30), "but it's still the 30th here"


def test_naive_timestamps_are_treated_as_utc(tz):
    """SQLite returns naive datetimes even from a timezone=True column."""
    tz("America/New_York")
    naive = datetime(2026, 7, 31, 3, 0)  # no tzinfo, as SQLite hands it back
    assert clock.to_local(naive).date() == date(2026, 7, 30)


def test_a_bad_timezone_falls_back_instead_of_crashing(tz):
    tz("Mars/Olympus_Mons")
    # Deliberately checks the offset rather than .key: the fallback is datetime's own
    # timezone.utc, precisely so it can't depend on the tz database being present.
    assert clock.zone().utcoffset(None) == timedelta(0)


def test_today_matches_the_configured_zone(tz):
    tz("Pacific/Kiritimati")  # UTC+14, so it is reliably a different date from UTC
    now_utc = datetime.now(timezone.utc)
    expected = now_utc.astimezone(ZoneInfo("Pacific/Kiritimati")).date()
    assert clock.today_local() == expected


# --- what the model actually sees ---


def test_prompt_states_the_local_date(tz):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    tz("Pacific/Kiritimati")

    with SessionLocal() as db:
        db.add(Goal(text="Fitness", horizon=Horizon.lifetime))
        db.commit()
        state = build_system_blocks(db)[1]["text"]

    expected = datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
    assert f"Today is {expected:%A}, {expected.isoformat()}" in state, (
        "the coach must resolve 'today' — day and date — the way Kyle would"
    )
    Base.metadata.drop_all(bind=engine)


def test_recap_dates_render_locally(tz):
    """A session from last night shouldn't be dated tomorrow."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    tz("America/Los_Angeles")

    with SessionLocal() as db:
        session = CheckInSession()
        db.add(session)
        db.commit()
        db.add(
            Summary(
                session_id=session.id,
                recap="Skipped the gym.",
                commitments="",
                created_at=datetime(2026, 7, 31, 3, 0, tzinfo=timezone.utc),  # 8pm PDT, 30th
            )
        )
        db.commit()
        state = build_system_blocks(db)[1]["text"]

    assert "### 2026-07-30" in state
    assert "### 2026-07-31" not in state
    Base.metadata.drop_all(bind=engine)
