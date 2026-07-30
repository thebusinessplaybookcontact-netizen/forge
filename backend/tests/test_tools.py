"""Tool use, end to end with the API mocked.

`claude_client.complete` is the only thing stubbed. The agent loop, argument
validation, the tool dispatch, and the SQLAlchemy writes are all real, so each test
asserts on the actual database afterwards.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import claude_client, crud, tools  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Goal, GoalStatus, Horizon, Task, TaskStatus  # noqa: E402


# --- fake model responses ---


def tool_use(name: str, tool_input: dict, tool_id: str = "toolu_1"):
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


def text(body: str):
    return SimpleNamespace(type="text", text=body)


def message(content: list, stop_reason: str):
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=10,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
    )


class ScriptedModel:
    """Replays a fixed list of responses and records what it was sent."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, system_blocks, messages, tool_defs=None):
        self.calls.append(
            {"system_blocks": system_blocks, "messages": messages, "tools": tool_defs}
        )
        if not self.responses:
            raise AssertionError("model called more times than the script allows")
        return self.responses.pop(0)


def script(monkeypatch, *responses) -> ScriptedModel:
    model = ScriptedModel(*responses)
    monkeypatch.setattr(claude_client, "complete", model)
    return model


# --- fixtures ---


@pytest.fixture()
def seeded():
    """A goal and two open tasks. Returns their ids."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        goal = Goal(text="Fitness and body recomposition", horizon=Horizon.lifetime, why="I owe it to myself.")
        db.add(goal)
        db.commit()
        workout = Task(text="Workout", linked_goal_id=goal.id)
        accountant = Task(text="Call the accountant")
        db.add_all([workout, accountant])
        db.commit()
        ids = {"goal": goal.id, "workout": workout.id, "accountant": accountant.id}
    yield ids
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(seeded):
    return TestClient(app)


def say(client, text_in: str):
    r = client.post("/api/chat", json={"message": text_in})
    assert r.status_code == 200, r.text
    return r.json()


# --- one test per tool, asserting the real DB change ---


def test_add_task(client, monkeypatch, seeded):
    script(
        monkeypatch,
        message([tool_use("add_task", {"text": "Call the accountant", "due": "2026-08-03"})], "tool_use"),
        message([text("Added it.")], "end_turn"),
    )

    body = say(client, "add call the accountant for monday")

    with SessionLocal() as db:
        task = db.query(Task).filter(Task.text == "Call the accountant", Task.due.isnot(None)).one()
        assert task.due.isoformat() == "2026-08-03"
        assert task.status is TaskStatus.open

    assert body["actions"][0]["name"] == "add_task"
    assert body["actions"][0]["ok"] is True


def test_add_task_linked_to_goal(client, monkeypatch, seeded):
    script(
        monkeypatch,
        message([tool_use("add_task", {"text": "Leg day", "linked_goal_id": seeded["goal"]})], "tool_use"),
        message([text("On the list.")], "end_turn"),
    )

    say(client, "add leg day")

    with SessionLocal() as db:
        task = db.query(Task).filter(Task.text == "Leg day").one()
        assert task.linked_goal_id == seeded["goal"]


def test_complete_task(client, monkeypatch, seeded):
    script(
        monkeypatch,
        message([tool_use("complete_task", {"task_id": seeded["workout"]})], "tool_use"),
        message([text("Good. That's the one that counts.")], "end_turn"),
    )

    say(client, "did the workout")

    with SessionLocal() as db:
        assert db.get(Task, seeded["workout"]).status is TaskStatus.done


def test_update_task(client, monkeypatch, seeded):
    script(
        monkeypatch,
        message(
            [tool_use("update_task", {"task_id": seeded["accountant"], "text": "Call the CPA", "due": "2026-09-01"})],
            "tool_use",
        ),
        message([text("Moved.")], "end_turn"),
    )

    say(client, "reword that and push it to september")

    with SessionLocal() as db:
        task = db.get(Task, seeded["accountant"])
        assert task.text == "Call the CPA"
        assert task.due.isoformat() == "2026-09-01"
        assert task.status is TaskStatus.open  # untouched fields stay put


def test_update_task_can_clear_the_due_date(client, monkeypatch, seeded):
    with SessionLocal() as db:
        from datetime import date

        db.get(Task, seeded["accountant"]).due = date(2026, 8, 1)
        db.commit()

    script(
        monkeypatch,
        message([tool_use("update_task", {"task_id": seeded["accountant"], "due": None})], "tool_use"),
        message([text("No deadline now.")], "end_turn"),
    )

    say(client, "drop the deadline")

    with SessionLocal() as db:
        assert db.get(Task, seeded["accountant"]).due is None


def test_delete_task(client, monkeypatch, seeded):
    script(
        monkeypatch,
        message([tool_use("delete_task", {"task_id": seeded["accountant"]})], "tool_use"),
        message([text("Gone.")], "end_turn"),
    )

    body = say(client, "that one doesn't matter, drop it")

    with SessionLocal() as db:
        # Soft delete: the row survives, reads stop seeing it.
        row = db.get(Task, seeded["accountant"])
        assert row is not None and row.deleted_at is not None
        assert seeded["accountant"] not in [t.id for t in crud.list_tasks(db)]

    # The action note carries an undo handle.
    assert body["actions"][0]["undo_id"] is not None


def test_delete_goal(client, monkeypatch, seeded):
    script(
        monkeypatch,
        message([tool_use("delete_goal", {"goal_id": seeded["goal"]})], "tool_use"),
        message([text("Dropped.")], "end_turn"),
    )

    body = say(client, "drop the fitness goal, it was a mistake")

    with SessionLocal() as db:
        row = db.get(Goal, seeded["goal"])
        assert row is not None and row.deleted_at is not None
        assert crud.list_goals(db) == []
        # Linked tasks keep their link so an undo restores the goal completely.
        assert db.get(Task, seeded["workout"]).linked_goal_id == seeded["goal"]

    assert body["actions"][0]["undo_id"] is not None


def test_add_goal(client, monkeypatch):
    script(
        monkeypatch,
        message(
            [
                tool_use(
                    "add_goal",
                    {
                        "text": "Ship the book series",
                        "horizon": "lifetime",
                        "why": "I want to make something a kid loves.",
                    },
                )
            ],
            "tool_use",
        ),
        message([text("That's the ship you're building.")], "end_turn"),
    )

    say(client, "new goal: ship the book series")

    with SessionLocal() as db:
        goal = db.query(Goal).filter(Goal.text == "Ship the book series").one()
        assert goal.horizon is Horizon.lifetime
        assert "kid loves" in goal.why


def test_update_goal(client, monkeypatch, seeded):
    script(
        monkeypatch,
        message(
            [tool_use("update_goal", {"goal_id": seeded["goal"], "why": "Best shape of my life.", "status": "active"})],
            "tool_use",
        ),
        message([text("Noted.")], "end_turn"),
    )

    say(client, "change the why on fitness")

    with SessionLocal() as db:
        goal = db.get(Goal, seeded["goal"])
        assert goal.why == "Best shape of my life."
        assert goal.status is GoalStatus.active
        assert goal.text == "Fitness and body recomposition"  # untouched


# --- the loop itself ---


def test_chains_several_calls_in_one_turn(client, monkeypatch, seeded):
    """Two tool_use blocks in one response: both run, both results go back together."""
    model = script(
        monkeypatch,
        message(
            [
                tool_use("complete_task", {"task_id": seeded["workout"]}, "toolu_a"),
                tool_use("add_task", {"text": "Book a massage"}, "toolu_b"),
            ],
            "tool_use",
        ),
        message([text("Done and added.")], "end_turn"),
    )

    body = say(client, "did the workout, and remind me to book a massage")

    with SessionLocal() as db:
        assert db.get(Task, seeded["workout"]).status is TaskStatus.done
        assert db.query(Task).filter(Task.text == "Book a massage").count() == 1

    assert [a["name"] for a in body["actions"]] == ["complete_task", "add_task"]

    # Both tool_results must ride in a SINGLE user message, one per tool_use id.
    follow_up = model.calls[1]["messages"]
    results = follow_up[-1]
    assert results["role"] == "user"
    assert [b["tool_use_id"] for b in results["content"]] == ["toolu_a", "toolu_b"]
    assert all(b["type"] == "tool_result" for b in results["content"])


def test_sequential_tool_rounds(client, monkeypatch, seeded):
    """The model may need several round trips; the loop keeps going."""
    script(
        monkeypatch,
        message([tool_use("add_goal", {"text": "Read more", "horizon": "weekly"}, "t1")], "tool_use"),
        message([tool_use("add_task", {"text": "Pick a book"}, "t2")], "tool_use"),
        message([text("Set up.")], "end_turn"),
    )

    body = say(client, "I want to read more")

    with SessionLocal() as db:
        assert db.query(Goal).filter(Goal.text == "Read more").count() == 1
        assert db.query(Task).filter(Task.text == "Pick a book").count() == 1
    assert len(body["actions"]) == 2


def test_tools_are_sent_on_every_request(client, monkeypatch, seeded):
    model = script(monkeypatch, message([text("Morning.")], "end_turn"))
    say(client, "morning")

    sent = model.calls[0]["tools"]
    assert [t["name"] for t in sent] == [
        "add_task",
        "complete_task",
        "update_task",
        "delete_task",
        "add_goal",
        "update_goal",
        "delete_goal",
        "add_habit",
        "log_habit",
        "unlog_habit",
        "undo_last",
    ], "tool order must stay stable — reordering invalidates the prompt cache"
    assert all("input_schema" in t and t["description"] for t in sent)


# --- failure modes come back as readable tool_results, not crashes ---


def test_missing_task_id_returns_a_clean_error(client, monkeypatch, seeded):
    model = script(
        monkeypatch,
        message([tool_use("complete_task", {"task_id": 9999})], "tool_use"),
        message([text("I couldn't find that one.")], "end_turn"),
    )

    body = say(client, "mark task 9999 done")

    results = model.calls[1]["messages"][-1]["content"]
    assert results[0]["is_error"] is True
    assert "No task with id 9999" in results[0]["content"]
    assert body["actions"][0]["ok"] is False
    assert body["reply"] == "I couldn't find that one."


def test_bad_arguments_return_a_clean_error(client, monkeypatch, seeded):
    model = script(
        monkeypatch,
        message([tool_use("add_task", {"text": "Nope", "due": "next tuesday"})], "tool_use"),
        message([text("Give me a real date.")], "end_turn"),
    )

    say(client, "add something for next tuesday")

    results = model.calls[1]["messages"][-1]["content"]
    assert results[0]["is_error"] is True
    assert "due" in results[0]["content"]
    with SessionLocal() as db:
        assert db.query(Task).filter(Task.text == "Nope").count() == 0, "nothing should be written"


def test_linking_to_a_missing_goal_is_rejected(client, monkeypatch, seeded):
    model = script(
        monkeypatch,
        message([tool_use("add_task", {"text": "Orphan", "linked_goal_id": 4242})], "tool_use"),
        message([text("That goal doesn't exist.")], "end_turn"),
    )

    say(client, "add orphan under goal 4242")

    assert model.calls[1]["messages"][-1]["content"][0]["is_error"] is True
    with SessionLocal() as db:
        assert db.query(Task).filter(Task.text == "Orphan").count() == 0


def test_unknown_tool_name_is_rejected(seeded):
    with SessionLocal() as db:
        outcome = tools.execute(db, "drop_database", {})
    assert outcome.ok is False
    assert "Unknown tool" in outcome.message


def test_update_with_no_fields_is_rejected(seeded):
    with SessionLocal() as db:
        outcome = tools.execute(db, "update_task", {"task_id": seeded["workout"]})
    assert outcome.ok is False
    assert "at least one field" in outcome.message


def test_hallucinated_argument_is_rejected(seeded):
    with SessionLocal() as db:
        outcome = tools.execute(db, "add_task", {"text": "x", "priority": "urgent"})
    assert outcome.ok is False
    assert "priority" in outcome.message
    with SessionLocal() as db:
        assert db.query(Task).filter(Task.text == "x").count() == 0


def test_runaway_tool_loop_is_capped(client, monkeypatch, seeded):
    """A model that never stops asking for tools must not loop forever."""
    attempts = 20
    forever = [
        message([tool_use("add_task", {"text": f"loop {i}"}, f"t{i}")], "tool_use")
        for i in range(attempts)
    ]
    model = script(monkeypatch, *forever)

    body = say(client, "go")

    from app.agent import MAX_TOOL_ITERATIONS

    assert len(model.calls) == MAX_TOOL_ITERATIONS < attempts
    assert len(body["actions"]) == MAX_TOOL_ITERATIONS
