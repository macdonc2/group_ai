"""How much of a conversation the model is shown: a token budget, not a message count."""

from types import SimpleNamespace

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse

from agent_system.adapters.outbound.llm import chat_agent, journal_agent
from agent_system.adapters.outbound.llm.chat_agent import (
    ChatDeps,
    build_history_and_omitted,
    turn_context,
)
from agent_system.adapters.outbound.llm.history import estimate_tokens, omitted_note, select_history

pytestmark = pytest.mark.unit


def msg(role: str, text: str):
    return SimpleNamespace(role=SimpleNamespace(value=role), content=SimpleNamespace(text=text), tool_calls=None)


def conversation(pairs: int, chars: int = 400):
    out = []
    for i in range(pairs):
        out += [msg("user", f"question {i} " + "q" * chars), msg("assistant", f"answer {i} " + "a" * chars)]
    return out


def test_a_short_conversation_is_shown_whole():
    items = [f"message {i}" for i in range(30)]                    # thirty short messages: far more than the old limit of 20
    selection = select_history(items, str, token_budget=16000)
    assert [t for _, t in selection.kept] == items
    assert selection.omitted == 0
    assert selection.clipped == 0


def test_a_long_conversation_keeps_the_most_recent_stretch_that_fits():
    items = [f"{i:03d} " + "x" * 396 for i in range(100)]           # 100 tokens each
    selection = select_history(items, str, token_budget=2500)
    kept = [t[:3] for _, t in selection.kept]
    assert kept == [f"{i:03d}" for i in range(75, 100)]             # the last 25, oldest first, no gaps
    assert selection.omitted == 75
    assert selection.tokens == 2500


def test_selection_stops_at_the_first_message_that_does_not_fit_so_there_are_no_gaps():
    items = ["old short", "B" * 4000, "recent one", "recent two", "recent three", "recent four", "recent five"]
    selection = select_history(items, str, token_budget=500)
    assert [t for _, t in selection.kept] == items[2:]              # the short old message is not pulled in past the long one
    assert selection.omitted == 2


def test_the_newest_messages_are_kept_even_when_they_exceed_the_budget():
    items = ["a" * 4000, "b" * 4000, "c" * 4000, "d" * 4000, "e" * 4000, "f" * 4000]
    selection = select_history(items, str, token_budget=100)
    assert len(selection.kept) == 4
    assert selection.omitted == 2


def test_one_huge_message_is_cut_and_marked_so_it_cannot_use_the_whole_budget():
    items = ["short question", "P" * 50000, "follow-up"]
    selection = select_history(items, str, token_budget=16000, per_message_tokens=1000)
    pasted = selection.kept[1][1]
    assert pasted.startswith("P" * 4000)
    assert "[message cut short: 46000 more characters]" in pasted
    assert selection.clipped == 1
    assert selection.omitted == 0


def test_the_model_is_told_what_is_out_of_view():
    assert omitted_note(0) == ""
    assert omitted_note(1).startswith("1 earlier message in this conversation is not shown")
    note = omitted_note(42)
    assert note.startswith("42 earlier messages in this conversation are not shown")
    assert "do not guess" in note
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_loop_history_is_the_whole_recent_conversation_not_twelve_messages():
    messages = conversation(20) + [msg("user", "and now?")]         # 40 earlier messages, about 100 tokens each
    history, omitted = build_history_and_omitted(messages, "and now?", token_budget=16000)
    assert len(history) == 40
    assert omitted == 0
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[-1], ModelResponse)
    assert history[0].parts[0].content.startswith("question 0")

    history, omitted = build_history_and_omitted(messages, "and now?", token_budget=1000)
    assert 4 <= len(history) < 40
    assert omitted == 40 - len(history)
    assert isinstance(history[0], ModelRequest)                     # still opens with a user turn
    assert history[-1].parts[0].content.startswith("answer 19")     # and ends with the latest reply


def test_loop_history_keeps_long_replies_whole_up_to_the_message_cap():
    long_reply = "Detailed plan. " + "d" * 6000                     # the old cut was 2,500 characters
    history, _ = build_history_and_omitted([msg("user", "plan it"), msg("assistant", long_reply), msg("user", "next")], "next")
    assert history[1].parts[0].content == long_reply


def test_the_loop_prompt_says_how_much_is_out_of_view():
    ctx = SimpleNamespace(deps=ChatDeps(user_id="u", history_omitted=12))
    assert "12 earlier messages in this conversation are not shown" in turn_context(ctx)
    assert "not shown" not in turn_context(SimpleNamespace(deps=ChatDeps(user_id="u")))


def test_journal_side_chat_uses_a_budget_too():
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"{i} " + "j" * 3000} for i in range(40)]
    history, omitted = journal_agent.build_history_and_omitted(messages, token_budget=8000)
    assert len(history) > 4
    assert omitted == 40 - len(history)
    assert history[-1].parts[0].content.startswith("39 ")
    assert len(history[-1].parts[0].content) == 3003
    assert isinstance(history[0], ModelRequest)
    assert journal_agent.build_history([{"role": "assistant", "content": "orphan"}, {"role": "user", "content": "hi"}])[0].parts[0].content == "hi"
    assert chat_agent.HISTORY_TOKENS == 16000
    assert journal_agent.HISTORY_TOKENS == 8000


def test_replies_are_asked_to_go_deep_by_default_and_personas_keep_the_substance():
    # Replies on the loop engine were averaging about 220 words: the prompt said "a few paragraphs"
    # and a persona capped a full reply at 200 to 350 words, half of it show.
    from agent_system.adapters.outbound.llm.personas import persona_suffix

    assert "450 to 700 words" in chat_agent.INSTRUCTIONS
    assert "Do not stop at the first" in chat_agent.INSTRUCTIONS
    assert "a few paragraphs" not in chat_agent.INSTRUCTIONS
    assert "Short is right only when the message is short by nature" in chat_agent.INSTRUCTIONS
    voice = persona_suffix("ultimate_warrior")
    assert "450 to 700 words" in voice
    assert "200 to 350 words" not in voice
    assert "at least half the words are the real answer" in voice
    assert persona_suffix(None) == ""
