"""How much of a conversation the model is shown: a token budget, not a message count.

The app used to send a fixed number of recent messages (20 on the state machine, 12 on the
loop and in the journal) and drop the rest. A count is the wrong unit: twenty one-line
messages are tiny, twenty long replies are not, and either way a long conversation lost its
early turns with no warning to the model.

`select_history` keeps the most recent messages that fit a token budget:

- it walks back from the newest message and stops at the first one that does not fit, so
  what is kept is one unbroken stretch of the conversation, never a selection with gaps;
- the newest few messages are always kept, even over budget, so a turn is never answered
  without its immediate context;
- one very long message is cut to a per-message cap and marked, so it cannot use the budget alone;
- it reports how many earlier messages were left out, and the prompt tells the model so. A
  model that knows part of the conversation is out of view can say that, or look the detail up
  with the memory tools, instead of answering as if it had never been said.

Tokens are estimated at four characters each. That is rough, and good enough to keep a prompt
inside a budget; nothing here depends on the exact count.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")

CHARS_PER_TOKEN = 4
MIN_MESSAGES = 4          # always kept, whatever the budget


def estimate_tokens(text: str) -> int:
    return (len(text or "") + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


@dataclass
class HistorySelection(Generic[T]):
    kept: list[tuple[T, str]] = field(default_factory=list)   # (message, text to show), oldest first
    omitted: int = 0                                           # earlier messages not shown
    tokens: int = 0                                            # estimated size of what is shown
    clipped: int = 0                                           # messages cut to the per-message cap


def omitted_note(omitted: int) -> str:
    """What the model is told when part of the conversation is out of view."""
    if omitted <= 0:
        return ""
    return (f"{omitted} earlier message{'s' if omitted != 1 else ''} in this conversation {'are' if omitted != 1 else 'is'} "
            "not shown here. If the person refers to something from that part, say you no longer have it in view and "
            "ask, or look it up with the memory tools; do not guess what was said.")


def select_history(messages: Sequence[T], text_of: Callable[[T], str], token_budget: int,
                   per_message_tokens: int = 3000, min_messages: int = MIN_MESSAGES) -> HistorySelection[T]:
    """The most recent messages that fit `token_budget`, oldest first."""
    cap_chars = max(per_message_tokens, 1) * CHARS_PER_TOKEN
    selection: HistorySelection[T] = HistorySelection()
    newest_first: list[tuple[T, str]] = []
    for position, message in enumerate(reversed(messages)):
        text = text_of(message) or ""
        if len(text) > cap_chars:
            text = f"{text[:cap_chars].rstrip()}\n[message cut short: {len(text) - cap_chars} more characters]"
            clipped = 1
        else:
            clipped = 0
        cost = estimate_tokens(text)
        if position >= min_messages and selection.tokens + cost > token_budget:
            break
        newest_first.append((message, text))
        selection.tokens += cost
        selection.clipped += clipped
    selection.kept = list(reversed(newest_first))
    selection.omitted = len(messages) - len(newest_first)
    return selection
