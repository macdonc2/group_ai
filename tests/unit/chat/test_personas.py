"""Wrestler personas: the per-reply draw from the voice bank and the dressed events listing.

A persona changes voice only, so these tests pin the parts code controls: the prompt
varies from turn to turn, and the events listing's own lines are never altered.
"""

import random
from types import SimpleNamespace

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent_system.adapters.outbound.fsm import nodes
from agent_system.adapters.outbound.llm import agents
from agent_system.adapters.outbound.llm.persona_voice import BANK, CLOSERS, EVENT_TAGLINES, OFF_THE_RAILS
from agent_system.adapters.outbound.llm.personas import (
    PERSONAS,
    event_tagline,
    persona_suffix,
    report_persona_suffix,
)

pytestmark = pytest.mark.unit

LISTING = """## Houston Events (3 found)
_Times are Houston local._

### Saturday, November 14

**Morning**
- **[Tandem Bicycle Demo Day](https://example.com/tandem)** — 9:00 AM · Pundt Park, Spring, TX · cycling
  Bicycle demonstration day

**Evening**
- **[Flea by Night](https://example.com/flea)** — 6:00 PM · Discovery Green, Houston, TX · food

**Time not listed**
- **[36th Annual Pow Wow](https://example.com/powwow)** — Traders Village Houston · community"""


class TestVoiceBank:
    def test_every_persona_has_enough_material_to_draw_from(self):
        assert set(BANK) == set(PERSONAS) == set(EVENT_TAGLINES) == set(OFF_THE_RAILS)
        for key, bank in BANK.items():
            assert len(bank["catchphrases"]) >= 8 and len(bank["riffs"]) >= 10 and len(bank["moves"]) >= 6, key
            assert set(EVENT_TAGLINES[key]) == {"Morning", "Afternoon", "Evening", "Time not listed"}, key

    def test_the_suffix_changes_from_turn_to_turn_and_can_be_pinned(self):
        assert persona_suffix("bret_hart", random.Random(1)) == persona_suffix("Bret_Hart ", random.Random(1))
        hands = {persona_suffix("bret_hart", random.Random(seed)) for seed in range(8)}
        assert len(hands) == 8
        for hand in hands:
            assert "THIS TURN" in hand and any(c in hand for c in CLOSERS)
            assert "Facts are not kayfabe" in hand and "exactly as if there were no persona" in hand

    def test_the_old_caps_on_the_voice_are_gone(self):
        suffix = persona_suffix("macho_man", random.Random(0))
        assert "two thirds" not in suffix and "\n- End on " not in suffix

    def test_unknown_or_missing_persona_adds_nothing(self):
        assert persona_suffix(None) == "" and persona_suffix("andre_the_giant") == ""
        assert report_persona_suffix("") == "" and event_tagline("andre_the_giant", "Morning") == ""

    def test_the_research_writer_keeps_a_fixed_prompt_with_the_phrases(self):
        suffix = report_persona_suffix("mean_gene")
        assert suffix == report_persona_suffix("mean_gene") and "THIS TURN" not in suffix
        assert "Hold on just a minute!" in suffix and "RESEARCH OVERVIEW" in suffix


def _ctx(persona):
    return SimpleNamespace(
        deps=SimpleNamespace(persona=persona, fallback_model="test", openai_api_key=""),
        state=SimpleNamespace(user_input="what's on today?"),
    )


def _model_saying(text: str, monkeypatch):
    def run(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(text)])

    monkeypatch.setattr(agents, "_get_model", lambda *a, **k: FunctionModel(run))


class TestEventsListing:
    def test_taglines_sit_beside_headers_and_events_are_untouched(self):
        dressed = nodes._dress_listing("macho_man", LISTING)
        before, after = LISTING.splitlines(), dressed.splitlines()
        assert len(before) == len(after)
        for old, new in zip(before, after):
            if old in ("**Morning**", "**Evening**", "**Time not listed**"):
                section = old.strip("*")
                assert new.startswith(f"{old} · _") and new[len(old) + 4:-1] in EVENT_TAGLINES["macho_man"][section]
            else:
                assert new == old

    async def test_no_persona_returns_the_plain_listing(self):
        assert await nodes._present_listing(_ctx(None), LISTING) == f"Here's what I found:\n\n{LISTING}"

    async def test_persona_frames_the_listing_with_a_promo_and_a_sign_off(self, monkeypatch):
        _model_saying("Houston is STACKED, brother!\n\nSIGN-OFF: The Madness has left the building.", monkeypatch)
        reply = await nodes._present_listing(_ctx("macho_man"), LISTING)
        assert reply.startswith("Houston is STACKED, brother!\n\n## Houston Events (3 found)")
        assert reply.endswith("\n\nThe Madness has left the building.") and "SIGN-OFF" not in reply
        for line in LISTING.splitlines():
            if line.startswith("- ") or line.startswith("  "):
                assert line in reply

    async def test_a_failed_promo_still_returns_the_listing(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no model")

        monkeypatch.setattr(agents, "_get_model", boom)
        reply = await nodes._present_listing(_ctx("bret_hart"), LISTING)
        assert reply.startswith("Here's what I found:\n\n## Houston Events") and "Flea by Night" in reply
