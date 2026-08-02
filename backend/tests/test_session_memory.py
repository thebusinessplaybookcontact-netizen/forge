"""The memory loop closing itself.

The gap this covers: summaries were only ever written by an endpoint nothing called,
so in real use the coach never remembered a previous conversation. These tests assert
the loop now completes on its own — a conversation goes quiet, its recap gets written,
and the next conversation sees it.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import claude_client, sessions as session_service  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.memory import build_system_blocks  # noqa: E402
from app.models import CheckInSession, Summary  # noqa: E402

from test_tools import message, script, text  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def fake_summariser(monkeypatch):
    """Stub the summarising call and record what it was asked to summarise."""
    seen: list[str] = []

    def fake(transcript: str):
        seen.append(transcript)
        return ("Kyle skipped the gym and admitted it was avoidance.", ["Do leg day Friday"])

    monkeypatch.setattr(claude_client, "summarize_session", fake)
    return seen


def make_session(*, minutes_idle: int, turns: int = 2) -> int:
    """A session whose last activity was `minutes_idle` ago."""
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_idle)
    transcript = json.dumps(
        [{"role": "user", "content": "skipped the gym"}, {"role": "assistant", "content": "Again?"}][
            :turns
        ]
    )
    with SessionLocal() as db:
        session = CheckInSession(started_at=when, last_active_at=when, transcript=transcript)
        db.add(session)
        db.commit()
        return session.id


# --- the sweep itself ---


def test_quiet_session_gets_summarised(fake_summariser):
    session_id = make_session(minutes_idle=120)

    with SessionLocal() as db:
        written = session_service.close_stale_sessions(db)

    assert len(written) == 1
    with SessionLocal() as db:
        summary = db.query(Summary).one()
        assert summary.session_id == session_id
        assert "avoidance" in summary.recap
        assert summary.commitments == "Do leg day Friday"
        assert db.get(CheckInSession, session_id).ended_at is not None


def test_recent_session_is_left_alone(fake_summariser):
    make_session(minutes_idle=5)
    with SessionLocal() as db:
        assert session_service.close_stale_sessions(db) == []
        assert db.query(Summary).count() == 0


def test_the_conversation_you_are_having_is_never_closed(fake_summariser):
    """A long pause mid-conversation must not summarise the session you just spoke to."""
    session_id = make_session(minutes_idle=120)
    with SessionLocal() as db:
        assert session_service.close_stale_sessions(db, exclude_id=session_id) == []
        assert db.get(CheckInSession, session_id).ended_at is None


def test_empty_session_is_closed_without_paying_for_a_summary(fake_summariser):
    session_id = make_session(minutes_idle=120, turns=0)

    with SessionLocal() as db:
        assert session_service.close_stale_sessions(db) == []

    assert fake_summariser == [], "should not have called the model for an empty transcript"
    with SessionLocal() as db:
        assert db.get(CheckInSession, session_id).ended_at is not None, "and not reconsider it"


def test_sweep_is_capped_per_request(fake_summariser):
    for _ in range(6):
        make_session(minutes_idle=120)

    with SessionLocal() as db:
        written = session_service.close_stale_sessions(db)

    cap = get_settings().max_sessions_closed_per_request
    assert len(written) == cap, "one message must not turn into a pile of API calls"


def test_oldest_sessions_are_closed_first(fake_summariser):
    newest = make_session(minutes_idle=60)
    oldest = make_session(minutes_idle=600)
    middle = make_session(minutes_idle=300)

    get_settings_cap = get_settings()
    saved = get_settings_cap.max_sessions_closed_per_request
    get_settings_cap.max_sessions_closed_per_request = 2
    try:
        with SessionLocal() as db:
            written = session_service.close_stale_sessions(db)
    finally:
        get_settings_cap.max_sessions_closed_per_request = saved

    assert [s.session_id for s in written] == [oldest, middle]
    with SessionLocal() as db:
        assert db.get(CheckInSession, newest).ended_at is None


def test_a_failed_summary_does_not_break_the_turn(monkeypatch):
    session_id = make_session(minutes_idle=120)

    def boom(_transcript):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr(claude_client, "summarize_session", boom)

    with SessionLocal() as db:
        assert session_service.close_stale_sessions(db) == []  # no exception escapes

    with SessionLocal() as db:
        session = db.get(CheckInSession, session_id)
        # Left open to retry, but pushed out of the stale window so it isn't reattempted
        # on every single request while the API is unhappy.
        assert session.ended_at is None
        assert session.summary is None

    with SessionLocal() as db:
        assert session_service.close_stale_sessions(db) == [], "should not retry immediately"


# --- the loop, end to end through the API ---


def test_previous_conversation_is_remembered_in_the_next_one(monkeypatch, fake_summariser):
    """The whole point: talk, go quiet, come back, and the coach knows what happened."""
    make_session(minutes_idle=120)
    client = TestClient(app)

    # Before: nothing to remember.
    with SessionLocal() as db:
        assert "first conversation" in build_system_blocks(db)[1]["text"]

    captured = script(monkeypatch, message([text("Morning.")], "end_turn"))
    r = client.post("/api/chat", json={"message": "morning"})
    assert r.status_code == 200

    # The recap was written before this turn's context was assembled, so the model saw it.
    state = captured.calls[0]["system_blocks"][1]["text"]
    assert "avoidance" in state
    assert "Do leg day Friday" in state
    assert "first conversation" not in state


def test_talking_keeps_your_own_session_alive(monkeypatch, fake_summariser):
    """Two turns far apart in one session shouldn't summarise it out from under you."""
    client = TestClient(app)

    script(monkeypatch, message([text("Hi.")], "end_turn"))
    session_id = client.post("/api/chat", json={"message": "hello"}).json()["session_id"]

    # Backdate it so it looks stale, then keep talking to it.
    with SessionLocal() as db:
        stale = datetime.now(timezone.utc) - timedelta(minutes=200)
        db.get(CheckInSession, session_id).last_active_at = stale
        db.commit()

    script(monkeypatch, message([text("Still here.")], "end_turn"))
    r = client.post("/api/chat", json={"message": "still here", "session_id": session_id})
    assert r.status_code == 200

    with SessionLocal() as db:
        session = db.get(CheckInSession, session_id)
        assert session.ended_at is None
        assert session.summary is None
        # And the turn refreshed its clock.
        assert session_service._aware(session.last_active_at) > stale


def test_a_finished_conversation_is_not_resurrected(monkeypatch, fake_summariser):
    """A phone closed overnight comes back holding a stale session id.

    That conversation has already been summarised. Appending to it would put the new
    turns after the recap was written, so they'd be said out loud and then never
    remembered — the memory loop silently losing an evening.
    """
    client = TestClient(app)
    script(monkeypatch, message([text("Hi.")], "end_turn"))
    old_id = client.post("/api/chat", json={"message": "hello"}).json()["session_id"]

    with SessionLocal() as db:
        session_service.close_session(db, db.get(CheckInSession, old_id))
        assert db.get(CheckInSession, old_id).ended_at is not None

    script(monkeypatch, message([text("Morning again.")], "end_turn"))
    new_id = client.post("/api/chat", json={"message": "morning", "session_id": old_id}).json()[
        "session_id"
    ]

    assert new_id != old_id, "a closed session must not take new turns"
    with SessionLocal() as db:
        # The old transcript is untouched, and the new turn landed somewhere summarisable.
        assert "Morning again." not in (db.get(CheckInSession, old_id).transcript or "")
        assert db.get(CheckInSession, new_id).ended_at is None


def test_turns_bump_last_active(monkeypatch, fake_summariser):
    client = TestClient(app)
    script(monkeypatch, message([text("Hi.")], "end_turn"))
    session_id = client.post("/api/chat", json={"message": "hello"}).json()["session_id"]

    with SessionLocal() as db:
        session = db.get(CheckInSession, session_id)
        age = (datetime.now(timezone.utc) - session_service._aware(session.last_active_at)).total_seconds()
    assert age < 30
