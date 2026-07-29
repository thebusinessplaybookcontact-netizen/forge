"""Exercises the chat loop end to end with the Claude call stubbed out.

Verifies the parts we own: route wiring, that the system prompt carries the persona +
live goals/tasks, that cache breakpoints are set, and that turns are persisted to the
transcript. A real call against the API needs ANTHROPIC_API_KEY — see the README.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import claude_client  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CheckInSession, Goal, Horizon, Task  # noqa: E402

CAPTURED: dict = {}


def fake_chat(system_blocks, messages):
    CAPTURED["system_blocks"] = system_blocks
    CAPTURED["messages"] = messages
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="You said you'd draft chapter 3. Do that first."),
        ],
        usage=SimpleNamespace(
            input_tokens=1200,
            output_tokens=18,
            cache_creation_input_tokens=900,
            cache_read_input_tokens=0,
        ),
    )


@pytest.fixture()
def client(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        goal = Goal(
            text="Write and publish the children's book series",
            horizon=Horizon.lifetime,
            why="I want to make something a kid actually loves.",
        )
        db.add(goal)
        db.commit()
        db.add(Task(text="Draft chapter 3", linked_goal_id=goal.id))
        db.commit()

    monkeypatch.setattr(claude_client, "chat", fake_chat)
    CAPTURED.clear()
    yield TestClient(app)
    Base.metadata.drop_all(bind=engine)


def test_chat_returns_reply_and_opens_a_session(client):
    r = client.post("/api/chat", json={"message": "I don't feel like writing today"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"].startswith("You said you'd draft chapter 3")
    assert body["session_id"] > 0
    assert body["usage"]["cache_creation_input_tokens"] == 900


def test_system_prompt_carries_persona_and_live_state(client):
    client.post("/api/chat", json={"message": "hey"})
    blocks = CAPTURED["system_blocks"]

    assert len(blocks) == 2
    # Persona first (stable, cached forever), volatile state second.
    assert "You are Kyle's coach" in blocks[0]["text"]
    assert "Draft chapter 3" in blocks[1]["text"]
    assert "a kid actually loves" in blocks[1]["text"]
    # Both halves are cache breakpoints.
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in blocks)


def test_history_is_passed_but_transcript_is_not_replayed(client):
    first = client.post("/api/chat", json={"message": "morning"}).json()
    session_id = first["session_id"]

    client.post(
        "/api/chat",
        json={
            "message": "still stuck",
            "session_id": session_id,
            "history": [
                {"role": "user", "content": "morning"},
                {"role": "assistant", "content": "Morning. What's the one thing today?"},
            ],
        },
    )

    # Current-session turns ride in `messages`...
    assert [m["role"] for m in CAPTURED["messages"]] == ["user", "assistant", "user"]
    # ...and the system prompt never contains raw transcript, only recaps.
    assert "still stuck" not in CAPTURED["system_blocks"][1]["text"]

    with SessionLocal() as db:
        stored = db.get(CheckInSession, session_id)
        turns = json.loads(stored.transcript)
    assert len(turns) == 4  # two user + two assistant
