"""The tools the coach can call, and the code that executes them.

Kept out of prompts.py deliberately: the persona describes *how* the coach talks, this
describes *what it can do*. Neither should have to change when the other does.

Three layers, in order:

1. TOOL_DEFINITIONS — the JSON schemas sent to the API.
2. A Pydantic model per tool — validates the model's arguments before anything touches
   the database. The model is capable of inventing a task id or a malformed date, and
   that must come back as a readable tool_result rather than a 500.
3. execute() — dispatches to crud.py. No SQL lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from . import crud, habits
from .models import Goal, Habit, Task

# Tool definitions render *before* the system prompt in the request, so this list is
# part of the cached prefix. Keep the order stable — reordering it silently invalidates
# the prompt cache for every request.
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "add_task",
        "description": (
            "Add a task to Kyle's to-do list. Use this the moment he says he needs to do "
            "something — don't ask permission first. Link it to a goal when it clearly "
            "serves one. Due dates are absolute (YYYY-MM-DD); today's date is in the "
            "system prompt, so resolve 'today' or 'Friday' yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The task, in Kyle's own words where possible.",
                },
                "linked_goal_id": {
                    "type": "integer",
                    "description": "Id of the goal this serves. Omit if it serves none.",
                },
                "due": {
                    "type": "string",
                    "description": "Due date as YYYY-MM-DD. Omit if there's no deadline.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "complete_task",
        "description": (
            "Mark a task done. Use this when Kyle says he did something, even in passing "
            "('finally called the accountant')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Id of the task, from the state block."},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "update_task",
        "description": (
            "Change a task's wording, due date, or status. Use this to reschedule or "
            "reword; use complete_task for simply finishing it. Only pass the fields "
            "that change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "text": {"type": "string", "description": "New wording."},
                "due": {
                    "type": "string",
                    "description": "New due date as YYYY-MM-DD, or null to clear it.",
                },
                "status": {"type": "string", "enum": ["open", "done"]},
                "linked_goal_id": {
                    "type": "integer",
                    "description": "Re-point at another goal, or null to unlink.",
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "delete_task",
        "description": (
            "Remove a task from the list. Use this when it shouldn't have existed or no "
            "longer matters. If Kyle actually did it, use complete_task instead so it "
            "stays on the record. This is reversible — undo_last puts it back."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "add_goal",
        "description": (
            "Add a goal. Always capture the 'why' — it's what you reflect back at him "
            "later, so use his own reason in his own words. If he hasn't said why it "
            "matters, ask before recording it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The goal."},
                "horizon": {
                    "type": "string",
                    "enum": ["daily", "weekly", "lifetime"],
                    "description": "Time horizon this goal lives on.",
                },
                "why": {
                    "type": "string",
                    "description": "Kyle's reason, in his words. This is the important field.",
                },
            },
            "required": ["text", "horizon"],
        },
    },
    {
        "name": "update_goal",
        "description": (
            "Change a goal's wording, why, horizon, or status. Set status to 'done' when "
            "he's achieved it or 'paused' when he's deliberately setting it aside — don't "
            "pause a goal just because he's behind on it. Only pass fields that change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal_id": {"type": "integer"},
                "text": {"type": "string"},
                "why": {"type": "string"},
                "horizon": {"type": "string", "enum": ["daily", "weekly", "lifetime"]},
                "status": {"type": "string", "enum": ["active", "paused", "done"]},
            },
            "required": ["goal_id"],
        },
    },
    {
        "name": "delete_goal",
        "description": (
            "Remove a goal from the list. Reversible via undo_last. Prefer update_goal "
            "with status 'done' when he achieved it, or 'paused' when he's deliberately "
            "setting it aside — deleting is for goals that were a mistake to record."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"goal_id": {"type": "integer"}},
            "required": ["goal_id"],
        },
    },
    {
        "name": "add_habit",
        "description": (
            "Start tracking something Kyle does repeatedly — training, writing, reading. "
            "Use this instead of add_task when it recurs. Cadence 'daily' for every day, "
            "or 'weekly' with target_per_week for things like three gym sessions a week. "
            "Prefer a weekly target when he says 'a few times a week' — a realistic "
            "target he hits beats a daily one he keeps missing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The habit, e.g. 'Train'."},
                "cadence": {"type": "string", "enum": ["daily", "weekly"]},
                "target_per_week": {
                    "type": "integer",
                    "description": "How many times a week, for weekly cadence. 1-7.",
                },
                "why": {"type": "string", "description": "His reason, in his words."},
                "linked_goal_id": {"type": "integer", "description": "Goal this serves."},
            },
            "required": ["text", "cadence"],
        },
    },
    {
        "name": "log_habit",
        "description": (
            "Record that Kyle did a habit. Use it the moment he mentions doing one, even "
            "in passing ('got the gym in this morning'). Defaults to today; pass a date "
            "for 'I did it yesterday'. Logging the same day twice is harmless."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "habit_id": {"type": "integer"},
                "on": {"type": "string", "description": "YYYY-MM-DD. Omit for today."},
            },
            "required": ["habit_id"],
        },
    },
    {
        "name": "unlog_habit",
        "description": (
            "Remove a habit log, for when it was recorded by mistake. Don't use this as "
            "punishment for a bad day — only when the record is actually wrong."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "habit_id": {"type": "integer"},
                "on": {"type": "string", "description": "YYYY-MM-DD. Omit for today."},
            },
            "required": ["habit_id"],
        },
    },
    {
        "name": "undo_last",
        "description": (
            "Reverse the most recent deletion. Use this when Kyle says 'undo', 'never "
            "mind', 'put that back', or otherwise signals the last change was wrong — "
            "including when he's correcting a misheard instruction. Don't ask him to "
            "confirm, just do it and say what came back."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

TOOL_NAMES = frozenset(t["name"] for t in TOOL_DEFINITIONS)


# --- Argument validation ---
#
# `extra="forbid"` makes a hallucinated argument name a clean validation error instead
# of a silently ignored field. Optional fields default to a sentinel so "not mentioned"
# stays distinguishable from "explicitly set to null" — the model uses null to *clear* a
# due date, which is different from leaving it alone.

UNSET = "__unset__"


class AddTask(BaseModel, extra="forbid"):
    text: str = Field(min_length=1)
    linked_goal_id: int | None = None
    due: date | None = None


class CompleteTask(BaseModel, extra="forbid"):
    task_id: int


class UpdateTask(BaseModel, extra="forbid"):
    task_id: int
    text: str | None = Field(default=UNSET, min_length=1)  # type: ignore[assignment]
    due: date | None = UNSET  # type: ignore[assignment]
    status: Literal["open", "done"] | None = UNSET  # type: ignore[assignment]
    linked_goal_id: int | None = UNSET  # type: ignore[assignment]


class DeleteTask(BaseModel, extra="forbid"):
    task_id: int


class DeleteGoal(BaseModel, extra="forbid"):
    goal_id: int


class UndoLast(BaseModel, extra="forbid"):
    pass


class AddHabit(BaseModel, extra="forbid"):
    text: str = Field(min_length=1)
    cadence: Literal["daily", "weekly"]
    target_per_week: int = Field(default=7, ge=1, le=7)
    why: str | None = None
    linked_goal_id: int | None = None


class LogHabit(BaseModel, extra="forbid"):
    habit_id: int
    on: date | None = None


class AddGoal(BaseModel, extra="forbid"):
    text: str = Field(min_length=1)
    horizon: Literal["daily", "weekly", "lifetime"]
    why: str | None = None


class UpdateGoal(BaseModel, extra="forbid"):
    goal_id: int
    text: str | None = Field(default=UNSET, min_length=1)  # type: ignore[assignment]
    why: str | None = UNSET  # type: ignore[assignment]
    horizon: Literal["daily", "weekly", "lifetime"] | None = UNSET  # type: ignore[assignment]
    status: Literal["active", "paused", "done"] | None = UNSET  # type: ignore[assignment]


def _changed_fields(model: BaseModel, keys: tuple[str, ...]) -> dict:
    """Pull out only the fields the model actually supplied."""
    return {k: getattr(model, k) for k in keys if getattr(model, k) != UNSET}


@dataclass
class ToolOutcome:
    """What happened, in a shape both the model and the UI can use."""

    name: str
    ok: bool
    # Goes back to the model as the tool_result content.
    message: str
    # Short human-facing line for the chat transcript.
    summary: str = ""
    entity: dict | None = field(default=None)
    # Set when this change can be taken back. Drives the Undo button on the action note.
    undo_id: int | None = None

    @property
    def is_error(self) -> bool:
        return not self.ok


def _task_view(task: Task) -> dict:
    return {
        "id": task.id,
        "text": task.text,
        "status": task.status.value,
        "due": task.due.isoformat() if task.due else None,
        "linked_goal_id": task.linked_goal_id,
    }


def _goal_view(goal: Goal) -> dict:
    return {
        "id": goal.id,
        "text": goal.text,
        "horizon": goal.horizon.value,
        "status": goal.status.value,
        "why": goal.why,
    }


def _habit_view(habit: Habit) -> dict:
    return {
        "id": habit.id,
        "text": habit.text,
        "cadence": habit.cadence.value,
        "target_per_week": habit.target_per_week,
    }


def execute(db: Session, name: str, raw_input: dict) -> ToolOutcome:
    """Validate, run, and describe one tool call.

    Never raises for input the model got wrong — an unknown tool, a bad argument, or a
    missing id all come back as ok=False so the model can read the problem and correct
    itself on the next iteration.
    """
    if name not in TOOL_NAMES:
        return ToolOutcome(name, False, f"Unknown tool '{name}'.")

    try:
        return _dispatch(db, name, raw_input)
    except ValidationError as exc:
        # Compact: the model needs to know which field and why, not a stack trace.
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}" for e in exc.errors()
        )
        return ToolOutcome(name, False, f"Invalid arguments — {problems}")
    except crud.NotFound as exc:
        return ToolOutcome(name, False, str(exc))
    except crud.UndoExpired as exc:
        return ToolOutcome(name, False, str(exc))
    except crud.CrudError as exc:
        return ToolOutcome(name, False, str(exc))


def _dispatch(db: Session, name: str, raw: dict) -> ToolOutcome:
    if name == "add_task":
        args = AddTask.model_validate(raw)
        task = crud.create_task(
            db, text=args.text, linked_goal_id=args.linked_goal_id, due=args.due
        )
        when = f" (due {task.due.isoformat()})" if task.due else ""
        return ToolOutcome(
            name,
            True,
            f"Added task {task.id}: {task.text}{when}",
            summary=f"Added “{task.text}”{when}",
            entity=_task_view(task),
        )

    if name == "complete_task":
        args = CompleteTask.model_validate(raw)
        task = crud.complete_task(db, args.task_id)
        return ToolOutcome(
            name,
            True,
            f"Task {task.id} marked done: {task.text}",
            summary=f"Completed “{task.text}”",
            entity=_task_view(task),
        )

    if name == "update_task":
        args = UpdateTask.model_validate(raw)
        fields = _changed_fields(args, ("text", "due", "status", "linked_goal_id"))
        if not fields:
            return ToolOutcome(name, False, "Nothing to update — pass at least one field to change.")
        task = crud.update_task(db, args.task_id, fields)
        return ToolOutcome(
            name,
            True,
            f"Task {task.id} updated: {_task_view(task)}",
            summary=f"Updated “{task.text}”",
            entity=_task_view(task),
        )

    if name == "delete_task":
        args = DeleteTask.model_validate(raw)
        task, undo = crud.delete_task(db, args.task_id)
        return ToolOutcome(
            name,
            True,
            f"Deleted task {task.id}: {task.text}. Reversible with undo_last.",
            summary=f"Deleted “{task.text}”",
            undo_id=undo.id,
        )

    if name == "delete_goal":
        args = DeleteGoal.model_validate(raw)
        goal, undo = crud.delete_goal(db, args.goal_id)
        return ToolOutcome(
            name,
            True,
            f"Deleted goal {goal.id}: {goal.text}. Reversible with undo_last.",
            summary=f"Deleted goal “{goal.text}”",
            undo_id=undo.id,
        )

    if name == "add_habit":
        args = AddHabit.model_validate(raw)
        habit = habits.create_habit(
            db,
            text=args.text,
            cadence=args.cadence,
            target_per_week=args.target_per_week,
            why=args.why,
            linked_goal_id=args.linked_goal_id,
        )
        cadence = "daily" if habit.cadence.value == "daily" else f"{habit.target_per_week}x per week"
        return ToolOutcome(
            name,
            True,
            f"Tracking habit {habit.id}: {habit.text} ({cadence})",
            summary=f"Now tracking “{habit.text}” ({cadence})",
            entity=_habit_view(habit),
        )

    if name in ("log_habit", "unlog_habit"):
        args = LogHabit.model_validate(raw)
        action = habits.log if name == "log_habit" else habits.unlog
        stats = action(db, args.habit_id, args.on)
        habit = stats.habit

        if name == "unlog_habit":
            return ToolOutcome(
                name,
                True,
                f"Removed the log for {habit.text} on {args.on or 'today'}.",
                summary=f"Unlogged “{habit.text}”",
                entity=_habit_view(habit),
            )

        # Hand the model the numbers so it can react specifically rather than generically.
        if habit.cadence.value == "daily":
            # This string is read aloud by the voice as well as shown, so "1 days" is
            # not a typo you can leave in.
            days = stats.current_streak
            progress = f"streak now {days} day{'' if days == 1 else 's'}"
        else:
            progress = f"{stats.this_week} of {stats.target_per_week} this week"
        return ToolOutcome(
            name,
            True,
            f"Logged {habit.text} for {args.on or 'today'}; {progress}, "
            f"{round(stats.completion_rate_30d * 100)}% consistent over 30 days.",
            summary=f"Logged “{habit.text}” — {progress}",
            entity=_habit_view(habit),
        )

    if name == "undo_last":
        UndoLast.model_validate(raw)
        entry = crud.apply_undo(db)
        noun = "goal" if entry.target_type == "goal" else "task"
        return ToolOutcome(
            name,
            True,
            f"Restored {noun} {entry.target_id}: {entry.label}",
            summary=f"Restored {noun} “{entry.label}”",
        )

    if name == "add_goal":
        args = AddGoal.model_validate(raw)
        goal = crud.create_goal(db, text=args.text, horizon=args.horizon, why=args.why)
        return ToolOutcome(
            name,
            True,
            f"Added {goal.horizon.value} goal {goal.id}: {goal.text}",
            summary=f"Added goal “{goal.text}”",
            entity=_goal_view(goal),
        )

    if name == "update_goal":
        args = UpdateGoal.model_validate(raw)
        fields = _changed_fields(args, ("text", "why", "horizon", "status"))
        if not fields:
            return ToolOutcome(name, False, "Nothing to update — pass at least one field to change.")
        goal = crud.update_goal(db, args.goal_id, fields)
        return ToolOutcome(
            name,
            True,
            f"Goal {goal.id} updated: {_goal_view(goal)}",
            summary=f"Updated goal “{goal.text}”",
            entity=_goal_view(goal),
        )

    raise AssertionError(f"tool {name!r} is defined but has no dispatch branch")
