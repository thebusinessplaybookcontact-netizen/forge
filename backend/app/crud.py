"""Every database mutation in the app lives here.

Two callers share these functions: the HTTP routes in routers/goals.py (used by the
Goals screen) and the tool executor in tools.py (used by the coach mid-conversation).
Neither owns the logic — this module does. If a rule changes, it changes once.

Functions raise NotFound rather than HTTPException so they stay usable outside a
request; the router translates, and the tool executor turns it into a tool_result the
model can read and recover from.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Goal, GoalStatus, Horizon, Summary, Task, TaskStatus, UndoEntry, utcnow


class CrudError(Exception):
    """Base for anything the caller could reasonably have avoided."""


class NotFound(CrudError):
    pass


class UndoExpired(CrudError):
    pass


# --- Reads ---
#
# Soft-deleted rows are invisible to every read below. That's the whole safety property:
# code that forgets about deleted_at gets the safe behaviour by default, because the
# only way to see a deleted row is to ask for it explicitly.


def get_goal(db: Session, goal_id: int, *, include_deleted: bool = False) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None or (goal.deleted_at is not None and not include_deleted):
        raise NotFound(f"No goal with id {goal_id}.")
    return goal


def get_task(db: Session, task_id: int, *, include_deleted: bool = False) -> Task:
    task = db.get(Task, task_id)
    if task is None or (task.deleted_at is not None and not include_deleted):
        raise NotFound(f"No task with id {task_id}.")
    return task


def list_goals(db: Session, *, active_only: bool = False) -> list[Goal]:
    stmt = select(Goal).where(Goal.deleted_at.is_(None))
    if active_only:
        stmt = stmt.where(Goal.status == GoalStatus.active)
    return list(db.scalars(stmt.order_by(Goal.created_at)))


def list_tasks(db: Session, *, open_only: bool = False) -> list[Task]:
    stmt = select(Task).where(Task.deleted_at.is_(None))
    if open_only:
        stmt = stmt.where(Task.status == TaskStatus.open)
    # Dated tasks first, soonest first, then undated by age.
    stmt = stmt.order_by(Task.due.is_(None), Task.due, Task.created_at)
    return list(db.scalars(stmt))


def list_recent_summaries(db: Session, *, limit: int | None = None) -> list[Summary]:
    limit = limit or get_settings().recent_summary_count
    newest_first = list(db.scalars(select(Summary).order_by(Summary.created_at.desc()).limit(limit)))
    return list(reversed(newest_first))  # chronological reads better in the prompt


# --- Goals ---


def create_goal(
    db: Session,
    *,
    text: str,
    horizon: Horizon | str,
    why: str | None = None,
    status: GoalStatus | str = GoalStatus.active,
) -> Goal:
    goal = Goal(
        text=text,
        horizon=Horizon(horizon),
        why=why,
        status=GoalStatus(status),
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def update_goal(db: Session, goal_id: int, fields: dict) -> Goal:
    """Partial update. Only keys present in `fields` are touched."""
    goal = get_goal(db, goal_id)
    if "text" in fields:
        goal.text = fields["text"]
    if "why" in fields:
        goal.why = fields["why"]
    if "horizon" in fields:
        goal.horizon = Horizon(fields["horizon"])
    if "status" in fields:
        goal.status = GoalStatus(fields["status"])
    db.commit()
    db.refresh(goal)
    return goal


def delete_goal(db: Session, goal_id: int) -> tuple[Goal, UndoEntry]:
    """Soft delete. The row stays; reads stop seeing it.

    Linked tasks keep pointing at it deliberately — nulling them out would make an undo
    only half restore the goal. A task whose goal is deleted simply shows no goal.
    """
    goal = get_goal(db, goal_id)
    goal.deleted_at = utcnow()
    undo = _record_undo(db, action="delete", target_type="goal", target_id=goal.id, label=goal.text)
    db.commit()
    db.refresh(goal)
    return goal, undo


def restore_goal(db: Session, goal_id: int) -> Goal:
    goal = get_goal(db, goal_id, include_deleted=True)
    goal.deleted_at = None
    db.commit()
    db.refresh(goal)
    return goal


# --- Tasks ---


def create_task(
    db: Session,
    *,
    text: str,
    linked_goal_id: int | None = None,
    due: date | None = None,
    status: TaskStatus | str = TaskStatus.open,
) -> Task:
    if linked_goal_id is not None:
        get_goal(db, linked_goal_id)  # raises NotFound if the goal doesn't exist
    task = Task(
        text=text,
        linked_goal_id=linked_goal_id,
        due=due,
        status=TaskStatus(status),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(db: Session, task_id: int, fields: dict) -> Task:
    task = get_task(db, task_id)
    if "text" in fields:
        task.text = fields["text"]
    if "due" in fields:
        task.due = fields["due"]
    if "status" in fields:
        task.status = TaskStatus(fields["status"])
    if "linked_goal_id" in fields:
        goal_id = fields["linked_goal_id"]
        if goal_id is not None:
            get_goal(db, goal_id)
        task.linked_goal_id = goal_id
    db.commit()
    db.refresh(task)
    return task


def complete_task(db: Session, task_id: int) -> Task:
    return update_task(db, task_id, {"status": TaskStatus.done})


def delete_task(db: Session, task_id: int) -> tuple[Task, UndoEntry]:
    """Soft delete. The row stays; reads stop seeing it."""
    task = get_task(db, task_id)
    task.deleted_at = utcnow()
    undo = _record_undo(db, action="delete", target_type="task", target_id=task.id, label=task.text)
    db.commit()
    db.refresh(task)
    return task, undo


def restore_task(db: Session, task_id: int) -> Task:
    task = get_task(db, task_id, include_deleted=True)
    task.deleted_at = None
    db.commit()
    db.refresh(task)
    return task


# --- Undo ---


def _record_undo(db: Session, *, action: str, target_type: str, target_id: int, label: str) -> UndoEntry:
    entry = UndoEntry(action=action, target_type=target_type, target_id=target_id, label=label)
    db.add(entry)
    db.flush()  # populate entry.id without committing; the caller commits
    return entry


def _age_seconds(moment: datetime) -> float:
    # SQLite hands back naive datetimes even from a timezone=True column, so normalise
    # before comparing or this raises on the subtraction.
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - moment).total_seconds()


def _window() -> int:
    return get_settings().undo_window_seconds


def latest_undoable(db: Session) -> UndoEntry | None:
    """The most recent change that hasn't been undone yet, if it's still in window."""
    entry = db.scalars(
        select(UndoEntry).where(UndoEntry.undone_at.is_(None)).order_by(UndoEntry.created_at.desc()).limit(1)
    ).first()
    if entry is None or _age_seconds(entry.created_at) > _window():
        return None
    return entry


def apply_undo(db: Session, undo_id: int | None = None) -> UndoEntry:
    """Reverse a change. Defaults to the most recent one.

    Raises NotFound when there's nothing to undo and UndoExpired when the window has
    passed — the caller distinguishes them because "nothing to undo" and "too late" mean
    different things to the person asking.
    """
    if undo_id is None:
        entry = db.scalars(
            select(UndoEntry).where(UndoEntry.undone_at.is_(None)).order_by(UndoEntry.created_at.desc()).limit(1)
        ).first()
        if entry is None:
            raise NotFound("There's nothing to undo.")
    else:
        entry = db.get(UndoEntry, undo_id)
        if entry is None:
            raise NotFound(f"No undo entry with id {undo_id}.")
        if entry.undone_at is not None:
            raise NotFound("That change was already undone.")

    age = _age_seconds(entry.created_at)
    if age > _window():
        raise UndoExpired(
            f"That was {int(age // 60)} minutes ago, past the {_window() // 60}-minute undo window. "
            "The row still exists though — it can be restored by hand."
        )

    if entry.action != "delete":
        raise CrudError(f"Don't know how to undo a '{entry.action}'.")

    if entry.target_type == "task":
        restore_task(db, entry.target_id)
    elif entry.target_type == "goal":
        restore_goal(db, entry.target_id)
    elif entry.target_type == "habit":
        from . import habits

        habits.restore_habit(db, entry.target_id)
    else:
        raise CrudError(f"Don't know how to undo a '{entry.target_type}'.")

    entry.undone_at = utcnow()
    db.commit()
    db.refresh(entry)
    return entry
