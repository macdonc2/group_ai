"""show_map: the place is validated and the link is built and placed by code, not by the model."""

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agent_system.adapters.outbound.llm.chat_agent import ChatDeps, run_chat_loop
from agent_system.adapters.outbound.llm.maps import (
    MAP_LINK_PREFIX,
    MapPlace,
    map_links_in,
    map_query,
    show_map,
    with_map_links,
)


def test_link_is_built_from_place_and_city():
    place = MapPlace(place="  Shell Energy   Stadium ", near="Houston, TX")
    assert place.query == "Shell Energy Stadium, Houston, TX"
    assert place.link == MAP_LINK_PREFIX + "Shell+Energy+Stadium%2C+Houston%2C+TX"
    assert map_query(place.link) == place.query


def test_city_is_not_repeated_when_the_place_already_names_it():
    assert MapPlace(place="813 St Emanuel St, Houston", near="houston").query == "813 St Emanuel St, Houston"


def test_place_text_cannot_break_out_of_the_query():
    link = MapPlace(place="Joe's & Sons #2 ?output=embed&q=evil").link
    assert link.count("?") == 1
    assert "&q=" not in link
    assert "#" not in link
    assert map_query(link) == "Joe's & Sons #2 ?output=embed&q=evil"


@pytest.mark.parametrize("bad", ["", "  ", "it", "That Place", "https://evil.example/x", "www.example.com", "???", "x" * 201])
async def test_a_bad_place_is_refused_with_a_reason(bad):
    result = await show_map(bad)
    assert result.success is False
    assert result.data is None
    assert "Cannot map" in result.message


async def test_tool_result_carries_the_link_and_does_not_claim_an_address():
    result = await show_map("Toyota Center", near="Houston")
    assert result.success
    assert result.data == {"query": "Toyota Center, Houston", "url": MapPlace(place="Toyota Center", near="Houston").link}
    assert result.data["url"] in result.message
    assert "did not confirm" in result.message


def test_only_links_of_our_shape_count_as_map_links():
    ours = MapPlace(place="POST Houston").link
    text = f"See [map]({ours}). Not https://www.google.com/maps/place/x nor https://evil.example/maps/search/?api=1&query=a."
    assert map_links_in(text) == [ours]
    assert map_query("https://www.google.com/maps/place/x") is None


def test_missing_link_is_added_and_a_present_one_is_not_repeated():
    link = MapPlace(place="POST Houston").link
    added = with_map_links("It is downtown.", [link])
    assert added == f"It is downtown.\n\n[POST Houston on Google Maps]({link})"
    assert with_map_links(added, [link]) == added
    # the same place written with another encoding is still the same place
    assert with_map_links(f"Here: {MAP_LINK_PREFIX}POST%20Houston", [link]).count("google.com/maps") == 1
    assert with_map_links("No map asked for.", []) == "No map asked for."


def test_at_most_three_maps_per_reply():
    links = [MapPlace(place=f"Place {i}").link for i in range(5)]
    assert len(map_links_in(with_map_links("Several.", links))) == 3


def _model(*replies):
    queue = list(replies)

    def run(messages, info):
        return ModelResponse(parts=[queue.pop(0)])

    return FunctionModel(run)


async def test_loop_puts_the_link_in_the_reply_when_the_model_leaves_it_out():
    model = _model(ToolCallPart("show_map", {"place": "Shell Energy Stadium", "near": "Houston, TX"}),
                   TextPart("It is in East Downtown."))
    out = await run_chat_loop("Where is Shell Energy Stadium?", deps=ChatDeps(user_id="u-1"), model=model)

    link = MapPlace(place="Shell Energy Stadium", near="Houston, TX").link
    assert out.tools_used == ["show_map"]
    assert out.response == f"It is in East Downtown.\n\n[Shell Energy Stadium, Houston, TX on Google Maps]({link})"


async def test_loop_adds_nothing_when_the_place_was_refused():
    model = _model(ToolCallPart("show_map", {"place": "there"}), TextPart("Which place do you mean?"))
    out = await run_chat_loop("Where is it?", deps=ChatDeps(user_id="u-1"), model=model)

    assert out.response == "Which place do you mean?"
    assert out.steps[0]["ok"] is False


async def test_added_link_reaches_a_streaming_client():
    from tests.unit.chat.test_chat_loop import scripted

    sent: list[str] = []

    async def emit(kind, node, message, data=None):
        if kind == "response_chunk":
            sent.append(message)

    model, _, _ = scripted(("show_map", {"place": "POST Houston"}), "Downtown, by the bayou.")
    out = await run_chat_loop("Where is POST Houston?", deps=ChatDeps(user_id="u-1", emit=emit), model=model)

    assert "".join(sent) == out.response
    assert MapPlace(place="POST Houston").link in sent[-1]
