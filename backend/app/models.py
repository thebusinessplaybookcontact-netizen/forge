from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Horizon(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
    lifetime = "lifetime"


class GoalStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    done = "done"


class TaskStatus(str, enum.Enum):
    open = "open"
    done = "done"


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    horizon: Mapped[Horizon] = mapped_column(Enum(Horizon), nullable=False)
    # The "why" is the lever the coach pulls when calling me out. Keep it in the data model,
    # not in the prompt.
    why: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[GoalStatus] = mapped_column(Enum(GoalStatus), default=GoalStatus.active)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Soft delete. Nothing in this app removes a row — a misheard sentence should never
    # be unrecoverable. Set means "deleted"; normal reads filter these out.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    tasks: Mapped[list[Task]] = relationship(back_populates="goal")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    linked_goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"), default=None)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.open)
    due: Mapped[date | None] = mapped_column(Date, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    goal: Mapped[Goal | None] = relationship(back_populates="tasks")


class UndoEntry(Base):
    """One reversible change, recorded so it can be taken back.

    Lives in the database rather than in process memory so an undo survives a restart
    and works regardless of which worker handled the original request — the SSE
    generator already runs on its own session.
    """

    __tablename__ = "undo_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Only "delete" today. The column exists so restoring other operations later
    # doesn't need a migration.
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)  # "task" | "goal"
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # What was affected, so "undo" can say what it put back without re-reading the row.
    label: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Cadence(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"  # target_per_week times, any days


class Habit(Base):
    """Something repeated, as opposed to a task that's done once and gone.

    Separate from tasks on purpose: ticking "leg day" off a to-do list destroys the
    information that matters here, which is the pattern over weeks.
    """

    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    cadence: Mapped[Cadence] = mapped_column(Enum(Cadence), default=Cadence.daily)
    # Only meaningful for weekly cadence; daily habits are effectively 7.
    target_per_week: Mapped[int] = mapped_column(Integer, default=7)
    why: Mapped[str | None] = mapped_column(Text, default=None)
    linked_goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    entries: Mapped[list[HabitEntry]] = relationship(
        back_populates="habit", cascade="all, delete-orphan"
    )


class HabitEntry(Base):
    """One day a habit was done. Absence means not done — there are no 'missed' rows."""

    __tablename__ = "habit_entries"
    __table_args__ = (UniqueConstraint("habit_id", "done_on", name="uq_habit_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id"), nullable=False)
    # Stored as a local date, not a timestamp: "did I do it Tuesday" is a calendar
    # question, and a UTC timestamp would put late-evening entries on the wrong day.
    done_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    habit: Mapped[Habit] = relationship(back_populates="entries")


class UsageEvent(Base):
    """Token usage for one model call, so spend is observable rather than a surprise.

    Recorded per call rather than per turn: a turn that uses tools makes several, and
    the difference between "one expensive turn" and "a tool loop that ran six times" is
    exactly what you'd want to see.
    """

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default="chat")  # chat | summary
    model: Mapped[str] = mapped_column(String(64), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CheckInSession(Base):
    """One conversation. The transcript is stored for the record but is never
    replayed into the model's context — only the summary is."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Bumped on every turn. A conversation is "over" when this stops moving, which is
    # the only signal available — nobody taps a "done" button on a voice app.
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # JSON array of {"role": ..., "content": ...} turns.
    transcript: Mapped[str] = mapped_column(Text, default="[]")

    summary: Mapped[Summary | None] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )


class Summary(Base):
    """The compact recap written after a session: what happened, what I committed to.

    This is the memory that gets loaded next time. Kept in its own table (rather than a
    column on sessions) so recaps are cheap to query and page without dragging transcripts
    along.
    """

    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), unique=True)
    recap: Mapped[str] = mapped_column(Text, nullable=False)
    # Newline-separated list of what I said I'd do.
    commitments: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[CheckInSession] = relationship(back_populates="summary")
