"""Every database mutation in the app lives here.

Two callers share these functions: the HTTP routes in routers/goals.py (used by the
Goals screen) and the tool executor in tools.py (used by the coach mid-conversation).
Neither owns the logic — this module does. If a rule changes, it changes once.

Functions raise NotFound rather than HTTPException so they stay usable outside a
request; the router translates, and the tool executor turns it into a tool_result the
model can read and recover from.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Goal, GoalStatus, Horizon, Summary, Task, TaskStatus


class CrudError(Exception):
    """Base for anything the caller could reasonably have avoided."""


class NotFound(CrudError):
    pass


# --- Reads ---


def get_goal(db: Session, goal_id: int) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise NotFound(f"No goal with id {goal_id}.")
    return goal


def get_task(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise NotFound(f"No task with id {task_id}.")
    return task


def list_goals(db: Session, *, active_only: bool = False) -> list[Goal]:
    stmt = select(Goal)
    if active_only:
        stmt = stmt.where(Goal.status == GoalStatus.active)
    return list(db.scalars(stmt.order_by(Goal.created_at)))


def list_tasks(db: Session, *, open_only: bool = False) -> list[Task]:
    stmt = select(Task)
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


def delete_goal(db: Session, goal_id: int) -> Goal:
    goal = get_goal(db, goal_id)
    # Orphan the tasks rather than deleting them — they may still be worth doing.
    for task in goal.tasks:
        task.linked_goal_id = None
    db.delete(goal)
    db.commit()
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


def delete_task(db: Session, task_id: int) -> Task:
    task = get_task(db, task_id)
    db.delete(task)
    db.commit()
    return task
