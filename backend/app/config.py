from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    # Everything is namespaced COACH_* on purpose. Bare names like CLAUDE_MODEL and
    # CLAUDE_EFFORT are already used by other tooling, and an ambient value would
    # silently override what's in .env.
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        env_prefix="COACH_",
        extra="ignore",
    )

    # --- Claude ---
    # The API key never leaves the server. The frontend talks only to this backend.
    # Reads the conventional ANTHROPIC_API_KEY too, since hosts set that by default.
    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("COACH_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    # Sonnet for real coaching conversation, per the build spec.
    claude_model: str = "claude-sonnet-5"
    # Cheaper/shorter pass for writing session summaries.
    claude_summary_model: str = "claude-sonnet-5"
    # low keeps the coach snappy enough for voice; raise to "medium" if replies feel shallow.
    claude_effort: str = "low"
    claude_max_tokens: int = 2048

    # --- Storage ---
    database_url: str = f"sqlite:///{BACKEND_DIR / 'coach.db'}"

    # --- Undo ---
    # How long after a delete you can still take it back. Soft-deleted rows are never
    # purged, so this bounds the *undo affordance*, not recoverability by hand.
    undo_window_seconds: int = 300

    # --- Memory window ---
    # How many recent session summaries get loaded into context. Bounded on purpose:
    # transcripts are never replayed, only these recaps.
    recent_summary_count: int = 8

    # --- Serving ---
    # Comma-separated origins for local dev. Empty means "same origin only".
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Built PWA is served from here when it exists (single-service deploy).
    static_dir: Path = REPO_DIR / "frontend" / "dist"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
