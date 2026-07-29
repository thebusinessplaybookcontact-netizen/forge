"""Thin wrapper over the Anthropic SDK.

Everything that talks to Claude goes through here so model choice, effort, and
streaming behaviour are configured in exactly one place.
"""

from __future__ import annotations

import json
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


def _request_kwargs(system_blocks: list[dict], messages: list[dict], tools: list[dict] | None) -> dict:
    settings = get_settings()
    kwargs: dict = {
        "model": settings.claude_model,
        "max_tokens": settings.claude_max_tokens,
        "system": system_blocks,
        "messages": messages,
        "output_config": {"effort": settings.claude_effort},
    }
    if tools:
        kwargs["tools"] = tools
    return kwargs


def complete(system_blocks: list[dict], messages: list[dict], tools: list[dict] | None = None):
    """One request/response against the API. Returns the raw SDK Message.

    This is the single seam the whole agent loop runs through, which is also what the
    tests patch — everything above it (the tool loop, validation, the DB writes) stays
    real under test.

    Streams under the hood even though it returns a whole message: it keeps the
    connection alive on slow turns instead of risking an HTTP timeout.
    """
    with get_client().messages.stream(**_request_kwargs(system_blocks, messages, tools)) as stream:
        return stream.get_final_message()


def stream_message(system_blocks: list[dict], messages: list[dict], tools: list[dict] | None = None):
    """Context manager yielding the live stream, for the SSE endpoint.

    Callers iterate `.text_stream` for deltas and then call `.get_final_message()` to
    find out whether the turn ended in tool use.
    """
    return get_client().messages.stream(**_request_kwargs(system_blocks, messages, tools))


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
