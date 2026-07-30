import logging
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .claude_client import ClaudeNotConfigured
from .config import get_settings
from .db import init_db
from .routers import chat, goals, voice

log = logging.getLogger("coach")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Goal Coach", version="0.1.0", lifespan=lifespan)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(chat.router)
app.include_router(goals.router)
app.include_router(voice.router)


@app.exception_handler(ClaudeNotConfigured)
async def handle_unconfigured(_: Request, exc: ClaudeNotConfigured) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(anthropic.APIError)
async def handle_upstream(_: Request, exc: anthropic.APIError) -> JSONResponse:
    """Turn SDK failures into a clean error instead of a 500 with a stack trace.

    The message is logged in full server-side; the client gets enough to act on.
    """
    log.exception("Claude API call failed")
    status = getattr(exc, "status_code", 502)
    detail = "Upstream Claude request failed."
    if status == 401:
        detail = "Claude rejected the API key. Check ANTHROPIC_API_KEY."
    elif status == 429:
        detail = "Rate limited by the Claude API. Try again shortly."
    return JSONResponse(status_code=502 if status < 400 else status, content={"detail": detail})


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "model": settings.claude_model,
        "claude_configured": bool(settings.anthropic_api_key),
    }


# Serve the built PWA when it exists, so the whole thing deploys as one service.
# In local dev the Vite server handles this instead and this block is a no-op.
if settings.static_dir.is_dir():
    assets = settings.static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        candidate = settings.static_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(settings.static_dir / "index.html")
