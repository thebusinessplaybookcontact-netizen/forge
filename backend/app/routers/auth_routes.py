from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import auth
from ..config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    passcode: str = Field(min_length=1)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/status")
def status(request: Request) -> dict:
    """Lets the UI decide between showing the lock screen and going straight in."""
    return {
        "required": auth.auth_required(),
        "authenticated": not auth.auth_required()
        or auth.token_valid(request.cookies.get(auth.COOKIE_NAME)),
    }


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response) -> dict:
    if not auth.auth_required():
        return {"authenticated": True}

    who = _client(request)
    wait = auth.throttle.blocked_for(who)
    if wait:
        raise HTTPException(429, f"Too many attempts. Try again in {wait} seconds.")

    if not auth.passcode_matches(body.passcode):
        auth.throttle.record_failure(who)
        # Deliberately vague: don't confirm anything about the real passcode.
        raise HTTPException(401, "That's not it.")

    auth.throttle.clear(who)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.issue_token(),
        max_age=get_settings().session_days * 86400,
        httponly=True,  # JS can't read it, so an injected script can't steal the session
        samesite="lax",
        # Only mark Secure over HTTPS, or the cookie is silently dropped in local dev.
        secure=request.url.scheme == "https",
        path="/",
    )
    return {"authenticated": True}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"authenticated": False}
