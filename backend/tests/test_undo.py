"""Soft delete and undo.

The property being protected: nothing in this app removes a row, so a misheard
instruction is always recoverable. These tests assert both halves — deleted rows are
invisible to normal reads, and they come back.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import claude_client, crud, tools  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Goal, Horizon, Task, UndoEntry  # noqa: E402

from test_tools import message, script, text, tool_use  # noqa: E402


@pytest.fixture()
def seeded():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        goal = Goal(text="Fitness", horizon=Horizon.lifetime, why="I owe it to myself.")
        db.add(goal)
        db.commit()
        keep = Task(text="Workout", linked_goal_id=goal.id)
        doomed = Task(text="Call the accountant")
        db.add_all([keep, doomed])
        db.commit()
        ids = {"goal": goal.id, "keep": keep.id, "doomed": doomed.id}
    yield ids
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(seeded):
    return TestClient(app)


# --- the core property ---


def test_deleted_task_is_hidden_but_recoverable(seeded):
    with SessionLocal() as db:
        task, undo = crud.delete_task(db, seeded["doomed"])
        assert task.deleted_at is not None

    with SessionLocal() as db:
        # Excluded from normal reads...
        assert [t.id for t in crud.list_tasks(db)] == [seeded["keep"]]
        assert [t.id for t in crud.list_tasks(db, open_only=True)] == [seeded["keep"]]
        with pytest.raises(crud.NotFound):
            crud.get_task(db, seeded["doomed"])
        # ...but the row is still there if you ask for it.
        assert crud.get_task(db, seeded["doomed"], include_deleted=True).text == "Call the accountant"
        # And it never left the table.
        assert db.get(Task, seeded["doomed"]) is not None

    with SessionLocal() as db:
        crud.apply_undo(db, undo.id)

    with SessionLocal() as db:
        assert seeded["doomed"] in [t.id for t in crud.list_tasks(db)]
        assert crud.get_task(db, seeded["doomed"]).deleted_at is None


def test_deleted_goal_is_hidden_but_recoverable(seeded):
    with SessionLocal() as db:
        _, undo = crud.delete_goal(db, seeded["goal"])

    with SessionLocal() as db:
        assert crud.list_goals(db) == []
        with pytest.raises(crud.NotFound):
            crud.get_goal(db, seeded["goal"])
        assert db.get(Goal, seeded["goal"]) is not None

    with SessionLocal() as db:
        crud.apply_undo(db, undo.id)

    with SessionLocal() as db:
        assert [g.id for g in crud.list_goals(db)] == [seeded["goal"]]


def test_deleted_goal_is_gone_from_the_prompt_state(seeded):
    """A deleted goal must not keep showing up in what the model sees."""
    from app.memory import build_system_blocks

    with SessionLocal() as db:
        assert "Fitness" in build_system_blocks(db)[1]["text"]
        crud.delete_goal(db, seeded["goal"])

    with SessionLocal() as db:
        assert "Fitness" not in build_system_blocks(db)[1]["text"]


def test_undo_restores_only_the_most_recent_delete(seeded):
    with SessionLocal() as db:
        crud.delete_task(db, seeded["keep"])
        crud.delete_task(db, seeded["doomed"])

    with SessionLocal() as db:
        entry = crud.apply_undo(db)  # no id: the latest
        assert entry.target_id == seeded["doomed"]

    with SessionLocal() as db:
        visible = [t.id for t in crud.list_tasks(db)]
        assert visible == [seeded["doomed"]], "the earlier delete should still stand"


def test_undo_is_not_reusable(seeded):
    with SessionLocal() as db:
        _, undo = crud.delete_task(db, seeded["doomed"])
    with SessionLocal() as db:
        crud.apply_undo(db, undo.id)
    with SessionLocal() as db:
        with pytest.raises(crud.NotFound, match="already undone"):
            crud.apply_undo(db, undo.id)


def test_undo_outside_the_window_is_refused(seeded):
    with SessionLocal() as db:
        _, undo = crud.delete_task(db, seeded["doomed"])
        undo_id = undo.id

    # Age the entry past the window.
    window = crud.get_settings().undo_window_seconds
    with SessionLocal() as db:
        entry = db.get(UndoEntry, undo_id)
        entry.created_at = entry.created_at - timedelta(seconds=window + 60)
        db.commit()

    with SessionLocal() as db:
        with pytest.raises(crud.UndoExpired):
            crud.apply_undo(db, undo_id)
        # Still soft-deleted, still not destroyed — recoverable by hand.
        assert crud.get_task(db, seeded["doomed"], include_deleted=True) is not None


def test_nothing_to_undo(seeded):
    with SessionLocal() as db:
        with pytest.raises(crud.NotFound, match="nothing to undo"):
            crud.apply_undo(db)


def test_latest_undoable_ignores_expired_and_used_entries(seeded):
    with SessionLocal() as db:
        assert crud.latest_undoable(db) is None
        _, undo = crud.delete_task(db, seeded["doomed"])
    with SessionLocal() as db:
        assert crud.latest_undoable(db).id == undo.id
        crud.apply_undo(db, undo.id)
    with SessionLocal() as db:
        assert crud.latest_undoable(db) is None


# --- through the HTTP surface ---


def test_http_delete_is_soft_and_returns_an_undo_id(client, seeded):
    r = client.delete(f"/api/tasks/{seeded['doomed']}")
    assert r.status_code == 200
    undo_id = r.json()["undo_id"]

    listed = [t["id"] for t in client.get("/api/tasks").json()]
    assert seeded["doomed"] not in listed

    r = client.post(f"/api/undo/{undo_id}")
    assert r.status_code == 200
    assert r.json()["restored"]["label"] == "Call the accountant"

    listed = [t["id"] for t in client.get("/api/tasks").json()]
    assert seeded["doomed"] in listed


def test_http_undo_with_no_history_is_404(client, seeded):
    assert client.post("/api/undo").status_code == 404


def test_http_undo_outside_window_is_410(client, seeded):
    undo_id = client.delete(f"/api/tasks/{seeded['doomed']}").json()["undo_id"]
    window = crud.get_settings().undo_window_seconds
    with SessionLocal() as db:
        entry = db.get(UndoEntry, undo_id)
        entry.created_at = entry.created_at - timedelta(seconds=window + 60)
        db.commit()
    r = client.post(f"/api/undo/{undo_id}")
    assert r.status_code == 410


# --- through the coach, by voice ---


def test_coach_can_undo_a_delete_it_just_made(client, monkeypatch, seeded):
    """The two-turn shape: 'drop that' then 'no wait, undo'."""
    script(
        monkeypatch,
        message([tool_use("delete_task", {"task_id": seeded["doomed"]})], "tool_use"),
        message([text("Dropped it.")], "end_turn"),
    )
    first = client.post("/api/chat", json={"message": "drop the accountant task"}).json()
    assert first["actions"][0]["undo_id"] is not None
    with SessionLocal() as db:
        assert seeded["doomed"] not in [t.id for t in crud.list_tasks(db)]

    script(
        monkeypatch,
        message([tool_use("undo_last", {})], "tool_use"),
        message([text("Put it back.")], "end_turn"),
    )
    second = client.post("/api/chat", json={"message": "no wait, undo that"}).json()

    assert second["actions"][0]["name"] == "undo_last"
    assert second["actions"][0]["ok"] is True
    assert "Call the accountant" in second["actions"][0]["summary"]
    with SessionLocal() as db:
        assert seeded["doomed"] in [t.id for t in crud.list_tasks(db)]


def test_undo_tool_with_nothing_to_undo_returns_a_clean_error(client, monkeypatch, seeded):
    model = script(
        monkeypatch,
        message([tool_use("undo_last", {})], "tool_use"),
        message([text("Nothing to take back.")], "end_turn"),
    )
    body = client.post("/api/chat", json={"message": "undo"}).json()

    results = model.calls[1]["messages"][-1]["content"]
    assert results[0]["is_error"] is True
    assert "nothing to undo" in results[0]["content"].lower()
    assert body["actions"][0]["ok"] is False


def test_deleting_a_missing_task_still_errors_cleanly(seeded):
    with SessionLocal() as db:
        outcome = tools.execute(db, "delete_task", {"task_id": 4242})
    assert outcome.ok is False
    assert "No task with id 4242" in outcome.message


def test_deleting_an_already_deleted_task_errors(seeded):
    with SessionLocal() as db:
        crud.delete_task(db, seeded["doomed"])
    with SessionLocal() as db:
        outcome = tools.execute(db, "delete_task", {"task_id": seeded["doomed"]})
    assert outcome.ok is False, "a soft-deleted task should look absent, not be re-deletable"


# Keep the imported fixtures/helpers referenced so linters don't flag them.
_ = (SimpleNamespace, claude_client)
