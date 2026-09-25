"""
Shared Claude call used by the AI Coach chat and the race tactics brief.
"""

from __future__ import annotations

import anthropic
from config import ANTHROPIC_API_KEY

MODEL = "claude-opus-5-5"

# Opus 5.5 always thinks before answering, and that thinking counts toward
# max_tokens, so leave room for it on top of the visible reply.
MAX_TOKENS = 16000


def ask(system: list[dict], messages: list[dict], effort: str = "medium") -> str:
    """Send a request and return the reply text, or a readable error message."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
            output_config={"effort": effort},
            # Caches the system prompt plus conversation so far; later turns reuse it.
            cache_control={"type": "ephemeral"},
            # If a safety check wrongly declines a request, retry on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        return "Claude rejected the API key. Check ANTHROPIC_API_KEY in your .env file."
    except anthropic.RateLimitError:
        return "Claude is getting too many requests right now. Wait a minute and try again."
    except anthropic.APIStatusError as e:
        if e.status_code >= 500:
            return f"Claude is having trouble right now (error {e.status_code}). Try again shortly."
        return f"Claude returned an error: {e.message}"
    except anthropic.APIConnectionError:
        return "Couldn't reach Claude. Check your internet connection."

    if response.stop_reason == "refusal":
        return "Claude declined to answer that one. Try rephrasing the question."

    # The reply starts with thinking blocks, so pick out the text blocks by type.
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        return "Claude returned an empty reply. Try asking again."
    if response.stop_reason == "max_tokens":
        text += "\n\n_(This reply hit the length limit and was cut off.)_"
    return text
