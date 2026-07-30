from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import agent, claude_client, sessions as session_service
from ..db import get_db
from ..memory import build_system_blocks
from ..models import CheckInSession, utcnow
from ..schemas import ChatRequest, ChatResponse, ChatUsage, ToolAction

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
    # Idleness is what marks a conversation finished, so this timestamp is what decides
    # when the recap gets written.
    session.last_active_at = utcnow()
    db.add(session)
    db.commit()


def _prepare_context(db: Session, current_session_id: int) -> list[dict]:
    """Write recaps for finished conversations, then assemble this turn's context.

    Order matters: a session that went quiet an hour ago is summarised *before* the
    system prompt is built, so its recap is in front of the model for this very turn.
    """
    session_service.close_stale_sessions(db, exclude_id=current_session_id)
    return build_system_blocks(db)


def _to_api_messages(req: ChatRequest) -> list[dict]:
    messages = [{"role": t.role, "content": t.content} for t in req.history]
    messages.append({"role": "user", "content": req.message})
    return messages


def _actions_out(outcomes) -> list[ToolAction]:
    return [
        ToolAction(
            name=o.name,
            ok=o.ok,
            summary=o.summary or o.message,
            entity=o.entity,
            undo_id=o.undo_id,
        )
        for o in outcomes
    ]


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """One coaching turn, non-streaming.

    Runs the full tool loop, so the reply comes back after any to-do list changes have
    already been committed.
    """
    session = _get_or_create_session(db, req.session_id)

    try:
        result = agent.run_turn(db, _prepare_context(db, session.id), _to_api_messages(req))
    except agent.ModelRefused as exc:
        raise HTTPException(502, str(exc)) from exc

    _record_turns(db, session, req.message, result.reply)

    usage = result.usage
    return ChatResponse(
        session_id=session.id,
        reply=result.reply,
        actions=_actions_out(result.actions),
        usage=(
            ChatUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
                cache_read_input_tokens=usage.cache_read_input_tokens or 0,
            )
            if usage is not None
            else None
        ),
    )


@router.post("/chat/stream")
def chat_stream(req: ChatRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    """Same turn, streamed as SSE.

    Emits `delta` events for text and `action` events whenever a tool changes something,
    so the UI can show the to-do list updating mid-reply.
    """
    session = _get_or_create_session(db, req.session_id)
    system_blocks = _prepare_context(db, session.id)
    api_messages = _to_api_messages(req)
    session_id = session.id

    def sse(event: str, payload: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

    def events() -> Iterator[str]:
        yield sse("session", {"session_id": session_id})

        reply = ""
        # Tools commit as they run, so this generator needs its own DB session — the
        # request-scoped one can be closed before streaming finishes.
        from ..db import SessionLocal

        try:
            with SessionLocal() as work_db:
                for item in agent.stream_turn(work_db, system_blocks, api_messages):
                    if isinstance(item, agent.Delta):
                        yield sse("delta", {"text": item.text})
                    elif isinstance(item, agent.Action):
                        o = item.outcome
                        yield sse(
                            "action",
                            {
                                "name": o.name,
                                "ok": o.ok,
                                "summary": o.summary or o.message,
                                "entity": o.entity,
                                "undo_id": o.undo_id,
                            },
                        )
                    else:  # Final
                        reply = item.reply
        except claude_client.ClaudeNotConfigured as exc:
            yield sse("error", {"message": str(exc)})
            return
        except Exception as exc:  # surface upstream failures, then stop cleanly
            yield sse("error", {"message": str(exc)})
            return

        with SessionLocal() as write_db:
            stored = write_db.get(CheckInSession, session_id)
            if stored is not None:
                _record_turns(write_db, stored, req.message, reply)

        yield sse("done", {"session_id": session_id})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/close")
def close_session(session_id: int, db: Session = Depends(get_db)) -> dict:
    """End a session now and write its recap, rather than waiting for it to go idle.

    Same code path the idle sweep uses — this just skips the waiting.
    """
    session = db.get(CheckInSession, session_id)
    if session is None:
        raise HTTPException(404, f"session {session_id} not found")
    if session.summary is not None:
        raise HTTPException(409, "session already summarized")

    summary = session_service.close_session(db, session)
    if summary is None:
        raise HTTPException(400, "nothing to summarize")

    return {
        "session_id": session.id,
        "recap": summary.recap,
        "commitments": [c for c in summary.commitments.splitlines() if c.strip()],
    }
