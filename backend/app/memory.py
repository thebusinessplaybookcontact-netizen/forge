"""Assembles what the model sees.

The rule this file exists to enforce: past conversations are never replayed. Each
request carries the system prompt + structured goals/tasks + the last N session
recaps. Token use stays bounded no matter how long the app has been in use.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import clock, crud, habits
from .models import CheckInSession, Goal, Horizon, Summary, Task
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


def _format_habits(stats: list) -> str:
    """Habits with enough context for the coach to be specific rather than nagging.

    Deliberately shows consistency alongside the streak: if only the streak were here,
    a reset would look like total failure to a coach with a licence to be blunt, which
    is exactly the response that makes people quit.
    """
    if not stats:
        return "(None yet. If Kyle describes something he wants to do regularly, offer to track it.)"

    lines = []
    for s in stats:
        habit = s.habit
        if habit.cadence.value == "daily":
            cadence = "daily"
            progress = "done today" if s.done_today else "not yet today"
        else:
            cadence = f"{s.target_per_week}x per week"
            progress = f"{s.this_week} of {s.target_per_week} this week"

        bits = [f"streak {s.current_streak} {s.streak_unit}{'s' if s.current_streak != 1 else ''}"]
        bits.append(f"{round(s.completion_rate_30d * 100)}% consistent over 30 days")
        if s.longest_streak > s.current_streak:
            bits.append(f"best {s.longest_streak}")

        line = f"- [{habit.id}] {habit.text} ({cadence}) — {progress}; {', '.join(bits)}"
        if habit.why:
            line += f"\n      why: {habit.why}"
        lines.append(line)
    return "\n".join(lines)


def _format_summaries(summaries: list[Summary]) -> str:
    if not summaries:
        return "(No previous sessions. This is the first conversation.)"

    lines = []
    for s in summaries:
        # Local, so "yesterday's session" is dated the way Kyle experienced it.
        when = clock.to_local(s.created_at).date().isoformat()
        lines.append(f"### {when}")
        lines.append(s.recap)
        if s.commitments.strip():
            lines.append("Committed to:")
            for c in s.commitments.splitlines():
                if c.strip():
                    lines.append(f"- {c.strip()}")
        lines.append("")
    return "\n".join(lines).strip()


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
    goals = crud.list_goals(db, active_only=True)
    tasks = crud.list_tasks(db, open_only=True)
    summaries = crud.list_recent_summaries(db)
    habit_stats = habits.all_stats(db)

    state = build_state_block(
        goals_block=_format_goals(goals),
        tasks_block=_format_tasks(tasks, goals),
        habits_block=_format_habits(habit_stats),
        summaries_block=_format_summaries(summaries),
        today=clock.today_local().isoformat(),
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
