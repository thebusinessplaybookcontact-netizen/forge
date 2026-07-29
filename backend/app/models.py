from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text
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

    tasks: Mapped[list[Task]] = relationship(back_populates="goal")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    linked_goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"), default=None)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.open)
    due: Mapped[date | None] = mapped_column(Date, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    goal: Mapped[Goal | None] = relationship(back_populates="tasks")


class CheckInSession(Base):
    """One conversation. The transcript is stored for the record but is never
    replayed into the model's context — only the summary is."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
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
