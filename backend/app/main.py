import logging
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth
from .claude_client import ClaudeNotConfigured
from .config import get_settings
from .db import init_db
from .routers import auth_routes, chat, goals, habits_routes, voice

log = logging.getLogger("coach")

# Everything under /api needs a session except these. Health stays open so a platform
# healthcheck doesn't need credentials, and it deliberately leaks nothing but liveness.
OPEN_PATHS = frozenset({"/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/logout"})

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not auth.auth_required():
        log.warning(
            "COACH_PASSCODE is not set — the API is OPEN. Fine on localhost; if this is "
            "reachable from the internet, anyone with the URL can read your goals and "
            "spend your API credits."
        )
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

@app.middleware("http")
async def require_session(request: Request, call_next):
    """Gate the API behind the passcode.

    A middleware rather than a per-route dependency so a new router can't accidentally
    ship unprotected — the default is closed, and exceptions are listed in one place.
    The SPA shell itself stays public; it's a static bundle with no data in it, and it
    needs to load in order to show the lock screen.
    """
    path = request.url.path
    if (
        auth.auth_required()
        and path.startswith("/api/")
        and path not in OPEN_PATHS
        and not auth.token_valid(request.cookies.get(auth.COOKIE_NAME))
    ):
        return JSONResponse(status_code=401, content={"detail": "Locked."})
    return await call_next(request)


app.include_router(auth_routes.router)
app.include_router(chat.router)
app.include_router(goals.router)
app.include_router(habits_routes.router)
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
        # Surfaced so an accidentally-open deploy is visible without reading logs.
        "auth": "on" if auth.auth_required() else "off",
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
