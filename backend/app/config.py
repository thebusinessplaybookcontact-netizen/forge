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

    # --- Voice (text to speech) ---
    # Speech-to-text is the phone's own engine and costs nothing, so it needs no config.
    # This is the "human voice" half; the browser's built-in voice is the free fallback.
    #
    # "auto" picks whichever provider has a key, preferring ElevenLabs. Set explicitly to
    # pin one, or "none" to disable human TTS entirely.
    tts_provider: str = "auto"  # auto | elevenlabs | openai | none
    tts_max_chars: int = 4000  # OpenAI's input cap is 4096

    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("COACH_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    # gpt-4o-mini-tts takes a style instruction; this is where the coach's delivery lives.
    openai_tts_instructions: str = (
        "Speak like a friend who knows you well: direct, warm, unhurried. "
        "Not a newsreader, not a customer service agent."
    )

    elevenlabs_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("COACH_ELEVENLABS_API_KEY", "ELEVENLABS_API_KEY"),
    )
    # Default is ElevenLabs' public "George" sample voice; swap for your own.
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    # flash is the low-latency model, which matters when you're waiting to hear a reply.
    elevenlabs_model: str = "eleven_flash_v2_5"

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
