"""HTTP CRUD for the Goals screen.

Thin on purpose — every mutation delegates to crud.py, which the coach's tools also
use. Keeping both callers on one implementation is what stops the two paths drifting.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud
from ..db import get_db
from ..models import Goal, Task
from ..schemas import (
    DashboardOut,
    GoalCreate,
    GoalOut,
    GoalUpdate,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)

router = APIRouter(prefix="/api", tags=["goals & tasks"])


def _not_found(exc: crud.NotFound) -> HTTPException:
    return HTTPException(404, str(exc))


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db)) -> DashboardOut:
    """Everything the home screen needs in one call."""
    from .. import habits
    from .habits_routes import to_out

    return DashboardOut(
        goals=crud.list_goals(db, active_only=True),
        open_tasks=crud.list_tasks(db, open_only=True),
        habits=[to_out(s) for s in habits.all_stats(db)],
        recent_summaries=list(reversed(crud.list_recent_summaries(db, limit=3))),
    )


# --- Goals ---


@router.get("/goals", response_model=list[GoalOut])
def list_goals(db: Session = Depends(get_db)) -> list[Goal]:
    return crud.list_goals(db)


@router.post("/goals", response_model=GoalOut, status_code=201)
def create_goal(payload: GoalCreate, db: Session = Depends(get_db)) -> Goal:
    return crud.create_goal(db, **payload.model_dump())


@router.patch("/goals/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: int, payload: GoalUpdate, db: Session = Depends(get_db)) -> Goal:
    try:
        return crud.update_goal(db, goal_id, payload.model_dump(exclude_unset=True))
    except crud.NotFound as exc:
        raise _not_found(exc) from exc


@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: int, db: Session = Depends(get_db)) -> dict:
    """Soft delete. Returns the undo id so the caller can offer to take it back."""
    try:
        _, undo = crud.delete_goal(db, goal_id)
    except crud.NotFound as exc:
        raise _not_found(exc) from exc
    return {"undo_id": undo.id}


# --- Tasks ---


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(get_db)) -> list[Task]:
    return crud.list_tasks(db)


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)) -> Task:
    try:
        return crud.create_task(db, **payload.model_dump())
    except crud.NotFound as exc:
        # A bad linked_goal_id is the client's mistake, not a missing task.
        raise HTTPException(400, str(exc)) from exc


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)) -> Task:
    try:
        return crud.update_task(db, task_id, payload.model_dump(exclude_unset=True))
    except crud.NotFound as exc:
        raise _not_found(exc) from exc


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)) -> dict:
    """Soft delete. Returns the undo id so the caller can offer to take it back."""
    try:
        _, undo = crud.delete_task(db, task_id)
    except crud.NotFound as exc:
        raise _not_found(exc) from exc
    return {"undo_id": undo.id}


# --- Undo ---


@router.post("/undo")
def undo_latest(db: Session = Depends(get_db)) -> dict:
    """Reverse the most recent deletion. Backs the 'undo' the coach can also do by voice."""
    return _undo(db, None)


@router.post("/undo/{undo_id}")
def undo_specific(undo_id: int, db: Session = Depends(get_db)) -> dict:
    """Reverse one specific change, so the Undo button on an older action note is exact."""
    return _undo(db, undo_id)


def _undo(db: Session, undo_id: int | None) -> dict:
    try:
        entry = crud.apply_undo(db, undo_id)
    except crud.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except crud.UndoExpired as exc:
        # Gone, but not because the request was malformed.
        raise HTTPException(410, str(exc)) from exc
    return {
        "undo_id": entry.id,
        "restored": {"type": entry.target_type, "id": entry.target_id, "label": entry.label},
    }
