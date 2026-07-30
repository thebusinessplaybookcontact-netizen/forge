"""The tool-use loop.

One coaching turn is not one API call. The model may ask to change the to-do list, and
it may ask for several changes at once ("mark the workout done and add a task to call
the accountant" is two tool calls in a single response). The shape is:

    call the API
      -> stop_reason == "tool_use"?  execute every tool_use block in the response,
         append the assistant turn plus ONE user turn containing all the tool_results,
         and call again
      -> otherwise, that's the reply

Both endpoints run this loop; the streaming one just emits text deltas along the way.

Two rules that are easy to get wrong and expensive to debug:

  * Every tool_use block must get a matching tool_result, and they all go in a *single*
    user message. Splitting them across messages trains the model out of making
    parallel calls.
  * The assistant turn is appended as `message.content` verbatim, thinking blocks and
    all. Reconstructing or filtering it breaks the signature the API expects back.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from . import claude_client, tools, usage as usage_log
from .config import get_settings
from .tools import ToolOutcome

# A turn that still wants tools after this many round trips is stuck. Each iteration is
# a billed request, so the cap is a cost guard as much as a loop guard.
MAX_TOOL_ITERATIONS = 6


class ModelRefused(RuntimeError):
    pass


@dataclass
class TurnResult:
    reply: str
    actions: list[ToolOutcome] = field(default_factory=list)
    usage: object | None = None
    # True when the loop hit the cap with the model still asking for tools.
    truncated: bool = False


def _tool_result_blocks(db: Session, message) -> tuple[list[dict], list[ToolOutcome]]:
    """Execute every tool_use block in one response; return the results and outcomes."""
    blocks: list[dict] = []
    outcomes: list[ToolOutcome] = []

    for block in message.content:
        if block.type != "tool_use":
            continue
        outcome = tools.execute(db, block.name, dict(block.input or {}))
        outcomes.append(outcome)
        blocks.append(
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": outcome.message,
                # Flags the failure so the model treats it as something to recover from
                # rather than as a successful write.
                "is_error": outcome.is_error,
            }
        )

    return blocks, outcomes


def run_turn(db: Session, system_blocks: list[dict], messages: list[dict]) -> TurnResult:
    """Non-streaming turn. Returns the final reply plus everything that changed."""
    working = list(messages)
    actions: list[ToolOutcome] = []
    last_usage = None

    for _ in range(MAX_TOOL_ITERATIONS):
        message = claude_client.complete(system_blocks, working, tools.TOOL_DEFINITIONS)
        last_usage = message.usage
        usage_log.record(db, kind="chat", model=get_settings().claude_model, usage=message.usage)

        if message.stop_reason == "refusal":
            raise ModelRefused("The model declined to respond to that.")

        if message.stop_reason != "tool_use":
            return TurnResult(claude_client.text_of(message), actions, last_usage)

        working.append({"role": "assistant", "content": message.content})
        result_blocks, outcomes = _tool_result_blocks(db, message)
        actions.extend(outcomes)
        working.append({"role": "user", "content": result_blocks})

    # Cap reached. Whatever the tools already did is committed, so report it rather than
    # pretending the turn failed outright.
    return TurnResult(
        "I made those changes but got tangled up explaining them. Ask me where things stand.",
        actions,
        last_usage,
        truncated=True,
    )


@dataclass
class Delta:
    text: str


@dataclass
class Action:
    outcome: ToolOutcome


@dataclass
class Final:
    reply: str
    truncated: bool = False


def stream_turn(
    db: Session, system_blocks: list[dict], messages: list[dict]
) -> Iterator[Delta | Action | Final]:
    """Streaming turn. Yields text deltas, then tool actions, then a Final.

    Text can arrive both before a tool call (the coach saying what it's about to do) and
    after, so deltas from every iteration are concatenated into the reply.
    """
    working = list(messages)
    reply_parts: list[str] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        with claude_client.stream_message(system_blocks, working, tools.TOOL_DEFINITIONS) as stream:
            for delta in stream.text_stream:
                reply_parts.append(delta)
                yield Delta(delta)
            message = stream.get_final_message()
        usage_log.record(db, kind="chat", model=get_settings().claude_model, usage=message.usage)

        if message.stop_reason == "refusal":
            raise ModelRefused("The model declined to respond to that.")

        if message.stop_reason != "tool_use":
            yield Final("".join(reply_parts).strip())
            return

        working.append({"role": "assistant", "content": message.content})
        result_blocks, outcomes = _tool_result_blocks(db, message)
        for outcome in outcomes:
            yield Action(outcome)
        working.append({"role": "user", "content": result_blocks})

    yield Final("".join(reply_parts).strip(), truncated=True)
