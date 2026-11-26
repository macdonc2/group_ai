"""Recipes API: import, find, pitch, keep, reopen, delete, convert, pictures, and that one
user's recipes are invisible to another.

Two users, Alice (who imports the cookbook) and Mallory (a valid account with no relationship
to Alice). The pitch model, the image model, Wikimedia and the web are replaced with
recorders, so no model or network call happens; the routes, the repository and the background
picture task are real.
"""

import json
import time
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agent_system.adapters.inbound.api import create_app
from agent_system.adapters.inbound.api.routes import recipes as recipe_routes
from agent_system.adapters.outbound.llm.recipe_agent import (
    DraftRecipe,
    PitchCard,
    PitchOutcome,
    recipe_from_draft,
)
from agent_system.adapters.outbound.recipes.dish_pictures import DishPicture, build_prompt
from agent_system.adapters.outbound.recipes.ingredient_photos import IngredientPhoto
from agent_system.adapters.outbound.recipes.web_recipes import WebRecipeError
from agent_system.composition_root.config import Settings
from agent_system.domain.recipes.jsonld import recipes_from_html
from tests.unit.recipes.samples import COOKBOOK
from tests.unit.recipes.test_recipe_agent import DRAFT, WEB_PAGE

pytestmark = pytest.mark.e2e

API = "/api/v1"
PASSWORD = "correct-horse-battery"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A running app with Alice and Mallory, and recorders in place of every model and network call."""
    from agent_system.composition_root.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()
    settings = Settings(openai_api_key="sk-test", database_url=f"sqlite+aiosqlite:///{tmp_path / 'recipes.db'}",
                        debug=False, recipe_images_per_day=2, recipe_photo_contact="https://example.org")
    calls = SimpleNamespace(pictures=[], photos=[], turns=[], web=[], fail_picture=False)

    async def fake_picture(recipe, *, api_key, model, quality):
        calls.pictures.append({"title": recipe.title, "api_key": api_key, "model": model, "quality": quality})
        if calls.fail_picture:
            raise RuntimeError("image model down")
        return DishPicture(content=JPEG, content_type="image/jpeg", prompt=build_prompt(recipe), model=model, cost_usd=0.02)

    async def fake_photos(keys, contact):
        calls.photos.append((sorted(keys), contact))
        return {
            key: None if key == "butter" else IngredientPhoto(         # no free photo for butter
                content=b"\xff\xd8photo-" + key.encode(), content_type="image/jpeg", title=f"{key}.jpg",
                author="Jo Photographer", license_name="CC BY-SA 4.0",
                license_url="https://creativecommons.org/licenses/by-sa/4.0",
                source_url=f"https://commons.wikimedia.org/wiki/File:{key}.jpg")
            for key in keys if key != "cumin"                          # cumin: download failed, no answer yet
        }

    async def fake_find_web(query):
        calls.web.append(query)
        return recipes_from_html(WEB_PAGE, "https://food.example/fried-rice")

    async def fake_fetch_web(url):
        if "blocked" in url:
            raise WebRecipeError("That site blocks automated readers.")
        return recipes_from_html(WEB_PAGE, url)

    async def fake_turn(*, deps, api_key, model_string):
        found = await deps.find_cookbook("lime", deps.request.have, None)
        calls.turns.append({"user_id": deps.user_id, "request": deps.request, "persona": deps.persona,
                            "found": [r.title for _, r in found], "web": deps.find_web is not None})
        await deps.emit("tool_result", "ChatLoop", "Tool completed: search_cookbook", {"tool_name": "search_cookbook"})
        if deps.request.craving == "break":
            return PitchOutcome(stopped="error", message="The pitch kept failing the checks.")
        cards = [PitchCard(recipe=r, hype="From the book!", library_id=lid) for lid, r in found[:1]]
        cards.append(PitchCard(recipe=recipe_from_draft(DraftRecipe.model_validate(DRAFT), "test-model"), hype="Brand new!"))
        return PitchOutcome(stopped="answered", promo="OH YEAH, the card is ready!", cards=cards,
                            steps=[{"tool": "search_cookbook"}])

    monkeypatch.setattr(recipe_routes, "make_picture", fake_picture)
    monkeypatch.setattr(recipe_routes, "fetch_photos", fake_photos)
    monkeypatch.setattr(recipe_routes, "find_web", fake_find_web)
    monkeypatch.setattr(recipe_routes, "fetch_web", fake_fetch_web)
    monkeypatch.setattr(recipe_routes, "run_turn", fake_turn)

    with TestClient(create_app(settings)) as client:
        boot = client.post(f"{API}/auth/bootstrap", json={"email": "alice@example.com", "password": PASSWORD})
        assert boot.status_code == 200, boot.text
        alice = boot.json()["access_token"]
        made = client.post(f"{API}/auth/register", json={"email": "mallory@example.com", "password": PASSWORD},
                           headers=_bearer(alice))
        assert made.status_code == 201, made.text
        mallory = client.post(f"{API}/auth/login",
                              json={"email": "mallory@example.com", "password": PASSWORD}).json()["access_token"]
        yield SimpleNamespace(client=client, alice=_bearer(alice), mallory=_bearer(mallory),
                              alice_id=boot.json()["user"]["id"], calls=calls)
    get_settings.cache_clear()


def _import(world, headers=None) -> dict:
    r = world.client.post(f"{API}/recipes/cookbooks", json=COOKBOOK, headers=headers or world.alice)
    assert r.status_code == 200, r.text
    return r.json()


def _find(world, headers=None, **params) -> list[dict]:
    r = world.client.get(f"{API}/recipes/search", params=params, headers=headers or world.alice)
    assert r.status_code == 200, r.text
    return r.json()


def _id(world, title: str) -> str:
    return next(c["id"] for c in _find(world) if c["title"] == title)


def _settled(world, recipe_id: str, headers=None) -> dict:
    """The recipe once its background picture task has finished."""
    for _ in range(200):
        detail = world.client.get(f"{API}/recipes/{recipe_id}", headers=headers or world.alice).json()
        if detail["image_status"] != "pending":
            return detail
        time.sleep(0.02)
    raise AssertionError("picture task did not finish")


def _events(response) -> list[dict]:
    return [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]


# -- the cookbook library --------------------------------------------------------


def test_importing_a_cookbook_fills_the_library_and_importing_again_updates_in_place(world):
    assert _import(world) == {"added": 3, "updated": 0, "skipped": [], "total": 3}
    tacos = _id(world, "Lime Shrimp Tacos")
    world.client.put(f"{API}/recipes/{tacos}/saved", headers=world.alice)

    assert _import(world) == {"added": 0, "updated": 3, "skipped": [], "total": 3}
    assert _id(world, "Lime Shrimp Tacos") == tacos                                   # same row
    assert [c["title"] for c in world.client.get(f"{API}/recipes/saved", headers=world.alice).json()] == ["Lime Shrimp Tacos"]

    status = world.client.get(f"{API}/recipes/status", headers=world.alice).json()
    assert status["cookbook_recipes"] == 3
    assert status["saved"] == 1
    assert status["pictures_available"] is True


def test_a_bad_cookbook_file_is_refused_whole(world):
    r = world.client.post(f"{API}/recipes/cookbooks", json={"books": [], "recipes": [{"title": "No id"}]}, headers=world.alice)
    assert r.status_code == 422
    assert world.client.post(f"{API}/recipes/cookbooks", json={"recipes": []}, headers=world.alice).status_code == 422
    assert _find(world) == []


def test_removing_the_cookbooks_keeps_what_was_kept_from_elsewhere(world):
    _import(world)
    [card] = world.client.post(f"{API}/recipes/web/search", json={"query": "fried rice"}, headers=world.alice).json()
    world.client.put(f"{API}/recipes/{card['id']}/saved", headers=world.alice)

    assert world.client.delete(f"{API}/recipes/cookbooks", headers=world.alice).status_code == 204
    assert [c["title"] for c in _find(world)] == ["Web Fried Rice"]


# -- find ------------------------------------------------------------------------


def test_search_finds_by_dish_and_by_ingredient_without_a_model(world):
    _import(world)
    assert [c["title"] for c in _find(world, q="tacos")] == ["Lime Shrimp Tacos"]
    by_ingredient = _find(world, have="lime juice, soy sauce")
    assert [(c["title"], c["uses"]) for c in by_ingredient] == [
        ("Peanut Noodles", ["lime juice", "soy sauce"]), ("Lime Shrimp Tacos", ["lime juice"])]
    assert [c["title"] for c in _find(world, category="pasta")] == ["Peanut Noodles"]
    assert _find(world, q="zebra") == []
    assert world.client.get(f"{API}/recipes/search", params={"category": "nope"}, headers=world.alice).status_code == 422
    assert world.calls.turns == []

    card = _find(world, q="tacos")[0]
    assert card["source"] == "cookbook"
    assert card["source_label"] == "Test Kitchen Vol 1, p. 12"
    assert card["saved"] is False
    assert card["ingredient_count"] == 7
    assert card["times"]["prep"] == "15 min"


def test_a_recipe_opens_with_its_text_and_structured_ingredients(world):
    _import(world)
    detail = world.client.get(f"{API}/recipes/{_id(world, 'Lime Shrimp Tacos')}", headers=world.alice).json()

    assert detail["recipe"]["steps"][1] == "Sear 2 minutes a side."
    assert detail["recipe"]["source"] == "cookbook"
    assert [g["name"] for g in detail["ingredients"]] == [None, "Slaw"]
    shrimp, oil, lime, tortillas, mixed = detail["ingredients"][0]["items"]
    assert shrimp == {**shrimp, "index": 0, "text": "1 lb large shrimp, peeled", "amount": "1", "unit": "lb",
                      "name": "large shrimp", "note": "peeled", "photo": "shrimp", "converted": False}
    assert "g" in shrimp["can_convert_to"]
    assert "cup" not in shrimp["can_convert_to"]
    assert "g" in oil["can_convert_to"]                                   # olive oil has a density on file
    assert tortillas["unit"] is None
    assert tortillas["can_convert_to"] == []
    assert tortillas["photo"] == "corn tortilla"
    assert mixed["amount"] is None
    assert mixed["photo"] is None
    assert mixed["text"] == "1½ tsp kosher salt, ¾ tsp pepper"
    assert detail["ingredients"][1]["items"][0]["index"] == 5


# -- unit conversion and scaling -----------------------------------------------------


def test_ingredients_convert_and_scale_in_code(world):
    _import(world)
    tacos = _id(world, "Lime Shrimp Tacos")

    def convert(**body):
        r = world.client.post(f"{API}/recipes/{tacos}/convert", json=body, headers=world.alice)
        assert r.status_code == 200, r.text
        return [item for group in r.json()["ingredients"] for item in group["items"]]

    metric = convert(system="metric")
    assert [i["text"] for i in metric] == [
        "455 g large shrimp, peeled", "30 ml olive oil", "15 ml lime juice", "8 corn tortillas",
        "1½ tsp kosher salt, ¾ tsp pepper", "475 ml shredded cabbage", "59 ml sour cream"]
    assert metric[0]["converted"] is True
    assert metric[3]["converted"] is False

    doubled = convert(scale="2")
    assert [i["text"] for i in doubled][:4] == ["2 lb large shrimp, peeled", "4 Tbsp olive oil", "2 Tbsp lime juice",
                                                "16 corn tortillas"]
    assert doubled[4]["not_scaled"] is True
    assert doubled[0]["not_scaled"] is False

    chosen = convert(units={"1": "tsp", "6": "g"})
    assert chosen[1]["text"] == "6 tsp olive oil"
    assert chosen[6]["text"] == "about 58 g sour cream"
    assert chosen[6]["approximate"] is True
    assert chosen[0]["text"] == "1 lb large shrimp, peeled"

    half_metric = convert(scale="1/2", system="metric", units={"0": "oz"})
    assert half_metric[0]["text"] == "8 oz large shrimp, peeled"
    assert half_metric[5]["text"] == "235 ml shredded cabbage"


def test_impossible_conversions_are_refused_with_the_reason(world):
    _import(world)
    tacos = _id(world, "Lime Shrimp Tacos")

    def status_of(**body):
        r = world.client.post(f"{API}/recipes/{tacos}/convert", json=body, headers=world.alice)
        return r.status_code, r.text

    assert status_of(units={"0": "cup"})[0] == 422  # shrimp by the cup
    assert "no density" in status_of(units={"0": "cup"})[1]
    assert status_of(units={"3": "g"})[0] == 422                                                             # tortillas are counted
    assert status_of(units={"0": "parsec"})[0] == 422
    assert status_of(scale="0")[0] == 422
    assert status_of(scale="banana")[0] == 422


# -- the saved list and pictures --------------------------------------------------------


def test_keeping_a_recipe_puts_it_on_the_list_and_makes_its_picture_once(world):
    _import(world)
    tacos = _id(world, "Lime Shrimp Tacos")

    kept = world.client.put(f"{API}/recipes/{tacos}/saved", headers=world.alice)
    assert kept.status_code == 200
    assert kept.json()["saved"] is True
    assert kept.json()["image_status"] == "pending"
    detail = _settled(world, tacos)
    assert detail["image_status"] == "done"
    assert world.calls.pictures == [{"title": "Lime Shrimp Tacos", "api_key": "sk-test", "model": "gpt-image-2.5-flare",
                                     "quality": "medium"}]

    picture = world.client.get(f"{API}/recipes/{tacos}/image", headers=world.alice)
    assert picture.status_code == 200
    assert picture.content == JPEG
    assert picture.headers["content-type"] == "image/jpeg"
    assert "private" in picture.headers["cache-control"]

    world.client.put(f"{API}/recipes/{tacos}/saved", headers=world.alice)                 # keeping again: no second picture
    world.client.post(f"{API}/recipes/{tacos}/image", headers=world.alice)
    _settled(world, tacos)
    assert len(world.calls.pictures) == 1

    saved = world.client.get(f"{API}/recipes/saved", headers=world.alice).json()
    assert [(c["title"], c["saved"], c["image_status"]) for c in saved] == [("Lime Shrimp Tacos", True, "done")]
    reopened = world.client.get(f"{API}/recipes/{tacos}", headers=world.alice).json()
    assert reopened["recipe"]["title"] == "Lime Shrimp Tacos"
    assert reopened["saved"] is True


def test_taking_a_cookbook_recipe_off_the_list_keeps_it_in_the_library(world):
    _import(world)
    tacos = _id(world, "Lime Shrimp Tacos")
    world.client.put(f"{API}/recipes/{tacos}/saved", headers=world.alice)
    _settled(world, tacos)

    assert world.client.delete(f"{API}/recipes/{tacos}/saved", headers=world.alice).status_code == 204
    assert world.client.get(f"{API}/recipes/saved", headers=world.alice).json() == []
    assert _find(world, q="tacos")[0]["saved"] is False                                  # still findable
    assert world.client.get(f"{API}/recipes/{tacos}/image", headers=world.alice).status_code == 200   # picture kept


def test_the_daily_picture_cap_is_enforced_in_code(world):
    _import(world)
    ids = [_id(world, t) for t in ("Lime Shrimp Tacos", "Peanut Noodles", "Sunday Chicken Soup")]
    for recipe_id in ids:
        world.client.put(f"{API}/recipes/{recipe_id}/saved", headers=world.alice)
        _settled(world, recipe_id)

    third = _settled(world, ids[2])
    assert len(world.calls.pictures) == 2
    assert third["image_status"] == "capped"
    assert "limit of 2" in third["image_note"]
    assert world.client.get(f"{API}/recipes/{ids[2]}/image", headers=world.alice).status_code == 404
    status = world.client.get(f"{API}/recipes/status", headers=world.alice).json()
    assert (status["pictures_today"], status["pictures_per_day"]) == (2, 2)


def test_pictures_are_only_made_for_kept_recipes(world):
    _import(world)
    tacos = _id(world, "Lime Shrimp Tacos")
    asked = world.client.post(f"{API}/recipes/{tacos}/image", headers=world.alice)
    assert asked.status_code == 409
    assert world.calls.pictures == []


def test_a_failed_picture_is_reported_and_can_be_retried(world):
    _import(world)
    tacos = _id(world, "Lime Shrimp Tacos")
    world.calls.fail_picture = True
    world.client.put(f"{API}/recipes/{tacos}/saved", headers=world.alice)
    failed = _settled(world, tacos)
    assert failed["image_status"] == "failed"
    assert "RuntimeError" in failed["image_note"]
    assert failed["saved"] is True

    world.calls.fail_picture = False
    assert world.client.post(f"{API}/recipes/{tacos}/image", headers=world.alice).status_code == 202
    assert _settled(world, tacos)["image_status"] == "done"


# -- pitch -----------------------------------------------------------------------------


def _pitch(world, headers=None, **body):
    return world.client.post(f"{API}/recipes/pitch", json=body, headers=headers or world.alice)


def test_a_pitch_streams_a_card_whose_recipes_can_be_opened_and_kept_by_id(world):
    _import(world)
    r = _pitch(world, craving="lime", have=["lime juice"], avoid=["peanuts"], persona="macho_man", allow_web=True)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _events(r)
    assert [e["event_type"] for e in events] == ["tool_result", "pitch"]

    [turn] = world.calls.turns
    assert turn["user_id"] == world.alice_id
    assert turn["persona"] == "macho_man"
    assert turn["web"] is True
    assert turn["request"].avoid == ["peanuts"]
    assert turn["request"].have == ["lime juice"]

    pitch = events[-1]["data"]
    assert pitch["promo"] == "OH YEAH, the card is ready!"
    assert pitch["tools_used"] == ["search_cookbook"]
    book, new = pitch["cards"]
    assert (book["source"], book["hype"], book["id"]) == ("cookbook", "From the book!", _id(world, book["title"]))
    assert (new["source"], new["source_label"], new["saved"]) == ("model", "Written by test-model", False)

    # The new recipe is an offer: it can be opened, but it is not on the list or in search until kept.
    opened = world.client.get(f"{API}/recipes/{new['id']}", headers=world.alice).json()
    assert opened["recipe"]["title"] == "Skillet Lime Chicken"
    assert opened["ingredients"][0]["items"][0]["unit"] == "lb"
    assert "Skillet Lime Chicken" not in [c["title"] for c in _find(world)]
    assert world.client.get(f"{API}/recipes/saved", headers=world.alice).json() == []

    world.client.put(f"{API}/recipes/{new['id']}/saved", headers=world.alice)
    _settled(world, new["id"])
    assert [c["title"] for c in world.client.get(f"{API}/recipes/saved", headers=world.alice).json()] == ["Skillet Lime Chicken"]
    assert "Skillet Lime Chicken" in [c["title"] for c in _find(world, q="chicken")]

    # Taking a model-written recipe off the list deletes it and its picture.
    assert world.client.delete(f"{API}/recipes/{new['id']}/saved", headers=world.alice).status_code == 204
    assert world.client.get(f"{API}/recipes/{new['id']}", headers=world.alice).status_code == 404
    assert world.client.get(f"{API}/recipes/{new['id']}/image", headers=world.alice).status_code == 404


def test_a_pitch_that_fails_its_checks_reports_an_error_and_stores_nothing(world):
    _import(world)
    events = _events(_pitch(world, craving="break"))
    assert events[-1]["event_type"] == "error"
    assert "failing the checks" in events[-1]["message"]
    assert len(_find(world)) == 3


def test_a_pitch_request_is_validated(world):
    assert _pitch(world, count=9).status_code == 422
    assert _pitch(world, craving="x" * 601).status_code == 422
    assert _pitch(world, have=["a"] * 31).status_code == 422
    assert _pitch(world, persona="not_a_wrestler").status_code == 200
    assert world.calls.turns[-1]["persona"] is None                        # unknown persona is dropped, not passed on


# -- the web ---------------------------------------------------------------------------


def test_web_recipes_are_offers_until_kept_and_are_not_stored_twice(world):
    [card] = world.client.post(f"{API}/recipes/web/search", json={"query": "fried rice"}, headers=world.alice).json()
    assert (card["title"], card["source"], card["source_label"], card["saved"]) == ("Web Fried Rice", "web", "food.example", False)
    [again] = world.client.post(f"{API}/recipes/web/search", json={"query": "fried rice"}, headers=world.alice).json()
    assert again["id"] == card["id"]  # looking again does not keep it
    assert again["saved"] is False
    assert _find(world) == []

    world.client.put(f"{API}/recipes/{card['id']}/saved", headers=world.alice)
    detail = _settled(world, card["id"])
    assert detail["recipe"]["source_url"] == "https://food.example/fried-rice"
    assert detail["saved"] is True
    [third] = world.client.post(f"{API}/recipes/web/search", json={"query": "fried rice"}, headers=world.alice).json()
    assert third["id"] == card["id"]
    assert third["saved"] is True


def test_a_pasted_address_is_read_or_refused_with_the_reason(world):
    ok = world.client.post(f"{API}/recipes/web/import", json={"url": "https://food.example/rice"}, headers=world.alice)
    assert ok.status_code == 200
    assert ok.json()[0]["title"] == "Web Fried Rice"
    blocked = world.client.post(f"{API}/recipes/web/import", json={"url": "https://blocked.example/x"}, headers=world.alice)
    assert blocked.status_code == 422
    assert "blocks automated readers" in blocked.json()["detail"]


# -- ingredient photos -------------------------------------------------------------------


def test_ingredient_photos_are_fetched_once_in_one_batch_and_served_with_their_credit(world):
    credits = world.client.get(f"{API}/recipes/ingredient-photos/credits",
                               params={"keys": "garlic,butter,garlic,cumin,unicorn tears"}, headers=world.alice).json()
    assert [(c["key"], c["available"]) for c in credits] == [("garlic", True), ("butter", False), ("cumin", False)]
    assert credits[0] == {"key": "garlic", "available": True, "title": "garlic.jpg", "author": "Jo Photographer",
                          "license_name": "CC BY-SA 4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0",
                          "source_url": "https://commons.wikimedia.org/wiki/File:garlic.jpg"}
    assert world.calls.photos == [(["butter", "cumin", "garlic"], "https://example.org")]      # one batch; unknown key dropped

    photo = world.client.get(f"{API}/recipes/ingredient-photos/garlic", headers=world.alice)
    assert photo.status_code == 200
    assert photo.content == b"\xff\xd8photo-garlic"
    assert world.client.get(f"{API}/recipes/ingredient-photos/butter", headers=world.alice).status_code == 404
    assert world.client.get(f"{API}/recipes/ingredient-photos/unicorn", headers=world.alice).status_code == 404

    # A second look, by anyone: definite answers (a photo, or "none exists") are remembered and not
    # asked for again; the one that had no answer is.
    world.client.get(f"{API}/recipes/ingredient-photos/credits", params={"keys": "garlic,butter,cumin"},
                     headers=world.mallory)
    assert world.calls.photos[1:] == [(["cumin"], "https://example.org")]


# -- access control ------------------------------------------------------------------------


def test_every_route_needs_a_login(world):
    for method, path in [("get", "/recipes/status"), ("get", "/recipes/search"), ("get", "/recipes/saved"),
                         ("get", "/recipes/abc"), ("get", "/recipes/abc/image"), ("put", "/recipes/abc/saved"),
                         ("delete", "/recipes/abc/saved"), ("post", "/recipes/abc/convert"), ("post", "/recipes/pitch"),
                         ("post", "/recipes/cookbooks"), ("delete", "/recipes/cookbooks"), ("post", "/recipes/web/search"),
                         ("post", "/recipes/web/import"), ("get", "/recipes/ingredient-photos/garlic"),
                         ("get", "/recipes/ingredient-photos/credits?keys=garlic")]:
        assert getattr(world.client, method)(f"{API}{path}").status_code == 401, path


def test_one_users_cookbook_list_and_pictures_are_invisible_to_another(world):
    _import(world)
    tacos = _id(world, "Lime Shrimp Tacos")
    world.client.put(f"{API}/recipes/{tacos}/saved", headers=world.alice)
    _settled(world, tacos)

    assert _find(world, headers=world.mallory) == []
    assert world.client.get(f"{API}/recipes/saved", headers=world.mallory).json() == []
    assert world.client.get(f"{API}/recipes/status", headers=world.mallory).json()["cookbook_recipes"] == 0
    for method, path, body in [("get", f"/recipes/{tacos}", None), ("get", f"/recipes/{tacos}/image", None),
                               ("put", f"/recipes/{tacos}/saved", None), ("delete", f"/recipes/{tacos}/saved", None),
                               ("post", f"/recipes/{tacos}/image", None), ("post", f"/recipes/{tacos}/convert", {})]:
        kwargs = {"json": body} if body is not None else {}
        assert getattr(world.client, method)(f"{API}{path}", headers=world.mallory, **kwargs).status_code == 404, path

    # Mallory's pitch searches Mallory's (empty) library, not Alice's.
    _pitch(world, headers=world.mallory, craving="lime")
    assert world.calls.turns[-1]["found"] == []
    # Mallory removing "her" cookbooks does not touch Alice's.
    world.client.delete(f"{API}/recipes/cookbooks", headers=world.mallory)
    assert len(_find(world)) == 3
    assert world.client.get(f"{API}/recipes/{tacos}", headers=world.alice).json()["saved"] is True
