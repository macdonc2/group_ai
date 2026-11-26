"""The cookbook file becomes typed recipes, and search over them is deterministic."""

import pytest
from pydantic import ValidationError

from agent_system.domain.recipes.cookbook import SeedFile, recipe_from_seed
from agent_system.domain.recipes.models import Recipe, RecipeSource
from agent_system.domain.recipes.search import search, tokens
from agent_system.domain.recipes.units import Unit
from tests.unit.recipes.samples import COOKBOOK, cookbook_recipes

pytestmark = pytest.mark.unit


def test_a_cookbook_entry_keeps_its_text_and_gains_structure():
    tacos = cookbook_recipes()["lime-shrimp-tacos"]
    assert tacos.source is RecipeSource.COOKBOOK
    assert tacos.source_label == "Test Kitchen Vol 1, p. 12"
    assert tacos.title == "Lime Shrimp Tacos"
    assert tacos.category == "seafood"
    assert tacos.complete is True
    assert [g.name for g in tacos.ingredient_groups] == [None, "Slaw"]
    shrimp = tacos.ingredients[0]
    assert (shrimp.raw, shrimp.quantity, shrimp.unit, shrimp.name, shrimp.note) == (
        "1 lb large shrimp, peeled", 1, Unit.LB, "large shrimp", "peeled")
    assert tacos.ingredients[4].quantity is None                 # two amounts on one line: kept as written
    assert tacos.steps[1] == "Sear 2 minutes a side."
    assert tacos.variants[0].untested is True


def test_unknown_categories_and_gaps_are_handled():
    soup = cookbook_recipes()["chicken-soup"]
    assert soup.category == "other"
    assert soup.complete is False
    assert soup.gaps == ["Seasoning amounts were not recorded."]
    assert soup.source_label == "Test Kitchen Vol 1"
    assert soup.source_url is None


def test_a_recipe_round_trips_through_json():
    for recipe in cookbook_recipes().values():
        assert Recipe.model_validate(recipe.model_dump(mode="json")) == recipe


def test_a_single_book_file_is_accepted_and_duplicate_ids_are_not():
    one = SeedFile.model_validate({"book": COOKBOOK["books"][0], "recipes": COOKBOOK["recipes"][:1]})
    assert [b.id for b in one.books] == ["test-kitchen"]
    with pytest.raises(ValidationError, match="more than once"):
        SeedFile.model_validate({"books": [], "recipes": [COOKBOOK["recipes"][0], COOKBOOK["recipes"][0]]})
    with pytest.raises(ValidationError):
        SeedFile.model_validate({"books": [], "recipes": []})


def test_the_source_cannot_be_anything_but_the_three_kinds():
    data = cookbook_recipes()["peanut-noodles"].model_dump(mode="json")
    with pytest.raises(ValidationError):
        Recipe.model_validate({**data, "source": "michelin"})
    with pytest.raises(ValidationError, match="http"):
        Recipe.model_validate({**data, "source_url": "javascript:alert(1)"})


def test_seed_without_book_title_falls_back_to_the_book_id():
    seed = SeedFile.model_validate(COOKBOOK).recipes[1]
    assert recipe_from_seed(seed, None).source_label == "test-kitchen, p. 20"


# ---- search ---------------------------------------------------------------


def _entries():
    return list(cookbook_recipes().items())


def _keys(hits):
    return [h.key for h in hits]


def test_tokens_fold_case_accents_and_plurals():
    assert tokens("Jalapeños & Tomatoes") == ["jalapeno", "tomato"]
    assert tokens("the Cherries of Dishes") == ["cherry"]


def test_title_matches_rank_above_ingredient_matches():
    assert _keys(search(_entries(), "shrimp")) == ["lime-shrimp-tacos"]
    assert _keys(search(_entries(), "lime")) == ["lime-shrimp-tacos", "peanut-noodles"]      # title, then ingredient
    assert _keys(search(_entries(), "noodle")) == ["peanut-noodles"]


def test_every_word_must_match_unless_nothing_does():
    assert _keys(search(_entries(), "lime noodles")) == ["peanut-noodles"]
    loose = search(_entries(), "shrimp soup")                     # no recipe has both
    assert set(_keys(loose)) == {"lime-shrimp-tacos", "chicken-soup"}
    assert not any(h.matched_all for h in loose)
    assert search(_entries(), "zebra") == []


def test_a_mention_in_the_pairings_does_not_count_as_a_full_match():
    # "rice" is only a pairing of the tacos; "shrimp rice" must not shrink the results to that one recipe
    hits = search(_entries(), "shrimp rice")
    assert _keys(hits) == ["lime-shrimp-tacos"]
    assert hits[0].matched_all is False
    assert _keys(search(_entries(), "rice")) == ["lime-shrimp-tacos"]          # still findable by it


def test_typing_a_prefix_finds_the_word():
    assert _keys(search(_entries(), "chick")) == ["chicken-soup"]


def test_ingredients_on_hand_rank_by_how_many_are_used():
    hits = search(_entries(), have=["lime juice", "soy sauce", "kale"])
    assert _keys(hits) == ["peanut-noodles", "lime-shrimp-tacos"]
    assert hits[0].have == ["lime juice", "soy sauce"]
    assert hits[1].have == ["lime juice"]


def test_filters_and_browsing():
    assert _keys(search(_entries(), category="pasta")) == ["peanut-noodles"]
    assert _keys(search(_entries(), tag="healthy")) == ["lime-shrimp-tacos", "chicken-soup"]     # title order
    assert len(search(_entries())) == 3
    assert len(search(_entries(), limit=2)) == 2


def test_search_is_deterministic():
    first = [(h.key, h.score) for h in search(_entries(), "lime", have=["cabbage"])]
    assert first == [(h.key, h.score) for h in search(reversed(_entries()), "lime", have=["cabbage"])]
