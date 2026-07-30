from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from .. import speech, usage
from ..db import get_db
from ..schemas import SpeakRequest

router = APIRouter(prefix="/api", tags=["voice & usage"])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("/usage")
def usage_summary(db: SessionDep) -> dict:
    """What the coach has cost lately.

    Cost is an estimate from a hardcoded price list, not a bill — see app/usage.py.
    """
    return {
        "today": usage.summarise(db, days=1),
        "week": usage.summarise(db, days=7),
        "month": usage.summarise(db, days=30),
    }


@router.get("/voice/status")
def voice_status() -> dict:
    """Whether the human voice is available, so the UI can offer it honestly.

    With no provider configured the Settings screen says so instead of presenting a
    toggle that silently does nothing.
    """
    provider = speech.active_provider()
    return {"human_voice": provider is not None, "provider": provider}


@router.post("/speak")
def speak(req: SpeakRequest) -> Response:
    """Render text as speech.

    Returns audio bytes rather than a URL — the audio is ephemeral and nothing needs it
    twice, so there's no file to store or clean up.
    """
    try:
        audio, content_type = speech.synthesize(req.text)
    except speech.TTSUnavailable as exc:
        # 503: the client should fall back to the browser voice, not show an error.
        raise HTTPException(503, str(exc)) from exc
    except speech.TTSFailed as exc:
        raise HTTPException(502, str(exc)) from exc

    return Response(
        content=audio,
        media_type=content_type,
        headers={
            # Same reply spoken twice (a replay tap) shouldn't be billed twice.
            "Cache-Control": "private, max-age=3600",
            "ETag": hashlib.sha256(audio).hexdigest()[:32],
        },
    )
