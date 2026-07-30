"""Passcode auth for a single-user app.

This is not a user system. There's one person, one passcode, and the only job is
stopping a stranger who finds the URL from reading Kyle's goals or spending his Claude
credits. Anything more (accounts, OAuth, password reset) would be machinery without a
purpose.

Design notes:

* The signing key is derived from the passcode, so changing the passcode invalidates
  every existing session for free — no second secret to manage or rotate.
* Tokens are stateless and signed, so there's no session table and restarts don't log
  you out. The tradeoff is no server-side revocation; changing the passcode is the
  revoke button.
* With no passcode set, auth is off. That keeps local dev frictionless, and startup logs
  a warning so an unprotected deploy is loud rather than silent.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass, field

from .config import get_settings

COOKIE_NAME = "coach_session"


def auth_required() -> bool:
    return bool(get_settings().passcode)


def _key() -> bytes:
    return hashlib.sha256(get_settings().passcode.encode()).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token() -> str:
    """A signed 'valid until' stamp. That's the whole session."""
    expires = int(time.time()) + get_settings().session_days * 86400
    payload = _b64(str(expires).encode())
    signature = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def token_valid(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload, _, signature = token.partition(".")

    expected = hmac.new(_key(), payload.encode(), hashlib.sha256).digest()
    try:
        given = _unb64(signature)
    except Exception:
        return False
    # compare_digest, not ==, so a wrong signature can't be found byte by byte.
    if not hmac.compare_digest(expected, given):
        return False

    try:
        return int(_unb64(payload).decode()) > time.time()
    except Exception:
        return False


def passcode_matches(attempt: str) -> bool:
    return hmac.compare_digest(attempt.encode(), get_settings().passcode.encode())


@dataclass
class Throttle:
    """Slows down guessing.

    A short passcode is brute-forceable in seconds over HTTP, so failures per client
    are capped. In-memory on purpose: one process, one user, and a restart clearing it
    is not a meaningful bypass when the lockout is measured in minutes.
    """

    max_attempts: int = 5
    window_seconds: int = 300
    _failures: dict[str, list[float]] = field(default_factory=dict)

    def _recent(self, who: str) -> list[float]:
        cutoff = time.time() - self.window_seconds
        recent = [t for t in self._failures.get(who, []) if t > cutoff]
        self._failures[who] = recent
        return recent

    def blocked_for(self, who: str) -> int:
        """Seconds until this client may try again; 0 if it may try now."""
        recent = self._recent(who)
        if len(recent) < self.max_attempts:
            return 0
        return max(1, int(self.window_seconds - (time.time() - recent[0])))

    def record_failure(self, who: str) -> None:
        self._failures.setdefault(who, []).append(time.time())

    def clear(self, who: str) -> None:
        self._failures.pop(who, None)


throttle = Throttle()
