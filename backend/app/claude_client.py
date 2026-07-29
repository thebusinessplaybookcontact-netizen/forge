"""Thin wrapper over the Anthropic SDK.

Everything that talks to Claude goes through here so model choice, effort, and
streaming behaviour are configured in exactly one place.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from functools import lru_cache

import anthropic

from .config import get_settings
from .prompts import SUMMARIZER_PROMPT, SUMMARY_SCHEMA


class ClaudeNotConfigured(RuntimeError):
    pass


@lru_cache
def get_client() -> anthropic.Anthropic:
    settings = get_settings()
    if settings.anthropic_api_key:
        return anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # The SDK also resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / an
    # `ant auth login` profile from the ambient environment. Construction succeeds even
    # with no credential at all and only fails at request time with a confusing 401, so
    # check up front and fail with something actionable.
    client = anthropic.Anthropic()
    if not (client.api_key or client.auth_token):
        raise ClaudeNotConfigured(
            "No Anthropic credentials. Set ANTHROPIC_API_KEY in backend/.env "
            "(copy backend/.env.example)."
        )
    return client


def _text_of(message) -> str:
    # Content is a list of blocks. With adaptive thinking on, thinking blocks come first
    # and carry no text (display defaults to "omitted"), so filter by type rather than
    # indexing content[0].
    return "".join(b.text for b in message.content if b.type == "text").strip()


def chat(system_blocks: list[dict], messages: list[dict]):
    """One coaching turn. Returns the raw SDK Message so callers can read usage."""
    settings = get_settings()
    client = get_client()

    # Streaming under the hood even for the non-streaming endpoint: it keeps the HTTP
    # connection alive on slow turns instead of risking a timeout.
    with client.messages.stream(
        model=settings.claude_model,
        max_tokens=settings.claude_max_tokens,
        system=system_blocks,
        messages=messages,
        output_config={"effort": settings.claude_effort},
    ) as stream:
        return stream.get_final_message()


def chat_stream(system_blocks: list[dict], messages: list[dict]) -> Iterator[str]:
    """Yields text deltas as they arrive, for the live chat UI."""
    settings = get_settings()
    client = get_client()

    with client.messages.stream(
        model=settings.claude_model,
        max_tokens=settings.claude_max_tokens,
        system=system_blocks,
        messages=messages,
        output_config={"effort": settings.claude_effort},
    ) as stream:
        yield from stream.text_stream


def summarize_session(transcript: str) -> tuple[str, list[str]]:
    """Write the compact recap that becomes this session's memory.

    Structured output so the recap and commitments come back as fields rather than
    prose we'd have to parse.
    """
    settings = get_settings()
    client = get_client()

    message = client.messages.create(
        model=settings.claude_summary_model,
        max_tokens=1024,
        system=SUMMARIZER_PROMPT,
        messages=[{"role": "user", "content": f"<transcript>\n{transcript}\n</transcript>"}],
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": SUMMARY_SCHEMA},
        },
    )

    data = json.loads(_text_of(message))
    return data["recap"], list(data.get("commitments", []))


text_of = _text_of
