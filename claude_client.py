"""
Shared Claude calls used by the AI Coach chat and the race tactics brief.
"""

from __future__ import annotations

from typing import Callable, Iterator

import anthropic
from config import ANTHROPIC_API_KEY

MODEL = "claude-opus-5-5"

# Opus 5.5 always thinks before answering, and that thinking counts toward
# max_tokens, so leave room for it on top of the visible reply.
MAX_TOKENS = 16000
STREAM_MAX_TOKENS = 32000

# Most tool rounds the coach may take for one question before we stop it.
MAX_TOOL_ROUNDS = 8

REFUSAL_MESSAGE = "Claude declined to answer that one. Try rephrasing the question."
CUT_OFF_NOTE = "\n\n_(This reply hit the length limit and was cut off.)_"


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _request(system: list[dict], messages: list[dict], effort: str, max_tokens: int) -> dict:
    return dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        output_config={"effort": effort},
        # Caches the tools, system prompt and conversation so far; later turns reuse it.
        cache_control={"type": "ephemeral"},
        # If a safety check wrongly declines a request, retry on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )


def _error_message(e: anthropic.APIError) -> str:
    if isinstance(e, anthropic.AuthenticationError):
        return "Claude rejected the API key. Check ANTHROPIC_API_KEY in your .env file."
    if isinstance(e, anthropic.RateLimitError):
        return "Claude is getting too many requests right now. Wait a minute and try again."
    if isinstance(e, anthropic.APIStatusError):
        if e.status_code >= 500:
            return f"Claude is having trouble right now (error {e.status_code}). Try again shortly."
        return f"Claude returned an error: {e.message}"
    if isinstance(e, anthropic.APIConnectionError):
        return "Couldn't reach Claude. Check your internet connection."
    return f"Something went wrong talking to Claude: {e}"


def ask(system: list[dict], messages: list[dict], effort: str = "medium") -> str:
    """Send a request and return the reply text, or a readable error message."""
    try:
        response = _client().beta.messages.create(**_request(system, messages, effort, MAX_TOKENS))
    except anthropic.APIError as e:
        return _error_message(e)

    if response.stop_reason == "refusal":
        return REFUSAL_MESSAGE

    # The reply starts with thinking blocks, so pick out the text blocks by type.
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        return "Claude returned an empty reply. Try asking again."
    if response.stop_reason == "max_tokens":
        text += CUT_OFF_NOTE
    return text


def stream_chat(
    system: list[dict],
    messages: list[dict],
    tools: list[dict],
    run_tool: Callable[[str, dict], str],
    effort: str = "medium",
) -> Iterator[tuple[str, str]]:
    """
    Stream a reply, running tools as Claude asks for them.

    Yields ("text", chunk) as the reply arrives, ("tool", name) when a tool
    runs, and ("error", message) if the reply could not be finished.
    run_tool should raise ValueError for bad input; the message goes back to Claude.
    """
    client = _client()
    messages = list(messages)
    tools = [{**t, "eager_input_streaming": True} for t in tools]
    json_retries = 0

    rounds = 0
    while rounds < MAX_TOOL_ROUNDS:
        try:
            with client.beta.messages.stream(
                **_request(system, messages, effort, STREAM_MAX_TOKENS), tools=tools
            ) as stream:
                for event in stream:
                    if event.type == "text":
                        yield ("text", event.text)
                response = stream.get_final_message()
            json_retries = 0
        except anthropic.APIError as e:
            yield ("error", _error_message(e))
            return
        except ValueError:
            # A tool call arrived as JSON the SDK could not parse. Ask again, a couple of times.
            json_retries += 1
            if json_retries > 2:
                yield ("error", "Claude sent a malformed tool request. Try asking again.")
                return
            continue

        if response.stop_reason == "refusal":
            yield ("error", REFUSAL_MESSAGE)
            return

        tool_uses = [block for block in response.content if block.type == "tool_use"]
        if not tool_uses:
            if response.stop_reason == "max_tokens":
                yield ("text", CUT_OFF_NOTE)
            return
        if response.stop_reason == "max_tokens":
            yield ("error", "The reply hit the length limit while Claude was looking something up.")
            return

        results = []
        for block in tool_uses:
            yield ("tool", block.name)
            try:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": run_tool(block.name, block.input)})
            except ValueError as e:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": f"Invalid input: {e}", "is_error": True})
            except Exception as e:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": f"Tool failed: {e}", "is_error": True})

        # Pass the reply back unchanged (thinking blocks included) so Claude keeps its reasoning.
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": results})
        rounds += 1

    yield ("error", "The coach needed too many lookups for one question. Try asking something narrower.")
