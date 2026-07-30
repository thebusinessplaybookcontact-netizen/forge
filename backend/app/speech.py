"""Text to speech.

The "human voice" half of the voice feature. Speech-to-text is the phone's own engine
and never reaches the server — this module only turns the coach's replies into audio.

Two providers behind one function because the spec suggested OpenAI while the operator
already runs ElevenLabs elsewhere; whichever key is present wins, so the choice is a
config change rather than a code change. Keys stay server-side, same as the Claude key:
the browser asks this API for audio and never sees a credential.
"""

from __future__ import annotations

import httpx

from .config import get_settings

OPENAI_URL = "https://api.openai.com/v1/audio/speech"
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

# TTS is slower than a chat token but not slow; a minute is generous for a few sentences.
TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class TTSUnavailable(RuntimeError):
    """No provider is configured. The client should fall back to the browser voice."""


class TTSFailed(RuntimeError):
    """A provider was configured but the request to it failed."""


def active_provider() -> str | None:
    """Which provider will be used, or None if human TTS isn't available."""
    settings = get_settings()
    choice = (settings.tts_provider or "auto").lower()

    if choice == "none":
        return None
    if choice == "elevenlabs":
        return "elevenlabs" if settings.elevenlabs_api_key else None
    if choice == "openai":
        return "openai" if settings.openai_api_key else None

    # auto: prefer ElevenLabs, fall back to OpenAI, else nothing.
    if settings.elevenlabs_api_key:
        return "elevenlabs"
    if settings.openai_api_key:
        return "openai"
    return None


def _clip(text: str) -> str:
    settings = get_settings()
    text = " ".join(text.split())
    if len(text) <= settings.tts_max_chars:
        return text
    # Cut at a word boundary so the audio doesn't end mid-syllable.
    return text[: settings.tts_max_chars].rsplit(" ", 1)[0]


def _openai(text: str) -> tuple[bytes, str]:
    settings = get_settings()
    payload = {
        "model": settings.openai_tts_model,
        "input": text,
        "voice": settings.openai_tts_voice,
        "response_format": "mp3",
    }
    if settings.openai_tts_instructions:
        payload["instructions"] = settings.openai_tts_instructions

    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json=payload,
        )
    if r.status_code != 200:
        raise TTSFailed(f"OpenAI TTS returned {r.status_code}: {r.text[:200]}")
    return r.content, "audio/mpeg"


def _elevenlabs(text: str) -> tuple[bytes, str]:
    settings = get_settings()
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(
            ELEVENLABS_URL.format(voice_id=settings.elevenlabs_voice_id),
            headers={"xi-api-key": settings.elevenlabs_api_key},
            json={"text": text, "model_id": settings.elevenlabs_model},
        )
    if r.status_code != 200:
        raise TTSFailed(f"ElevenLabs TTS returned {r.status_code}: {r.text[:200]}")
    return r.content, "audio/mpeg"


def synthesize(text: str) -> tuple[bytes, str]:
    """Render text as speech. Returns (audio bytes, content type)."""
    text = _clip(text)
    if not text:
        raise TTSFailed("Nothing to speak.")

    provider = active_provider()
    if provider == "elevenlabs":
        return _elevenlabs(text)
    if provider == "openai":
        return _openai(text)

    raise TTSUnavailable(
        "No text-to-speech provider configured. Set ELEVENLABS_API_KEY or OPENAI_API_KEY "
        "in backend/.env, or use the built-in browser voice."
    )
