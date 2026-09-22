"""ReAct steps must not send their instruction prose to tools as the query."""

import pytest

from agent_system.adapters.outbound.fsm.nodes import react_tool_input
from agent_system.adapters.outbound.llm.provider import openai_provider

pytestmark = pytest.mark.unit

STEP = "Check current park access, seasonal heat, road conditions, lodging or campground availability."
ASK = "Help me plan a 3-day road trip from Houston to Big Bend."


def test_step_agent_query_wins():
    assert react_tool_input("web_search", "Big Bend lodging Terlingua", ASK, STEP) == "Big Bend lodging Terlingua"


def test_search_falls_back_to_user_question_not_step_prose():
    assert react_tool_input("web_search", None, ASK, STEP) == ASK
    assert react_tool_input("web_search", "  ", ASK, STEP) == ASK


def test_non_search_tools_keep_step_description_fallback():
    assert react_tool_input("get_upcoming_events", None, ASK, STEP) == STEP


def test_providers_have_bounded_timeouts():
    chat = openai_provider("sk-test").client
    research = openai_provider("sk-test", long_running=True).client
    assert chat.timeout.read == 120 and chat.max_retries == 1
    assert research.timeout.read == 600
