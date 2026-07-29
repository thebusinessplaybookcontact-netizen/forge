"""Assembles what the model sees.

The rule this file exists to enforce: past conversations are never replayed. Each
request carries the system prompt + structured goals/tasks + the last N session
recaps. Token use stays bounded no matter how long the app has been in use.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import CheckInSession, Goal, GoalStatus, Horizon, Summary, Task, TaskStatus
from .prompts import COACH_PERSONA, build_state_block

HORIZON_LABELS = {
    Horizon.daily: "Daily",
    Horizon.weekly: "Weekly",
    Horizon.lifetime: "Lifetime",
}


def _format_goals(goals: list[Goal]) -> str:
    if not goals:
        return "(No goals set yet. If Kyle describes one, encourage him to name it and say why it matters.)"

    lines: list[str] = []
    for horizon in (Horizon.daily, Horizon.weekly, Horizon.lifetime):
        in_horizon = [g for g in goals if g.horizon is horizon]
        if not in_horizon:
            continue
        lines.append(f"{HORIZON_LABELS[horizon]}:")
        for g in in_horizon:
            line = f"- [{g.id}] {g.text}"
            if g.why:
                line += f"\n      why: {g.why}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).strip()


def _format_tasks(tasks: list[Task], goals: list[Goal]) -> str:
    if not tasks:
        return "(Nothing open.)"

    goal_text = {g.id: g.text for g in goals}
    lines = []
    for t in tasks:
        line = f"- [{t.id}] {t.text}"
        bits = []
        if t.due:
            bits.append(f"due {t.due.isoformat()}")
        if t.linked_goal_id and t.linked_goal_id in goal_text:
            bits.append(f"serves: {goal_text[t.linked_goal_id]}")
        if bits:
            line += f" ({', '.join(bits)})"
        lines.append(line)
    return "\n".join(lines)


def _format_summaries(summaries: list[Summary]) -> str:
    if not summaries:
        return "(No previous sessions. This is the first conversation.)"

    lines = []
    for s in summaries:
        when = s.created_at.date().isoformat()
        lines.append(f"### {when}")
        lines.append(s.recap)
        if s.commitments.strip():
            lines.append("Committed to:")
            for c in s.commitments.splitlines():
                if c.strip():
                    lines.append(f"- {c.strip()}")
        lines.append("")
    return "\n".join(lines).strip()


def load_goals(db: Session) -> list[Goal]:
    stmt = select(Goal).where(Goal.status == GoalStatus.active).order_by(Goal.created_at)
    return list(db.scalars(stmt))


def load_open_tasks(db: Session) -> list[Task]:
    stmt = select(Task).where(Task.status == TaskStatus.open).order_by(Task.due.is_(None), Task.due, Task.created_at)
    return list(db.scalars(stmt))


def load_recent_summaries(db: Session, limit: int | None = None) -> list[Summary]:
    limit = limit or get_settings().recent_summary_count
    stmt = select(Summary).order_by(Summary.created_at.desc()).limit(limit)
    newest_first = list(db.scalars(stmt))
    return list(reversed(newest_first))  # chronological reads better in the prompt


def build_system_blocks(db: Session) -> list[dict]:
    """Two blocks, two cache breakpoints.

    Block 1 is the persona: identical on every request forever, so it caches and stays
    cached. Block 2 is current state: changes whenever goals/tasks/summaries change,
    which is far less often than once per message, so it still earns its cache within a
    conversation.

    Note: the API silently declines to cache a prefix under ~1024 tokens. Check
    `usage.cache_read_input_tokens` on responses — if it's always 0, the persona is too
    short to cache rather than something being misconfigured.
    """
    goals = load_goals(db)
    tasks = load_open_tasks(db)
    summaries = load_recent_summaries(db)

    state = build_state_block(
        goals_block=_format_goals(goals),
        tasks_block=_format_tasks(tasks, goals),
        summaries_block=_format_summaries(summaries),
        today=date.today().isoformat(),
    )

    return [
        {
            "type": "text",
            "text": COACH_PERSONA,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": state,
            "cache_control": {"type": "ephemeral"},
        },
    ]


def transcript_for_summary(session: CheckInSession) -> str:
    import json

    turns = json.loads(session.transcript or "[]")
    speaker = {"user": "Kyle", "assistant": "Coach"}
    return "\n\n".join(f"{speaker.get(t['role'], t['role'])}: {t['content']}" for t in turns)
