"""Passcode auth.

The property under test: with a passcode set, no API route that touches data can be
reached without a valid session — and the ways people usually get this wrong (forged
tokens, expired tokens, brute force, a new router forgetting the dependency) are all
covered explicitly.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import OPEN_PATHS, app  # noqa: E402

PASSCODE = "let-me-in-1234"


@pytest.fixture()
def locked():
    """App with a passcode set."""
    Base.metadata.create_all(bind=engine)
    s = get_settings()
    saved = s.passcode
    s.passcode = PASSCODE
    auth.throttle._failures.clear()
    yield TestClient(app)
    s.passcode = saved
    auth.throttle._failures.clear()


@pytest.fixture()
def open_app():
    """App with no passcode — local dev."""
    Base.metadata.create_all(bind=engine)
    s = get_settings()
    saved = s.passcode
    s.passcode = ""
    yield TestClient(app)
    s.passcode = saved


# --- open mode stays frictionless ---


def test_no_passcode_means_no_lock(open_app):
    assert open_app.get("/api/dashboard").status_code == 200
    assert open_app.get("/api/auth/status").json() == {"required": False, "authenticated": True}


def test_health_reports_when_auth_is_off(open_app):
    assert open_app.get("/api/health").json()["auth"] == "off"


# --- locked mode ---


def test_data_routes_are_locked(locked):
    for path in ("/api/dashboard", "/api/goals", "/api/tasks"):
        assert locked.get(path).status_code == 401, path
    assert locked.post("/api/chat", json={"message": "hi"}).status_code == 401
    assert locked.post("/api/speak", json={"text": "hi"}).status_code == 401
    assert locked.post("/api/undo").status_code == 401
    assert locked.delete("/api/tasks/1").status_code == 401


def test_health_stays_open_for_platform_healthchecks(locked):
    r = locked.get("/api/health")
    assert r.status_code == 200
    assert r.json()["auth"] == "on"


def test_login_then_access(locked):
    assert locked.post("/api/auth/login", json={"passcode": PASSCODE}).status_code == 200
    # TestClient keeps the cookie, like a browser.
    assert locked.get("/api/dashboard").status_code == 200
    assert locked.get("/api/auth/status").json() == {"required": True, "authenticated": True}


def test_wrong_passcode_is_rejected(locked):
    assert locked.post("/api/auth/login", json={"passcode": "nope"}).status_code == 401
    assert locked.get("/api/dashboard").status_code == 401


def test_logout_ends_the_session(locked):
    locked.post("/api/auth/login", json={"passcode": PASSCODE})
    assert locked.get("/api/dashboard").status_code == 200
    locked.post("/api/auth/logout")
    assert locked.get("/api/dashboard").status_code == 401


def test_cookie_is_httponly(locked):
    r = locked.post("/api/auth/login", json={"passcode": PASSCODE})
    assert "httponly" in r.headers["set-cookie"].lower()


# --- token integrity ---


def test_forged_token_is_rejected(locked):
    locked.cookies.set(auth.COOKIE_NAME, "bogus.token")
    assert locked.get("/api/dashboard").status_code == 401


def test_token_with_tampered_expiry_is_rejected(locked):
    """Extending your own session must fail the signature check."""
    token = auth.issue_token()
    _, _, signature = token.partition(".")
    forged_payload = auth._b64(str(int(time.time()) + 999_999).encode())
    locked.cookies.set(auth.COOKIE_NAME, f"{forged_payload}.{signature}")
    assert locked.get("/api/dashboard").status_code == 401


def test_expired_token_is_rejected(locked, monkeypatch):
    monkeypatch.setattr(get_settings(), "session_days", 0)
    token = auth.issue_token()
    time.sleep(0.01)
    assert auth.token_valid(token) is False


def test_changing_the_passcode_invalidates_existing_sessions(locked):
    locked.post("/api/auth/login", json={"passcode": PASSCODE})
    assert locked.get("/api/dashboard").status_code == 200
    get_settings().passcode = "a-different-passcode"
    assert locked.get("/api/dashboard").status_code == 401


# --- brute force ---


def test_repeated_failures_are_throttled(locked):
    for _ in range(auth.throttle.max_attempts):
        assert locked.post("/api/auth/login", json={"passcode": "wrong"}).status_code == 401

    r = locked.post("/api/auth/login", json={"passcode": "wrong"})
    assert r.status_code == 429
    # Even the correct passcode waits out the lockout.
    assert locked.post("/api/auth/login", json={"passcode": PASSCODE}).status_code == 429


def test_a_successful_login_clears_the_failure_count(locked):
    for _ in range(auth.throttle.max_attempts - 1):
        locked.post("/api/auth/login", json={"passcode": "wrong"})
    assert locked.post("/api/auth/login", json={"passcode": PASSCODE}).status_code == 200
    assert auth.throttle.blocked_for("testclient") == 0


# --- the failure mode that matters most ---


def test_every_api_route_is_closed_by_default(locked):
    """A new router must not be able to ship unprotected by forgetting a dependency.

    Walks the real route table rather than a hand-written list, so a route added later
    is covered by this test the day it appears.
    """
    checked = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if not path.startswith("/api/") or path in OPEN_PATHS:
            continue
        if "{" in path:  # give path params something concrete
            concrete = path.replace("{session_id}", "1").replace("{goal_id}", "1")
            concrete = concrete.replace("{task_id}", "1").replace("{undo_id}", "1")
        else:
            concrete = path

        method = "GET" if "GET" in methods else next(iter(methods - {"HEAD", "OPTIONS"}), None)
        if method is None:
            continue
        r = locked.request(method, concrete, json={})
        assert r.status_code == 401, f"{method} {concrete} returned {r.status_code}, expected 401"
        checked += 1

    assert checked >= 8, f"only checked {checked} routes — the walk probably broke"
