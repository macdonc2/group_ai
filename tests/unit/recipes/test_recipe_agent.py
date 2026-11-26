"""The pitch agent: its tools, what it is told, and the checks code runs on its answer.

The real agent runs against a scripted `FunctionModel`, so nothing here touches a model, a
database or the network.
"""

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent_system.adapters.outbound.llm.recipe_agent import (
    TOOL_NAMES,
    DraftRecipe,
    PitchRequest,
    PitchSheet,
    RecipeDeps,
    avoided_in,
    check_sheet,
    recipe_from_draft,
    request_text,
    run_pitch_turn,
)
from agent_system.domain.recipes.jsonld import recipes_from_html
from agent_system.domain.recipes.models import RecipeSource
from agent_system.domain.recipes.search import search
from agent_system.domain.recipes.units import Unit
from tests.unit.recipes.samples import cookbook_recipes

pytestmark = pytest.mark.unit

PROMO = "OHHH the kitchen is LOUD tonight and the card is stacked from top to bottom, so ring the bell!"
HYPE = "This one walks in with lime and leaves with the belt, no question about it."
DRAFT = {
    "title": "Skillet Lime Chicken", "servings": "Serves 4", "prep_time": "10 min", "cook_time": "20 min",
    "category": "chicken", "tags": ["weeknight"],
    "ingredients": [{"quantity": "1 1/2", "unit": "lb", "name": "chicken thighs", "note": "boneless"},
                    {"quantity": "2", "unit": "tbsp", "name": "lime juice"},
                    {"quantity": "3", "unit": None, "name": "garlic cloves", "note": "minced"},
                    {"quantity": None, "unit": None, "name": "salt"}],
    "steps": ["Season the chicken and sear it in a hot skillet, 6 minutes a side.",
              "Add garlic and lime juice and cook to 165 F in the thickest part."],
    "notes": [],
}
WEB_PAGE = ('<script type="application/ld+json">{"@type":"Recipe","name":"Web Fried Rice","recipeIngredient":'
            '["2 cups cooked rice","2 eggs","1 tbsp soy sauce"],"recipeInstructions":["Fry it."]}</script>')


def scripted(*steps):
    """A model that plays `steps` in order. A step is ("tool", args) or a dict to return as the card."""
    seen = {"results": [], "retries": [], "instructions": "", "tools": [], "prompt": ""}

    def run(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen["instructions"] = info.instructions or ""
        seen["tools"] = sorted(t.name for t in info.function_tools)
        parts = [p for m in messages if isinstance(m, ModelRequest) for p in m.parts]
        seen["prompt"] = next(str(p.content) for p in parts if p.part_kind == "user-prompt")
        seen["results"] = [str(p.content) for p in parts if isinstance(p, ToolReturnPart)]
        seen["retries"] = [p.model_response() for p in parts if isinstance(p, RetryPromptPart)]
        step = steps[min(len(seen["results"]) + len(seen["retries"]), len(steps) - 1)]
        if isinstance(step, tuple):
            return ModelResponse(parts=[ToolCallPart(step[0], step[1])])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, step)])

    return FunctionModel(run), seen


def deps(request: PitchRequest | None = None, *, web: bool = True, **overrides) -> RecipeDeps:
    library = list(cookbook_recipes().items())

    async def find_cookbook(query, have, category):
        return [(h.key, h.recipe) for h in search(library, query, have=have, category=category)]

    async def find_web(query):
        return recipes_from_html(WEB_PAGE, "https://food.example/fried-rice")

    return RecipeDeps(user_id="u1", request=request or PitchRequest(craving="something with lime", allow_web=True),
                      find_cookbook=find_cookbook, find_web=find_web if web else None, model_name="test-model",
                      **overrides)


def sheet(*pitches) -> dict:
    return {"promo": PROMO, "pitches": [{"hype": HYPE, **p} for p in pitches]}


async def test_a_cookbook_pick_is_shown_from_the_stored_recipe_not_from_model_text():
    model, seen = scripted(("search_cookbook", {"query": "lime"}), sheet({"source": "cookbook", "ref": "C1"}))
    d = deps()
    outcome = await run_pitch_turn(deps=d, model=model)

    assert outcome.stopped == "answered"
    assert outcome.promo == PROMO
    assert outcome.tools_used == ["search_cookbook"]
    [card] = outcome.cards
    assert card.recipe == cookbook_recipes()["lime-shrimp-tacos"]
    assert card.library_id == "lime-shrimp-tacos"
    assert card.recipe.source is RecipeSource.COOKBOOK
    assert card.hype == HYPE
    assert seen["tools"] == sorted(TOOL_NAMES)
    assert "C1 | Lime Shrimp Tacos" in seen["results"][0]
    assert "C2 | Peanut Noodles" in seen["results"][0]


async def test_the_request_and_the_voice_reach_the_model():
    model, seen = scripted(("search_cookbook", {"query": "lime"}), sheet({"source": "cookbook", "ref": "C1"}))
    request = PitchRequest(craving="tacos", have=["shrimp", "lime juice"], avoid=["peanuts"], already_pitched=["Old Dish"], count=1)
    await run_pitch_turn(deps=deps(request), model=model)

    assert seen["prompt"] == request_text(request)
    assert "What I fancy: tacos" in seen["prompt"]
    assert "In my kitchen: shrimp, lime juice" in seen["prompt"]
    assert "Avoid (never pitch anything containing these): peanuts" in seen["prompt"]
    assert "Dishes to pitch: 1." in seen["instructions"]
    assert "THE RING CHEF" in seen["instructions"]
    assert "Web lookup: off" in seen["instructions"]
    assert "uses from their kitchen: shrimp, lime juice" in seen["results"][0]


async def test_a_wrestler_persona_replaces_the_house_voice():
    model, seen = scripted(("search_cookbook", {"query": "lime"}), sheet({"source": "cookbook", "ref": "C1"}))
    await run_pitch_turn(deps=deps(persona="macho_man"), model=model)
    assert "RANDY SAVAGE" in seen["instructions"]
    assert "THE RING CHEF" not in seen["instructions"]
    assert "IN THE RECIPE RING" in seen["instructions"]


async def test_a_made_up_reference_is_sent_back_and_the_fix_is_accepted():
    model, seen = scripted(
        ("search_cookbook", {"query": "lime"}),
        sheet({"source": "cookbook", "ref": "C9"}),                      # no such reference
        sheet({"source": "cookbook", "ref": "C2"}),
    )
    outcome = await run_pitch_turn(deps=deps(), model=model)

    assert outcome.stopped == "answered"
    assert [c.recipe.title for c in outcome.cards] == ["Peanut Noodles"]
    assert "ref 'C9' is not a cookbook recipe a search returned this turn" in seen["retries"][0]
    assert "Known references: C1, C2" in seen["retries"][0]


async def test_a_card_that_never_passes_the_checks_is_not_shown():
    model, _ = scripted(sheet({"source": "cookbook", "ref": "C1"}))        # never searches, so C1 does not exist
    outcome = await run_pitch_turn(deps=deps(), model=model)
    assert outcome.stopped == "error"
    assert outcome.cards == []
    assert "failing the checks" in outcome.message


async def test_the_avoid_list_is_enforced_in_code_before_and_after_the_model():
    request = PitchRequest(craving="noodles", avoid=["peanuts"])
    model, seen = scripted(
        ("search_cookbook", {"query": "lime"}),
        sheet({"source": "new", "recipe": {**DRAFT, "ingredients": [*DRAFT["ingredients"],
                                                                 {"quantity": "1/4", "unit": "cup", "name": "peanut butter"}]}}),
        sheet({"source": "cookbook", "ref": "C1"}),
    )
    outcome = await run_pitch_turn(deps=deps(request), model=model)

    assert "Peanut Noodles" not in seen["results"][0]  # hidden from the model
    assert "Lime Shrimp Tacos" in seen["results"][0]
    assert "contains 'peanuts', which is on the avoid list" in seen["retries"][0]                  # and refused from it
    assert [c.recipe.title for c in outcome.cards] == ["Lime Shrimp Tacos"]


async def test_a_new_recipe_is_validated_and_stamped_as_model_written():
    model, _ = scripted(("search_cookbook", {"query": "chicken lime"}), sheet({"source": "new", "recipe": DRAFT}))
    outcome = await run_pitch_turn(deps=deps(), model=model)

    [card] = outcome.cards
    recipe = card.recipe
    assert recipe.source is RecipeSource.MODEL
    assert recipe.source_label == "Written by test-model"
    assert card.library_id is None
    chicken, lime, garlic, salt = recipe.ingredients
    assert (chicken.quantity, chicken.unit, chicken.raw) == (1.5, Unit.LB, "1½ lb chicken thighs, boneless")
    assert (garlic.quantity, garlic.unit, garlic.raw) == (3, None, "3 garlic cloves, minced")
    assert (salt.quantity, salt.raw) == (None, "salt")
    assert lime.raw == "2 Tbsp lime juice"
    assert recipe.times.prep == "10 min"
    assert recipe.servings == "Serves 4"


async def test_a_new_recipe_with_an_unreadable_amount_or_unknown_unit_is_sent_back():
    bad_amount = {**DRAFT, "ingredients": [{"quantity": "a handful", "unit": None, "name": "rice"}, DRAFT["ingredients"][1]]}
    bad_unit = {**DRAFT, "ingredients": [{"quantity": "2", "unit": "glugs", "name": "oil"}, DRAFT["ingredients"][1]]}
    model, seen = scripted(sheet({"source": "new", "recipe": bad_amount}), sheet({"source": "new", "recipe": bad_unit}),
                           sheet({"source": "new", "recipe": DRAFT}))
    outcome = await run_pitch_turn(deps=deps(), model=model)
    assert outcome.stopped == "answered"
    assert len(seen["retries"]) == 2
    assert "not a quantity" in seen["retries"][0]
    assert "glugs" in seen["retries"][1]


async def test_new_recipes_can_be_switched_off():
    request = PitchRequest(craving="chicken", allow_new=False)
    model, seen = scripted(sheet({"source": "new", "recipe": DRAFT}), ("search_cookbook", {"query": "chicken"}),
                           sheet({"source": "cookbook", "ref": "C1"}))
    outcome = await run_pitch_turn(deps=deps(request), model=model)
    assert "new recipes are not allowed" in seen["retries"][0]
    assert "NOT allowed" in seen["instructions"]
    assert [c.recipe.title for c in outcome.cards] == ["Sunday Chicken Soup"]


async def test_web_recipes_are_marked_untrusted_and_shown_from_the_parsed_page():
    model, seen = scripted(("search_web", {"query": "fried rice"}), sheet({"source": "web", "ref": "W1"}))
    outcome = await run_pitch_turn(deps=deps(), model=model)
    [card] = outcome.cards
    assert card.recipe.source is RecipeSource.WEB
    assert card.recipe.source_url == "https://food.example/fried-rice"
    assert seen["results"][0].startswith('<untrusted source="web">')
    assert "W1 | Web Fried Rice" in seen["results"][0]


async def test_web_lookup_refuses_when_it_is_switched_off():
    model, seen = scripted(("search_web", {"query": "fried rice"}), ("search_cookbook", {"query": "lime"}),
                           sheet({"source": "cookbook", "ref": "C1"}))
    await run_pitch_turn(deps=deps(PitchRequest(craving="rice", allow_web=False)), model=model)
    assert seen["results"][0] == "Tool failed: web lookup is switched off for this request."


async def test_repeats_and_too_many_dishes_are_refused():
    model, seen = scripted(
        ("search_cookbook", {"query": ""}),
        sheet({"source": "cookbook", "ref": "C1"}, {"source": "cookbook", "ref": "C1"}),
        sheet({"source": "cookbook", "ref": "C1"}, {"source": "cookbook", "ref": "C2"}, {"source": "cookbook", "ref": "C3"}),
        sheet({"source": "cookbook", "ref": "C1"}, {"source": "cookbook", "ref": "C2"}),
    )
    outcome = await run_pitch_turn(deps=deps(PitchRequest(craving="anything", count=2)), model=model)
    assert "is a repeat" in seen["retries"][0]
    assert "the request is for 2" in seen["retries"][1]
    assert len(outcome.cards) == 2


async def test_the_step_limit_is_an_exit_not_an_exception():
    model, _ = scripted(("search_cookbook", {"query": "lime"}))             # searches forever
    outcome = await run_pitch_turn(deps=deps(), model=model, max_requests=3)
    assert outcome.stopped == "step_limit"
    assert outcome.cards == []
    assert "3 steps" in outcome.message


def test_check_sheet_is_a_pure_function_of_the_sheet_and_the_turn():
    d = deps()
    d.candidates["C1"] = cookbook_recipes()["peanut-noodles"]
    d.library_ids["C1"] = "peanut-noodles"
    good = PitchSheet.model_validate(sheet({"source": "cookbook", "ref": "c1"}))       # case-insensitive
    cards, problems = check_sheet(good, d)
    assert problems == []
    assert cards[0].library_id == "peanut-noodles"
    wrong_kind = PitchSheet.model_validate(sheet({"source": "web", "ref": "C1"}))
    assert "is not a web recipe" in check_sheet(wrong_kind, d)[1][0]
    missing = PitchSheet.model_validate(sheet({"source": "new"}))
    assert 'needs the full recipe' in check_sheet(missing, d)[1][0]


def test_avoid_matching_is_by_whole_normalised_words():
    recipes = cookbook_recipes()
    assert avoided_in(recipes["peanut-noodles"], ["Peanuts"]) == "Peanuts"
    assert avoided_in(recipes["peanut-noodles"], ["nut"]) is None                     # not a substring match
    assert avoided_in(recipes["lime-shrimp-tacos"], ["sour cream"]) == "sour cream"
    assert avoided_in(recipes["lime-shrimp-tacos"], ["pepper"]) == "pepper"           # found in an as-written line
    assert avoided_in(recipes["lime-shrimp-tacos"], []) is None


def test_the_model_cannot_set_the_source_of_a_recipe_it_wrote():
    assert "source" not in DraftRecipe.model_fields
    recipe = recipe_from_draft(DraftRecipe.model_validate(DRAFT), "some-model")
    assert recipe.source is RecipeSource.MODEL
    assert recipe.source_url is None
