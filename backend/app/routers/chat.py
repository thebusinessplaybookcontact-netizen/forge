from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import claude_client
from ..db import get_db
from ..memory import build_system_blocks
from ..models import CheckInSession, utcnow
from ..schemas import ChatRequest, ChatResponse, ChatUsage

router = APIRouter(prefix="/api", tags=["chat"])


def _get_or_create_session(db: Session, session_id: int | None) -> CheckInSession:
    if session_id is not None:
        session = db.get(CheckInSession, session_id)
        if session is None:
            raise HTTPException(404, f"session {session_id} not found")
        return session

    session = CheckInSession()
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _record_turns(db: Session, session: CheckInSession, user_msg: str, reply: str) -> None:
    turns = json.loads(session.transcript or "[]")
    turns.append({"role": "user", "content": user_msg})
    turns.append({"role": "assistant", "content": reply})
    session.transcript = json.dumps(turns)
    db.add(session)
    db.commit()


def _to_api_messages(req: ChatRequest) -> list[dict]:
    messages = [{"role": t.role, "content": t.content} for t in req.history]
    messages.append({"role": "user", "content": req.message})
    return messages


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """One coaching turn, non-streaming. The simplest way to confirm the loop works."""
    session = _get_or_create_session(db, req.session_id)

    try:
        message = claude_client.chat(build_system_blocks(db), _to_api_messages(req))
    except claude_client.ClaudeNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc

    if message.stop_reason == "refusal":
        raise HTTPException(502, "The model declined to respond to that.")

    reply = claude_client.text_of(message)
    _record_turns(db, session, req.message, reply)

    usage = message.usage
    return ChatResponse(
        session_id=session.id,
        reply=reply,
        usage=ChatUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_input_tokens=usage.cache_read_input_tokens or 0,
        ),
    )


@router.post("/chat/stream")
def chat_stream(req: ChatRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    """Same turn, streamed as SSE so the UI can render tokens as they land."""
    session = _get_or_create_session(db, req.session_id)
    system_blocks = build_system_blocks(db)
    api_messages = _to_api_messages(req)
    session_id = session.id

    def events() -> Iterator[str]:
        yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n"

        chunks: list[str] = []
        try:
            for delta in claude_client.chat_stream(system_blocks, api_messages):
                chunks.append(delta)
                yield f"event: delta\ndata: {json.dumps({'text': delta})}\n\n"
        except claude_client.ClaudeNotConfigured as exc:
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"
            return
        except Exception as exc:  # surface upstream failures to the client, then stop
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"
            return

        reply = "".join(chunks).strip()
        # Fresh DB session: the request-scoped one may be closed by the time the
        # generator finishes streaming.
        from ..db import SessionLocal

        with SessionLocal() as write_db:
            stored = write_db.get(CheckInSession, session_id)
            if stored is not None:
                _record_turns(write_db, stored, req.message, reply)

        yield f"event: done\ndata: {json.dumps({'session_id': session_id})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/close")
def close_session(session_id: int, db: Session = Depends(get_db)) -> dict:
    """End a session and write its compact recap.

    That recap — not the transcript — is what future conversations load.
    """
    from ..memory import transcript_for_summary
    from ..models import Summary

    session = db.get(CheckInSession, session_id)
    if session is None:
        raise HTTPException(404, f"session {session_id} not found")
    if session.summary is not None:
        raise HTTPException(409, "session already summarized")

    transcript = transcript_for_summary(session)
    if not transcript.strip():
        raise HTTPException(400, "nothing to summarize")

    try:
        recap, commitments = claude_client.summarize_session(transcript)
    except claude_client.ClaudeNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc

    summary = Summary(session_id=session.id, recap=recap, commitments="\n".join(commitments))
    session.ended_at = utcnow()
    db.add_all([summary, session])
    db.commit()

    return {"session_id": session.id, "recap": recap, "commitments": commitments}
