"""Habits: the repeating things, and how well they're actually going.

The measurement design here is deliberate, and it's the part most habit trackers get
wrong. The evidence on streaks cuts both ways: the unbroken chain is genuinely
motivating through loss aversion, but a broken one reliably triggers a "what's the
point" collapse — and the underlying research on habit formation finds that missing a
single day doesn't meaningfully set back the habit at all. So an all-or-nothing streak
is both psychologically risky and factually wrong.

That matters more here than in a normal tracker, because this app has a coach with a
licence to be blunt. A brittle streak counter plus tough love is exactly the
combination that makes someone quit. So:

* **Cadence is flexible.** "Three times a week" is a first-class target, not a daily
  habit you keep failing four days out of seven.
* **Streaks count scheduled units, not raw days.** A 3x/week habit doesn't break
  because you skipped Tuesday; it breaks when a whole week misses target.
* **Today is never a failure.** A day that hasn't happened yet can't break a streak,
  and neither can the current week while it's still running.
* **Consistency sits alongside the streak.** A 30-day completion rate survives a missed
  day, so there's always a number that says "this is still going well" even when the
  chain resets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock
from .models import Cadence, Habit, HabitEntry

# How much history the consistency grid shows. Nine weeks fits a phone and is long
# enough to show a pattern rather than a mood.
GRID_DAYS = 63


def week_start(day: date) -> date:
    """Monday of the week containing `day`."""
    return day - timedelta(days=day.weekday())


@dataclass
class HabitStats:
    habit: Habit
    done_today: bool
    this_week: int
    target_per_week: int
    current_streak: int
    longest_streak: int
    completion_rate_30d: float
    # Oldest-first list of (date, done) for the consistency grid.
    recent: list[tuple[date, bool]]

    @property
    def streak_unit(self) -> str:
        return "day" if self.habit.cadence is Cadence.daily else "week"


def _done_dates(db: Session, habit_id: int) -> set[date]:
    rows = db.scalars(select(HabitEntry.done_on).where(HabitEntry.habit_id == habit_id))
    return set(rows)


def _daily_streaks(done: set[date], today: date) -> tuple[int, int]:
    if not done:
        return 0, 0

    # Current: walk back from today. Not having done it *yet* today doesn't break
    # anything — the day isn't over.
    cursor = today if today in done else today - timedelta(days=1)
    current = 0
    while cursor in done:
        current += 1
        cursor -= timedelta(days=1)

    # Longest: scan runs across all recorded days.
    longest = 0
    for day in done:
        if day - timedelta(days=1) in done:
            continue  # not the start of a run
        run = 0
        cursor = day
        while cursor in done:
            run += 1
            cursor += timedelta(days=1)
        longest = max(longest, run)

    return current, max(longest, current)


def _weekly_streaks(done: set[date], today: date, target: int) -> tuple[int, int]:
    if not done:
        return 0, 0

    per_week: dict[date, int] = {}
    for day in done:
        start = week_start(day)
        per_week[start] = per_week.get(start, 0) + 1

    this_week = week_start(today)

    # Current: the week in progress counts if it has already hit target, but a week
    # that's merely unfinished must not read as a break.
    cursor = this_week if per_week.get(this_week, 0) >= target else this_week - timedelta(days=7)
    current = 0
    while per_week.get(cursor, 0) >= target:
        current += 1
        cursor -= timedelta(days=7)

    longest = 0
    for start in per_week:
        if per_week.get(start - timedelta(days=7), 0) >= target:
            continue
        if per_week.get(start, 0) < target:
            continue
        run = 0
        cursor = start
        while per_week.get(cursor, 0) >= target:
            run += 1
            cursor += timedelta(days=7)
        longest = max(longest, run)

    return current, max(longest, current)


def stats_for(db: Session, habit: Habit, *, today: date | None = None) -> HabitStats:
    today = today or clock.today_local()
    done = _done_dates(db, habit.id)

    target = 7 if habit.cadence is Cadence.daily else max(1, habit.target_per_week)

    if habit.cadence is Cadence.daily:
        current, longest = _daily_streaks(done, today)
    else:
        current, longest = _weekly_streaks(done, today, target)

    start_of_week = week_start(today)
    this_week = sum(1 for d in done if start_of_week <= d <= today)

    # Rate is measured from when the habit started, so a habit created three days ago
    # doesn't show 10% just because the window is 30 days long.
    window_start = max(today - timedelta(days=29), clock.to_local(habit.created_at).date())
    window_days = (today - window_start).days + 1
    expected = window_days * (target / 7)
    hit = sum(1 for d in done if window_start <= d <= today)
    rate = min(1.0, hit / expected) if expected > 0 else 0.0

    grid_start = today - timedelta(days=GRID_DAYS - 1)
    recent = [
        (grid_start + timedelta(days=i), (grid_start + timedelta(days=i)) in done)
        for i in range(GRID_DAYS)
    ]

    return HabitStats(
        habit=habit,
        done_today=today in done,
        this_week=this_week,
        target_per_week=target,
        current_streak=current,
        longest_streak=longest,
        completion_rate_30d=round(rate, 3),
        recent=recent,
    )


# --- reads & writes ---


def list_habits(db: Session) -> list[Habit]:
    stmt = select(Habit).where(Habit.deleted_at.is_(None)).order_by(Habit.created_at)
    return list(db.scalars(stmt))


def all_stats(db: Session, *, today: date | None = None) -> list[HabitStats]:
    today = today or clock.today_local()
    return [stats_for(db, h, today=today) for h in list_habits(db)]


def get_habit(db: Session, habit_id: int, *, include_deleted: bool = False) -> Habit:
    from .crud import NotFound

    habit = db.get(Habit, habit_id)
    if habit is None or (habit.deleted_at is not None and not include_deleted):
        raise NotFound(f"No habit with id {habit_id}.")
    return habit


def create_habit(
    db: Session,
    *,
    text: str,
    cadence: Cadence | str = Cadence.daily,
    target_per_week: int = 7,
    why: str | None = None,
    linked_goal_id: int | None = None,
) -> Habit:
    from . import crud

    if linked_goal_id is not None:
        crud.get_goal(db, linked_goal_id)

    cadence = Cadence(cadence)
    if cadence is Cadence.daily:
        target_per_week = 7
    habit = Habit(
        text=text,
        cadence=cadence,
        target_per_week=max(1, min(7, target_per_week)),
        why=why,
        linked_goal_id=linked_goal_id,
    )
    db.add(habit)
    db.commit()
    db.refresh(habit)
    return habit


def update_habit(db: Session, habit_id: int, fields: dict) -> Habit:
    habit = get_habit(db, habit_id)
    if "text" in fields:
        habit.text = fields["text"]
    if "why" in fields:
        habit.why = fields["why"]
    if "cadence" in fields:
        habit.cadence = Cadence(fields["cadence"])
        if habit.cadence is Cadence.daily:
            habit.target_per_week = 7
    if "target_per_week" in fields and habit.cadence is not Cadence.daily:
        habit.target_per_week = max(1, min(7, fields["target_per_week"]))
    if "linked_goal_id" in fields:
        from . import crud

        goal_id = fields["linked_goal_id"]
        if goal_id is not None:
            crud.get_goal(db, goal_id)
        habit.linked_goal_id = goal_id
    db.commit()
    db.refresh(habit)
    return habit


def delete_habit(db: Session, habit_id: int):
    """Soft delete, with an undo entry — same contract as goals and tasks."""
    from . import crud
    from .models import utcnow

    habit = get_habit(db, habit_id)
    habit.deleted_at = utcnow()
    undo = crud._record_undo(
        db, action="delete", target_type="habit", target_id=habit.id, label=habit.text
    )
    db.commit()
    db.refresh(habit)
    return habit, undo


def restore_habit(db: Session, habit_id: int) -> Habit:
    habit = get_habit(db, habit_id, include_deleted=True)
    habit.deleted_at = None
    db.commit()
    db.refresh(habit)
    return habit


def log(db: Session, habit_id: int, when: date | None = None) -> HabitStats:
    """Mark a habit done for a day. Idempotent — logging twice is not two."""
    habit = get_habit(db, habit_id)
    when = when or clock.today_local()

    existing = db.scalars(
        select(HabitEntry).where(HabitEntry.habit_id == habit.id, HabitEntry.done_on == when)
    ).first()
    if existing is None:
        db.add(HabitEntry(habit_id=habit.id, done_on=when))
        db.commit()

    return stats_for(db, habit)


def unlog(db: Session, habit_id: int, when: date | None = None) -> HabitStats:
    """Undo a log — for the inevitable mis-tap."""
    habit = get_habit(db, habit_id)
    when = when or clock.today_local()

    entry = db.scalars(
        select(HabitEntry).where(HabitEntry.habit_id == habit.id, HabitEntry.done_on == when)
    ).first()
    if entry is not None:
        db.delete(entry)
        db.commit()

    return stats_for(db, habit)
