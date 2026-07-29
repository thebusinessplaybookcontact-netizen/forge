from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..memory import load_goals, load_open_tasks, load_recent_summaries
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


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db)) -> DashboardOut:
    """Everything the home screen needs in one call."""
    return DashboardOut(
        goals=load_goals(db),
        open_tasks=load_open_tasks(db),
        recent_summaries=list(reversed(load_recent_summaries(db, limit=3))),
    )


# --- Goals ---


@router.get("/goals", response_model=list[GoalOut])
def list_goals(db: Session = Depends(get_db)) -> list[Goal]:
    return list(db.scalars(select(Goal).order_by(Goal.created_at)))


@router.post("/goals", response_model=GoalOut, status_code=201)
def create_goal(payload: GoalCreate, db: Session = Depends(get_db)) -> Goal:
    goal = Goal(**payload.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@router.patch("/goals/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: int, payload: GoalUpdate, db: Session = Depends(get_db)) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, f"goal {goal_id} not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)
    db.commit()
    db.refresh(goal)
    return goal


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, db: Session = Depends(get_db)) -> None:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, f"goal {goal_id} not found")
    # Orphan the tasks rather than deleting them — they may still be worth doing.
    for task in goal.tasks:
        task.linked_goal_id = None
    db.delete(goal)
    db.commit()


# --- Tasks ---


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(get_db)) -> list[Task]:
    return list(db.scalars(select(Task).order_by(Task.created_at)))


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)) -> Task:
    if payload.linked_goal_id is not None and db.get(Goal, payload.linked_goal_id) is None:
        raise HTTPException(400, f"goal {payload.linked_goal_id} not found")
    task = Task(**payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"task {task_id} not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, db: Session = Depends(get_db)) -> None:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"task {task_id} not found")
    db.delete(task)
    db.commit()
