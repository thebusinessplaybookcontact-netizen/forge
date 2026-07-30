"""Closing out conversations and writing their recaps.

This is the half of the memory design that had no trigger. The endpoint to summarise a
session existed and worked, but nothing ever called it — so summaries were never
written, and the coach's "Recent sessions" block permanently read "this is the first
conversation". Goals and tasks carried across sessions because they're structured data;
everything else was forgotten.

There's no "end conversation" button to hang this off, and there shouldn't be — you put
the phone down mid-thought. So the signal is idleness: a session that has been quiet
long enough is over, and gets summarised on the next request that comes along.

Doing it lazily rather than on a scheduler means no background worker to run or monitor,
and it happens at exactly the moment the recap is needed — just before the next
conversation's context is assembled.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import claude_client
from .config import get_settings
from .memory import transcript_for_summary
from .models import CheckInSession, Summary, utcnow

log = logging.getLogger("coach")


def _aware(moment: datetime) -> datetime:
    """SQLite returns naive datetimes even from a timezone=True column."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def close_session(db: Session, session: CheckInSession) -> Summary | None:
    """End a session and write its recap. Returns None if there was nothing to say."""
    if session.summary is not None:
        return session.summary

    transcript = transcript_for_summary(session)
    if not transcript.strip():
        # Opened but never used — close it quietly rather than paying for a summary of
        # nothing, and don't leave it to be reconsidered on every future request.
        session.ended_at = utcnow()
        db.commit()
        return None

    recap, commitments = claude_client.summarize_session(transcript)
    summary = Summary(session_id=session.id, recap=recap, commitments="\n".join(commitments))
    session.ended_at = utcnow()
    db.add_all([summary, session])
    db.commit()
    db.refresh(summary)
    return summary


def close_stale_sessions(db: Session, *, exclude_id: int | None = None) -> list[Summary]:
    """Summarise conversations that have gone quiet.

    Called before assembling the next turn's context, so a recap written here is
    available to the conversation that triggered it.
    """
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.session_idle_minutes)

    # coalesce because rows created before last_active_at existed have it as NULL, and
    # NULL comparisons would silently exclude exactly the oldest sessions.
    last_active = func.coalesce(CheckInSession.last_active_at, CheckInSession.started_at)

    stmt = (
        select(CheckInSession)
        .where(CheckInSession.ended_at.is_(None), last_active < cutoff)
        .order_by(last_active)
        .limit(settings.max_sessions_closed_per_request)
    )
    if exclude_id is not None:
        stmt = stmt.where(CheckInSession.id != exclude_id)

    written: list[Summary] = []
    for session in db.scalars(stmt).all():
        try:
            summary = close_session(db, session)
        except Exception:
            # Never let a failed summary break the conversation the user is having.
            # Pushing last_active_at forward retries after another idle window instead
            # of re-attempting on every single request while the API is unhappy.
            log.exception("Could not summarise session %s; will retry later", session.id)
            db.rollback()
            session.last_active_at = utcnow()
            db.commit()
            continue
        if summary is not None:
            written.append(summary)

    return written
