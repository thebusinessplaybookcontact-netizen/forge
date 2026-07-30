"""Usage recording and cost estimation."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import clock, usage  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import UsageEvent  # noqa: E402

from test_tools import message, script, text  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def usage_obj(inp=1000, out=200, read=0, write=0):
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=read,
        cache_creation_input_tokens=write,
    )


# --- recording ---


def test_records_a_call(fresh_db):
    with SessionLocal() as db:
        usage.record(db, kind="chat", model="claude-sonnet-5", usage=usage_obj())
    with SessionLocal() as db:
        event = db.query(UsageEvent).one()
        assert event.input_tokens == 1000 and event.output_tokens == 200
        assert event.kind == "chat"


def test_missing_usage_is_ignored(fresh_db):
    with SessionLocal() as db:
        usage.record(db, kind="chat", model="claude-sonnet-5", usage=None)
        assert db.query(UsageEvent).count() == 0


def test_recording_never_raises(fresh_db):
    """Telemetry must not be able to break a conversation."""
    with SessionLocal() as db:
        usage.record(db, kind="chat", model="m", usage=object())  # no usage attributes
    # Absent attributes default to zero rather than exploding.
    with SessionLocal() as db:
        assert db.query(UsageEvent).count() == 1


# --- cost ---


def test_cost_uses_per_token_prices(fresh_db):
    # 1M input + 1M output on Sonnet 5 = $3 + $15
    cost = usage.estimate_cost("claude-sonnet-5", 1_000_000, 1_000_000, 0, 0)
    assert cost == pytest.approx(18.0)


def test_cache_reads_are_much_cheaper_than_input(fresh_db):
    plain = usage.estimate_cost("claude-sonnet-5", 1_000_000, 0, 0, 0)
    cached = usage.estimate_cost("claude-sonnet-5", 0, 0, 1_000_000, 0)
    assert cached == pytest.approx(plain * 0.1)


def test_cache_writes_cost_more_than_input(fresh_db):
    plain = usage.estimate_cost("claude-sonnet-5", 1_000_000, 0, 0, 0)
    written = usage.estimate_cost("claude-sonnet-5", 0, 0, 0, 1_000_000)
    assert written == pytest.approx(plain * 1.25)


def test_unknown_model_has_no_price(fresh_db):
    assert usage.estimate_cost("some-future-model", 1000, 1000, 0, 0) is None


def test_total_is_withheld_when_a_model_is_unpriced(fresh_db):
    """A partial total would understate the bill, which is worse than saying nothing."""
    with SessionLocal() as db:
        usage.record(db, kind="chat", model="claude-sonnet-5", usage=usage_obj())
        usage.record(db, kind="chat", model="mystery-model", usage=usage_obj())
        summary = usage.summarise(db, days=1)
    assert summary["estimated_cost_usd"] is None
    assert summary["calls"] == 2, "tokens are still counted"


# --- windows ---


def test_only_counts_the_window(fresh_db):
    with SessionLocal() as db:
        usage.record(db, kind="chat", model="claude-sonnet-5", usage=usage_obj())
        old = db.query(UsageEvent).one()
        old.created_at = clock.now_local() - timedelta(days=9)
        db.commit()

    with SessionLocal() as db:
        assert usage.summarise(db, days=7)["calls"] == 0
        assert usage.summarise(db, days=30)["calls"] == 1


def test_today_starts_at_local_midnight(fresh_db):
    """A call from this morning counts as today even if UTC has rolled over."""
    with SessionLocal() as db:
        usage.record(db, kind="chat", model="claude-sonnet-5", usage=usage_obj())
        event = db.query(UsageEvent).one()
        event.created_at = clock.now_local().replace(hour=0, minute=30)
        db.commit()
    with SessionLocal() as db:
        assert usage.summarise(db, days=1)["calls"] == 1


def test_cached_share_reports_how_well_caching_is_working(fresh_db):
    with SessionLocal() as db:
        usage.record(db, kind="chat", model="claude-sonnet-5", usage=usage_obj(inp=250, read=750))
        assert usage.summarise(db, days=1)["cached_share"] == pytest.approx(0.75)


# --- through the API ---


def test_a_chat_turn_is_recorded(monkeypatch, fresh_db):
    script(monkeypatch, message([text("Morning.")], "end_turn"))
    client = TestClient(app)
    assert client.post("/api/chat", json={"message": "morning"}).status_code == 200

    body = client.get("/api/usage").json()
    assert body["today"]["calls"] == 1
    assert body["today"]["input_tokens"] > 0
    assert body["today"]["estimated_cost_usd"] is not None


def test_a_tool_loop_records_every_call(monkeypatch, fresh_db):
    """Six calls in one turn should read as six, not one."""
    from test_tools import tool_use

    script(
        monkeypatch,
        message([tool_use("add_task", {"text": "a"}, "t1")], "tool_use"),
        message([tool_use("add_task", {"text": "b"}, "t2")], "tool_use"),
        message([text("Both added.")], "end_turn"),
    )
    client = TestClient(app)
    client.post("/api/chat", json={"message": "add a and b"})

    assert client.get("/api/usage").json()["today"]["calls"] == 3


def test_usage_endpoint_shape(fresh_db):
    body = TestClient(app).get("/api/usage").json()
    assert set(body) == {"today", "week", "month"}
    assert body["week"]["days"] == 7
    assert body["today"]["calls"] == 0
