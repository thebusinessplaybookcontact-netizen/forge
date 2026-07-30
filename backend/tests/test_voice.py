"""Text-to-speech: provider selection, the /api/speak endpoint, and failure modes.

The provider HTTP calls are mocked — these assert we build the right request and
degrade sensibly, not that OpenAI and ElevenLabs work.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import speech  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

MP3 = b"ID3\x04\x00fake-audio-bytes"


@pytest.fixture(autouse=True)
def clean_settings():
    """Settings are cached; each test edits the live object and resets afterwards."""
    Base.metadata.create_all(bind=engine)
    s = get_settings()
    saved = (s.tts_provider, s.openai_api_key, s.elevenlabs_api_key)
    s.tts_provider, s.openai_api_key, s.elevenlabs_api_key = "auto", "", ""
    yield s
    s.tts_provider, s.openai_api_key, s.elevenlabs_api_key = saved


@pytest.fixture()
def captured(monkeypatch):
    """Intercept the outbound provider call and record it."""
    seen: dict = {}

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            seen["url"] = url
            seen["headers"] = headers or {}
            seen["json"] = json or {}
            return httpx.Response(
                seen.get("status", 200),
                content=seen.get("body", MP3),
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(speech.httpx, "Client", FakeClient)
    return seen


# --- which provider gets used ---


def test_no_keys_means_no_human_voice(clean_settings):
    assert speech.active_provider() is None


def test_elevenlabs_is_preferred_when_both_keys_are_present(clean_settings):
    clean_settings.openai_api_key = "sk-openai"
    clean_settings.elevenlabs_api_key = "el-key"
    assert speech.active_provider() == "elevenlabs"


def test_openai_is_used_when_it_is_the_only_key(clean_settings):
    clean_settings.openai_api_key = "sk-openai"
    assert speech.active_provider() == "openai"


def test_provider_can_be_pinned(clean_settings):
    clean_settings.openai_api_key = "sk-openai"
    clean_settings.elevenlabs_api_key = "el-key"
    clean_settings.tts_provider = "openai"
    assert speech.active_provider() == "openai"


def test_provider_none_disables_human_voice(clean_settings):
    clean_settings.elevenlabs_api_key = "el-key"
    clean_settings.tts_provider = "none"
    assert speech.active_provider() is None


def test_pinned_provider_without_its_key_is_unavailable(clean_settings):
    clean_settings.elevenlabs_api_key = "el-key"
    clean_settings.tts_provider = "openai"  # pinned, but no OpenAI key
    assert speech.active_provider() is None


# --- request shape ---


def test_elevenlabs_request_shape(clean_settings, captured):
    clean_settings.elevenlabs_api_key = "el-key"
    audio, content_type = speech.synthesize("Go do the workout.")

    assert audio == MP3
    assert content_type == "audio/mpeg"
    assert captured["url"].endswith(f"/text-to-speech/{clean_settings.elevenlabs_voice_id}")
    assert captured["headers"]["xi-api-key"] == "el-key"
    assert captured["json"] == {
        "text": "Go do the workout.",
        "model_id": clean_settings.elevenlabs_model,
    }


def test_openai_request_shape(clean_settings, captured):
    clean_settings.openai_api_key = "sk-openai"
    speech.synthesize("Go do the workout.")

    assert captured["url"] == speech.OPENAI_URL
    assert captured["headers"]["Authorization"] == "Bearer sk-openai"
    assert captured["json"]["input"] == "Go do the workout."
    assert captured["json"]["response_format"] == "mp3"
    assert captured["json"]["model"] == clean_settings.openai_tts_model
    assert captured["json"]["voice"] == clean_settings.openai_tts_voice
    assert captured["json"]["instructions"]  # delivery style is sent


def test_long_text_is_clipped_at_a_word_boundary(clean_settings, captured):
    clean_settings.openai_api_key = "sk-openai"
    clean_settings.tts_max_chars = 40
    speech.synthesize("word " * 200)

    sent = captured["json"]["input"]
    assert len(sent) <= 40
    assert not sent.endswith("wor"), "should not cut mid-word"


def test_whitespace_is_collapsed(clean_settings, captured):
    clean_settings.openai_api_key = "sk-openai"
    speech.synthesize("  Go   do\n\nthe workout.  ")
    assert captured["json"]["input"] == "Go do the workout."


# --- failures ---


def test_synthesize_without_a_provider_raises_unavailable(clean_settings):
    with pytest.raises(speech.TTSUnavailable):
        speech.synthesize("anything")


def test_provider_error_raises_failed(clean_settings, captured):
    clean_settings.openai_api_key = "sk-openai"
    captured["status"] = 401
    captured["body"] = b"bad key"
    with pytest.raises(speech.TTSFailed, match="401"):
        speech.synthesize("anything")


def test_empty_text_is_rejected(clean_settings):
    clean_settings.openai_api_key = "sk-openai"
    with pytest.raises(speech.TTSFailed):
        speech.synthesize("   ")


# --- HTTP surface ---


def test_status_reports_availability(clean_settings):
    client = TestClient(app)
    assert client.get("/api/voice/status").json() == {"human_voice": False, "provider": None}

    clean_settings.elevenlabs_api_key = "el-key"
    assert client.get("/api/voice/status").json() == {
        "human_voice": True,
        "provider": "elevenlabs",
    }


def test_speak_returns_audio(clean_settings, captured):
    clean_settings.elevenlabs_api_key = "el-key"
    r = TestClient(app).post("/api/speak", json={"text": "Go do the workout."})

    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == MP3
    assert r.headers["etag"]  # same reply replayed shouldn't be re-billed


def test_speak_without_a_provider_is_503(clean_settings):
    """503 is the signal for the client to fall back to the browser voice."""
    r = TestClient(app).post("/api/speak", json={"text": "hello"})
    assert r.status_code == 503


def test_speak_with_a_broken_provider_is_502(clean_settings, captured):
    clean_settings.openai_api_key = "sk-openai"
    captured["status"] = 500
    captured["body"] = b"upstream boom"
    assert TestClient(app).post("/api/speak", json={"text": "hello"}).status_code == 502


def test_speak_rejects_empty_text(clean_settings):
    assert TestClient(app).post("/api/speak", json={"text": ""}).status_code == 422
