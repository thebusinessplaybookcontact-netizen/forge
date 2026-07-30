from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, habits
from ..db import get_db
from ..habits import HabitStats
from ..schemas import HabitCreate, HabitOut, HabitUpdate, LogHabitRequest

router = APIRouter(prefix="/api/habits", tags=["habits"])


def to_out(stats: HabitStats) -> HabitOut:
    habit = stats.habit
    return HabitOut(
        id=habit.id,
        text=habit.text,
        cadence=habit.cadence.value,
        target_per_week=stats.target_per_week,
        why=habit.why,
        linked_goal_id=habit.linked_goal_id,
        done_today=stats.done_today,
        this_week=stats.this_week,
        current_streak=stats.current_streak,
        longest_streak=stats.longest_streak,
        completion_rate_30d=stats.completion_rate_30d,
        grid_start=stats.recent[0][0],
        grid=[done for _, done in stats.recent],
    )


@router.get("", response_model=list[HabitOut])
def list_habits(db: Session = Depends(get_db)) -> list[HabitOut]:
    return [to_out(s) for s in habits.all_stats(db)]


@router.post("", response_model=HabitOut, status_code=201)
def create_habit(payload: HabitCreate, db: Session = Depends(get_db)) -> HabitOut:
    try:
        habit = habits.create_habit(db, **payload.model_dump())
    except crud.NotFound as exc:
        raise HTTPException(400, str(exc)) from exc
    return to_out(habits.stats_for(db, habit))


@router.patch("/{habit_id}", response_model=HabitOut)
def update_habit(habit_id: int, payload: HabitUpdate, db: Session = Depends(get_db)) -> HabitOut:
    try:
        habit = habits.update_habit(db, habit_id, payload.model_dump(exclude_unset=True))
    except crud.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return to_out(habits.stats_for(db, habit))


@router.delete("/{habit_id}")
def delete_habit(habit_id: int, db: Session = Depends(get_db)) -> dict:
    """Soft delete, so the history isn't destroyed and it can be undone."""
    try:
        _, undo = habits.delete_habit(db, habit_id)
    except crud.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"undo_id": undo.id}


@router.post("/{habit_id}/log", response_model=HabitOut)
def log_habit(
    habit_id: int, payload: LogHabitRequest | None = None, db: Session = Depends(get_db)
) -> HabitOut:
    """Mark done. Returns the updated stats so the UI can show the new streak at once."""
    try:
        return to_out(habits.log(db, habit_id, payload.on if payload else None))
    except crud.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{habit_id}/unlog", response_model=HabitOut)
def unlog_habit(
    habit_id: int, payload: LogHabitRequest | None = None, db: Session = Depends(get_db)
) -> HabitOut:
    try:
        return to_out(habits.unlog(db, habit_id, payload.on if payload else None))
    except crud.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
