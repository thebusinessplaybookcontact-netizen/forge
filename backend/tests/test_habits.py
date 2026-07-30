"""Habits: cadence, streaks, and consistency.

The measurement rules being pinned here are deliberate choices, not incidental
behaviour — see the module docstring in app/habits.py. In particular: an unfinished
day or week is never a failure, and a flexible cadence must not break because of the
wrong weekday.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crud, habits, tools  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Cadence, Goal, Habit, HabitEntry, Horizon  # noqa: E402

MONDAY = date(2026, 7, 27)  # anchor; 2026-07-27 is a Monday
TUE, WED, THU, FRI, SAT, SUN = (MONDAY + timedelta(days=i) for i in range(1, 7))


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def make_habit(cadence=Cadence.daily, target=7, created=None) -> int:
    with SessionLocal() as db:
        habit = Habit(text="Train", cadence=cadence, target_per_week=target)
        if created:
            from datetime import datetime, timezone

            habit.created_at = datetime.combine(created, datetime.min.time(), tzinfo=timezone.utc)
        db.add(habit)
        db.commit()
        return habit.id


def log_days(habit_id: int, days: list[date]) -> None:
    with SessionLocal() as db:
        for d in days:
            db.add(HabitEntry(habit_id=habit_id, done_on=d))
        db.commit()


def stats(habit_id: int, today: date):
    with SessionLocal() as db:
        return habits.stats_for(db, habits.get_habit(db, habit_id), today=today)


# --- daily streaks ---


def test_consecutive_days_build_a_streak():
    h = make_habit(created=MONDAY)
    log_days(h, [MONDAY, TUE, WED])
    assert stats(h, WED).current_streak == 3


def test_not_done_yet_today_does_not_break_the_streak():
    """The day isn't over. This is the single most important rule here."""
    h = make_habit(created=MONDAY)
    log_days(h, [MONDAY, TUE, WED])
    s = stats(h, THU)  # nothing logged for Thursday yet
    assert s.current_streak == 3
    assert s.done_today is False


def test_a_missed_day_does_break_it():
    h = make_habit(created=MONDAY)
    log_days(h, [MONDAY, TUE, THU])  # Wednesday missed
    assert stats(h, THU).current_streak == 1


def test_longest_streak_is_remembered_after_a_break():
    h = make_habit(created=MONDAY)
    log_days(h, [MONDAY, TUE, WED, FRI])  # 3 then a gap then 1
    s = stats(h, FRI)
    assert s.current_streak == 1
    assert s.longest_streak == 3, "the best run should survive a reset"


def test_no_history_is_zero_not_an_error():
    h = make_habit()
    s = stats(h, WED)
    assert (s.current_streak, s.longest_streak) == (0, 0)


# --- weekly cadence: the flexible case ---


def test_weekly_target_does_not_care_which_days():
    h = make_habit(Cadence.weekly, target=3, created=MONDAY)
    log_days(h, [MONDAY, WED, SAT])
    s = stats(h, SUN)
    assert s.this_week == 3
    assert s.current_streak == 1, "hitting 3 of 3 is a completed week"


def test_a_skipped_weekday_does_not_break_a_weekly_habit():
    """3x/week must not read as failure just because Tuesday was skipped."""
    h = make_habit(Cadence.weekly, target=3, created=MONDAY - timedelta(days=7))
    prev = [MONDAY - timedelta(days=7), MONDAY - timedelta(days=5), MONDAY - timedelta(days=3)]
    log_days(h, prev + [MONDAY, WED, FRI])
    assert stats(h, FRI).current_streak == 2, "two consecutive weeks at target"


def test_an_unfinished_week_is_not_a_break():
    """Mid-week, below target, with last week complete — the streak stands."""
    h = make_habit(Cadence.weekly, target=3, created=MONDAY - timedelta(days=7))
    last_week = [MONDAY - timedelta(days=7), MONDAY - timedelta(days=5), MONDAY - timedelta(days=3)]
    log_days(h, last_week + [MONDAY])  # only 1 of 3 so far this week

    s = stats(h, TUE)
    assert s.this_week == 1
    assert s.current_streak == 1, "last week still counts; this week is merely unfinished"


def test_a_missed_week_breaks_the_streak():
    h = make_habit(Cadence.weekly, target=3, created=MONDAY - timedelta(days=14))
    two_ago = MONDAY - timedelta(days=14)
    log_days(h, [two_ago, two_ago + timedelta(days=2), two_ago + timedelta(days=4)])
    # last week: nothing. this week: at target.
    log_days(h, [MONDAY, WED, FRI])
    assert stats(h, FRI).current_streak == 1


def test_daily_cadence_forces_a_target_of_seven():
    with SessionLocal() as db:
        habit = habits.create_habit(db, text="Read", cadence="daily", target_per_week=3)
    assert habit.target_per_week == 7


# --- consistency ---


def test_consistency_is_measured_from_when_the_habit_started():
    """A habit created three days ago shouldn't show 10% because the window is 30 days."""
    h = make_habit(created=MONDAY)
    log_days(h, [MONDAY, TUE, WED])
    assert stats(h, WED).completion_rate_30d == 1.0


def test_consistency_survives_a_broken_streak():
    """The number that stops a reset reading as total failure."""
    h = make_habit(created=MONDAY)
    log_days(h, [MONDAY, TUE, WED, THU, SAT])  # missed Friday
    s = stats(h, SAT)
    assert s.current_streak == 1
    assert s.completion_rate_30d > 0.8, "still going well despite the reset"


def test_weekly_consistency_is_scaled_to_target():
    """3 of 3 in a week is 100%, not 43%."""
    h = make_habit(Cadence.weekly, target=3, created=MONDAY)
    log_days(h, [MONDAY, WED, FRI])
    assert stats(h, SUN).completion_rate_30d == pytest.approx(1.0, abs=0.15)


# --- logging ---


def test_logging_twice_is_idempotent():
    h = make_habit(created=MONDAY)
    with SessionLocal() as db:
        habits.log(db, h, MONDAY)
        habits.log(db, h, MONDAY)
        assert db.query(HabitEntry).count() == 1


def test_unlog_removes_the_day():
    h = make_habit(created=MONDAY)
    with SessionLocal() as db:
        habits.log(db, h, MONDAY)
        habits.unlog(db, h, MONDAY)
        assert db.query(HabitEntry).count() == 0


def test_unlogging_a_day_that_was_never_logged_is_harmless():
    h = make_habit(created=MONDAY)
    with SessionLocal() as db:
        habits.unlog(db, h, MONDAY)  # no exception


def test_deleted_habits_disappear_but_can_be_restored():
    h = make_habit()
    with SessionLocal() as db:
        _, undo = habits.delete_habit(db, h)
        undo_id = undo.id
    with SessionLocal() as db:
        assert habits.list_habits(db) == []
        with pytest.raises(crud.NotFound):
            habits.get_habit(db, h)
    with SessionLocal() as db:
        crud.apply_undo(db, undo_id)
        assert len(habits.list_habits(db)) == 1


# --- through the coach ---


def test_coach_can_create_and_log_a_habit():
    with SessionLocal() as db:
        outcome = tools.execute(
            db, "add_habit", {"text": "Train", "cadence": "weekly", "target_per_week": 3}
        )
        assert outcome.ok, outcome.message
        habit_id = outcome.entity["id"]

    with SessionLocal() as db:
        logged = tools.execute(db, "log_habit", {"habit_id": habit_id})
        assert logged.ok
        assert "1 of 3 this week" in logged.message

    with SessionLocal() as db:
        assert db.query(HabitEntry).count() == 1


def test_coach_can_log_a_past_day():
    with SessionLocal() as db:
        habit = habits.create_habit(db, text="Train", cadence="daily")
        outcome = tools.execute(db, "log_habit", {"habit_id": habit.id, "on": "2026-07-27"})
        assert outcome.ok
    with SessionLocal() as db:
        assert db.query(HabitEntry).one().done_on == MONDAY


def test_logging_an_unknown_habit_is_a_clean_error():
    with SessionLocal() as db:
        outcome = tools.execute(db, "log_habit", {"habit_id": 999})
    assert outcome.ok is False
    assert "No habit with id 999" in outcome.message


def test_habit_linked_to_a_missing_goal_is_rejected():
    with SessionLocal() as db:
        outcome = tools.execute(
            db, "add_habit", {"text": "x", "cadence": "daily", "linked_goal_id": 404}
        )
    assert outcome.ok is False


def test_habits_reach_the_prompt_with_streak_and_consistency():
    from app.memory import build_system_blocks

    with SessionLocal() as db:
        goal = Goal(text="Fitness", horizon=Horizon.lifetime)
        db.add(goal)
        db.commit()
        habit = habits.create_habit(
            db, text="Train", cadence="weekly", target_per_week=3, why="Best shape of my life."
        )
        habits.log(db, habit.id)
        state = build_system_blocks(db)[1]["text"]

    assert "## Habits" in state
    assert "Train" in state
    assert "3x per week" in state
    assert "consistent over 30 days" in state
    assert "Best shape of my life." in state
