from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Horizon = Literal["daily", "weekly", "lifetime"]
GoalStatus = Literal["active", "paused", "done"]
TaskStatus = Literal["open", "done"]


# --- Goals ---


class GoalCreate(BaseModel):
    text: str
    horizon: Horizon
    why: str | None = None
    status: GoalStatus = "active"


class GoalUpdate(BaseModel):
    text: str | None = None
    horizon: Horizon | None = None
    why: str | None = None
    status: GoalStatus | None = None


class GoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    horizon: Horizon
    why: str | None
    status: GoalStatus
    created_at: datetime


# --- Tasks ---


class TaskCreate(BaseModel):
    text: str
    linked_goal_id: int | None = None
    status: TaskStatus = "open"
    due: date | None = None


class TaskUpdate(BaseModel):
    text: str | None = None
    linked_goal_id: int | None = None
    status: TaskStatus | None = None
    due: date | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    linked_goal_id: int | None
    status: TaskStatus
    due: date | None
    created_at: datetime


# --- Chat ---


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: int | None = None
    # Turns from the current session only. Prior sessions come back as summaries,
    # never as replayed transcripts.
    history: list[ChatTurn] = Field(default_factory=list)


class ChatUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)


class ToolAction(BaseModel):
    """One change the coach made to goals or tasks during this turn."""

    name: str
    ok: bool
    summary: str
    entity: dict | None = None
    # Present when the change is reversible; the UI shows an Undo affordance for it.
    undo_id: int | None = None


class ChatResponse(BaseModel):
    session_id: int
    reply: str
    # What the coach actually changed, in the order it happened.
    actions: list[ToolAction] = Field(default_factory=list)
    usage: ChatUsage | None = None


# --- Sessions & summaries ---


class SummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    recap: str
    commitments: str
    created_at: datetime


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    ended_at: datetime | None


# --- Habits ---

Cadence = Literal["daily", "weekly"]


class HabitCreate(BaseModel):
    text: str = Field(min_length=1)
    cadence: Cadence = "daily"
    target_per_week: int = Field(default=7, ge=1, le=7)
    why: str | None = None
    linked_goal_id: int | None = None


class HabitUpdate(BaseModel):
    text: str | None = None
    cadence: Cadence | None = None
    target_per_week: int | None = Field(default=None, ge=1, le=7)
    why: str | None = None
    linked_goal_id: int | None = None


class HabitOut(BaseModel):
    """A habit plus everything needed to render it, in one object.

    The stats are computed, not stored, so there's no version of this where the
    displayed streak and the entries disagree.
    """

    id: int
    text: str
    cadence: Cadence
    target_per_week: int
    why: str | None
    linked_goal_id: int | None

    done_today: bool
    this_week: int
    current_streak: int
    longest_streak: int
    completion_rate_30d: float
    # Oldest-first booleans for the consistency grid, with the date the run starts.
    grid_start: date
    grid: list[bool]


class LogHabitRequest(BaseModel):
    on: date | None = None


class DashboardOut(BaseModel):
    goals: list[GoalOut]
    open_tasks: list[TaskOut]
    habits: list[HabitOut]
    recent_summaries: list[SummaryOut]
