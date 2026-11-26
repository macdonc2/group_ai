"""Recipes API: the cookbook library, search, pitches, the saved list, unit conversion and pictures.

Access control: every route takes the signed-in user from the token and every recipe query is
filtered by that user id inside the repository. Someone else's recipe is reported as 404, the
same as one that does not exist, so ids cannot be probed. The cookbooks a user imports are
visible to that user only.

Recipe text never comes from the browser. A recipe enters the database in one of three ways,
each through a validated model: the owner's cookbook file (`SeedFile`), a web page's own
structured data (`jsonld.py`), or the pitch agent's checked output. The browser then refers to
recipes by id; "save" is a flag on a row the server already holds.

Pictures are served from here, as bytes from the database, to requests that carry the
Authorization header. The browser turns them into blob: addresses. Nothing in this mode makes
the browser load an address on another site, so the frontend's image policy is unchanged.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from agent_system.adapters.inbound.api.dependencies import (
    CurrentUserId,
    SessionDep,
    SettingsDep,
    get_database,
    user_api_key,
)
from agent_system.adapters.inbound.api.schemas import StreamEvent
from agent_system.adapters.outbound.persistence import SQLAlchemyUserRepository
from agent_system.adapters.outbound.persistence.recipe_models import (
    IngredientImageModel,
    RecipeModel,
)
from agent_system.adapters.outbound.persistence.recipe_repository import SQLAlchemyRecipeRepository
from agent_system.domain.recipes.cookbook import SeedFile, recipe_from_seed
from agent_system.domain.recipes.ingredients import (
    ShownIngredient,
    UnitSystem,
    parse_scale,
    present,
)
from agent_system.domain.recipes.models import CATEGORIES, Recipe, RecipeSource, RecipeTimes
from agent_system.domain.recipes.photo_keys import PHOTO_PAGES, photo_key
from agent_system.domain.recipes.search import search
from agent_system.domain.recipes.units import ConversionError, Unit
from agent_system.domain.value_objects import UserId

router = APIRouter(prefix="/recipes", tags=["recipes"])
logger = logging.getLogger(__name__)

OFFER_DAYS = 3            # pitched and looked-up recipes nobody kept are removed after this long
_PHOTO_BUDGET_S = 8.0     # how long one request waits for new ingredient photos

Word = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RecipeCard(BaseModel):
    """A recipe in a list: enough to show a card, not the method."""

    id: str
    title: str
    source: RecipeSource
    source_label: str
    category: str
    tags: list[str]
    servings: str | None
    times: RecipeTimes
    complete: bool
    saved: bool
    image_status: str
    ingredient_count: int
    uses: list[str] = []          # which of the person's ingredients it uses (search and pitch)
    partial_match: bool = False   # search only: it matched some of the words, not all


class IngredientLine(ShownIngredient):
    index: int                    # position in the recipe, the handle for a per-line unit choice
    raw: str                      # as printed
    photo: str | None             # key of an ingredient photo, when the fixed list has one


class IngredientGroupRead(BaseModel):
    name: str | None
    items: list[IngredientLine]


class RecipeDetail(RecipeCard):
    recipe: Recipe
    ingredients: list[IngredientGroupRead]
    image_note: str | None


class ConvertRequest(BaseModel):
    scale: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] = "1"
    system: UnitSystem = "original"
    units: Annotated[dict[int, Unit], Field(max_length=200)] = {}     # line index -> unit chosen for that line


class ConvertResponse(BaseModel):
    scale: str
    system: UnitSystem
    ingredients: list[IngredientGroupRead]


class ImportResult(BaseModel):
    added: int
    updated: int
    skipped: list[dict[str, str]]
    total: int


class StatusRead(BaseModel):
    cookbook_recipes: int
    saved: int
    categories: list[str]
    pictures_per_day: int
    pictures_today: int
    pictures_available: bool
    ingredient_photos: bool


class PitchBody(BaseModel):
    craving: Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)] = ""
    have: Annotated[list[Word], Field(max_length=30)] = []
    avoid: Annotated[list[Word], Field(max_length=30)] = []
    already_pitched: Annotated[list[Word], Field(max_length=40)] = []
    count: Annotated[int, Field(ge=1, le=5)] = 3
    allow_new: bool = True
    allow_web: bool = False
    persona: str | None = None


class WebSearchBody(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]


class WebImportBody(BaseModel):
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=2000)]


class PhotoCredit(BaseModel):
    key: str
    available: bool
    title: str | None = None
    author: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    source_url: str | None = None


# ---------------------------------------------------------------------------
# Rows to responses
# ---------------------------------------------------------------------------


def _recipe(row: RecipeModel) -> Recipe:
    return Recipe.model_validate(row.data)


def _card(row: RecipeModel, recipe: Recipe | None = None, *, uses: list[str] | None = None,
          partial_match: bool = False) -> RecipeCard:
    recipe = recipe or _recipe(row)
    return RecipeCard(
        id=row.id, title=recipe.title, source=recipe.source, source_label=recipe.source_label,
        category=recipe.category, tags=recipe.tags, servings=recipe.servings, times=recipe.times,
        complete=recipe.complete, saved=bool(row.saved), image_status=row.image_status,
        ingredient_count=len(recipe.ingredients), uses=uses or [], partial_match=partial_match,
    )


def _lines(recipe: Recipe, *, scale: Any = 1, system: UnitSystem = "original",
           units: dict[int, Unit] | None = None) -> list[IngredientGroupRead]:
    """The recipe's ingredient lines, scaled and converted by `present` (the only place that happens)."""
    factor = parse_scale(scale)
    groups, index = [], 0
    for group in recipe.ingredient_groups:
        items = []
        for item in group.items:
            shown = present(item, scale=factor, system=system, to=(units or {}).get(index))
            items.append(IngredientLine(**shown.model_dump(), index=index, raw=item.raw,
                                        photo=photo_key(item.name) if item.name != item.raw else None))
            index += 1
        groups.append(IngredientGroupRead(name=group.name, items=items))
    return groups


def _detail(row: RecipeModel) -> RecipeDetail:
    recipe = _recipe(row)
    return RecipeDetail(**_card(row, recipe).model_dump(), recipe=recipe, ingredients=_lines(recipe),
                        image_note=row.image_note)


async def _user(session: Any, user_id: str) -> Any:
    user = await SQLAlchemyUserRepository(session).get(UserId.from_string(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _row(session: Any, recipe_id: str, user_id: str) -> RecipeModel:
    row = await SQLAlchemyRecipeRepository(session).get(recipe_id, user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    return row


@asynccontextmanager
async def _own_session() -> AsyncGenerator[Any, None]:
    async with get_database().session() as session:
        yield session


# ---------------------------------------------------------------------------
# Status and the cookbook library
# ---------------------------------------------------------------------------


@router.get("/status")
async def recipes_status(current_user_id: CurrentUserId, session: SessionDep, settings: SettingsDep) -> StatusRead:
    repo = SQLAlchemyRecipeRepository(session)
    user = await _user(session, current_user_id)
    today = await repo.images_since(current_user_id, datetime.utcnow() - timedelta(hours=24))
    return StatusRead(
        cookbook_recipes=await repo.cookbook_count(current_user_id),
        saved=len(await repo.saved(current_user_id)),
        categories=list(CATEGORIES),
        pictures_per_day=settings.recipe_images_per_day,
        pictures_today=today,
        pictures_available=settings.recipe_images_per_day > 0 and bool(user_api_key(user, settings)),
        ingredient_photos=bool(settings.recipe_photo_contact),
    )


@router.post("/cookbooks")
async def import_cookbooks(payload: SeedFile, current_user_id: CurrentUserId, session: SessionDep) -> ImportResult:
    """Load a cookbook file into the caller's own library. Importing the same file again
    updates the entries in place; anything the caller saved or pictured stays as it was."""
    repo = SQLAlchemyRecipeRepository(session)
    books = {book.id: book.title for book in payload.books}
    added = updated = 0
    skipped: list[dict[str, str]] = []
    for seed in payload.recipes:
        try:
            recipe = recipe_from_seed(seed, books.get(seed.book_id))
        except ValidationError as exc:
            first = exc.errors()[0]
            skipped.append({"id": seed.id, "reason": f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"[:300]})
            continue
        if await repo.upsert_cookbook(current_user_id, seed.id[:600], seed.book_id, recipe):
            added += 1
        else:
            updated += 1
    return ImportResult(added=added, updated=updated, skipped=skipped, total=await repo.cookbook_count(current_user_id))


@router.delete("/cookbooks", status_code=status.HTTP_204_NO_CONTENT)
async def remove_cookbooks(current_user_id: CurrentUserId, session: SessionDep) -> None:
    """Remove the caller's imported cookbooks. Saved model and web recipes are kept."""
    await SQLAlchemyRecipeRepository(session).delete_cookbooks(current_user_id)


# ---------------------------------------------------------------------------
# Find
# ---------------------------------------------------------------------------


async def _search(session: Any, user_id: str, query: str, have: list[str], category: str | None, tag: str | None,
                  limit: int) -> list[Any]:
    rows = await SQLAlchemyRecipeRepository(session).library(user_id)
    return search(((row, _recipe(row)) for row in rows), query, have=have, category=category, tag=tag, limit=limit)


@router.get("/search")
async def search_recipes(
    current_user_id: CurrentUserId,
    session: SessionDep,
    q: str = Query("", max_length=200),
    have: str = Query("", max_length=600, description="Ingredients on hand, comma separated"),
    category: str | None = Query(None, max_length=40),
    tag: str | None = Query(None, max_length=40),
    limit: int = Query(40, ge=1, le=200),
) -> list[RecipeCard]:
    """Search the caller's cookbooks and saved recipes by dish, name or ingredient. No model is involved."""
    if category and category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="Unknown category")
    wanted = [part.strip() for part in have.split(",") if part.strip()][:30]
    hits = await _search(session, current_user_id, q, wanted, category, tag, limit)
    return [_card(hit.key, hit.recipe, uses=hit.have, partial_match=not hit.matched_all) for hit in hits]


async def find_web(query: str) -> list[Recipe]:
    """Recipes from the web for a query (a seam for tests)."""
    from agent_system.adapters.outbound.recipes.web_recipes import search_recipes as web_search

    return await web_search(query)


async def fetch_web(url: str) -> list[Recipe]:
    """Recipes declared by one page (a seam for tests). Raises WebRecipeError with the reason."""
    from agent_system.adapters.outbound.recipes.web_recipes import fetch_recipes

    return await fetch_recipes(url)


async def _offer(repo: SQLAlchemyRecipeRepository, user_id: str, recipe: Recipe) -> RecipeModel:
    """Store a recipe the user has been shown but has not kept. It gets an id, so the browser
    never has to send recipe text back; unkept offers are swept after a few days."""
    return await repo.add(user_id, recipe, saved=False)


async def _sweep_offers(session: Any, user_id: str) -> None:
    from sqlalchemy import delete

    cutoff = datetime.utcnow() - timedelta(days=OFFER_DAYS)
    await session.execute(delete(RecipeModel).where(
        RecipeModel.user_id == user_id, RecipeModel.saved.is_(False),
        RecipeModel.source != RecipeSource.COOKBOOK.value, RecipeModel.created_at < cutoff))


@router.post("/web/search")
async def search_the_web(payload: WebSearchBody, current_user_id: CurrentUserId, session: SessionDep) -> list[RecipeCard]:
    """Look a dish up on the web. Only pages that publish structured recipe data are returned,
    read by code, field for field. Nothing is kept unless the caller saves it."""
    found = await find_web(payload.query)
    repo = SQLAlchemyRecipeRepository(session)
    await _sweep_offers(session, current_user_id)
    return [_card(await _offer(repo, current_user_id, recipe), recipe) for recipe in found]


@router.post("/web/import")
async def import_from_web(payload: WebImportBody, current_user_id: CurrentUserId, session: SessionDep) -> list[RecipeCard]:
    """Read the recipe from one web page the caller pasted."""
    from agent_system.adapters.outbound.recipes.web_recipes import WebRecipeError

    try:
        found = await fetch_web(payload.url)
    except WebRecipeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    repo = SQLAlchemyRecipeRepository(session)
    return [_card(await _offer(repo, current_user_id, recipe), recipe) for recipe in found[:3]]


# ---------------------------------------------------------------------------
# The saved list
# ---------------------------------------------------------------------------


@router.get("/saved")
async def list_saved(current_user_id: CurrentUserId, session: SessionDep) -> list[RecipeCard]:
    return [_card(row) for row in await SQLAlchemyRecipeRepository(session).saved(current_user_id)]


@router.get("/{recipe_id}")
async def get_recipe(recipe_id: str, current_user_id: CurrentUserId, session: SessionDep) -> RecipeDetail:
    return _detail(await _row(session, recipe_id, current_user_id))


@router.put("/{recipe_id}/saved")
async def save_recipe(recipe_id: str, current_user_id: CurrentUserId, session: SessionDep,
                      settings: SettingsDep) -> RecipeDetail:
    """Keep a recipe on the caller's list. Its picture is made in the background, once."""
    row = await SQLAlchemyRecipeRepository(session).set_saved(recipe_id, current_user_id, True)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    if row.image_status in ("none", "capped", "no_key"):
        row.image_status, row.image_note = "pending", None
        await session.commit()                   # the background task reads the row from its own session
        schedule_picture(recipe_id, current_user_id, settings)
    return _detail(row)


@router.delete("/{recipe_id}/saved", status_code=status.HTTP_204_NO_CONTENT)
async def unsave_recipe(recipe_id: str, current_user_id: CurrentUserId, session: SessionDep) -> None:
    """Take a recipe off the list. A cookbook recipe stays in the library; a model-written or
    web recipe exists only because it was kept, so it is deleted with its picture."""
    repo = SQLAlchemyRecipeRepository(session)
    row = await _row(session, recipe_id, current_user_id)
    if row.source == RecipeSource.COOKBOOK.value:
        await repo.set_saved(recipe_id, current_user_id, False)
    else:
        await repo.delete(recipe_id, current_user_id)


# ---------------------------------------------------------------------------
# Unit conversion and scaling
# ---------------------------------------------------------------------------


@router.post("/{recipe_id}/convert")
async def convert_ingredients(recipe_id: str, payload: ConvertRequest, current_user_id: CurrentUserId,
                              session: SessionDep) -> ConvertResponse:
    """The recipe's ingredient lines scaled and shown in other units. Arithmetic only: exact
    fractions inside a dimension, a known density (flagged approximate) between volume and weight."""
    recipe = _recipe(await _row(session, recipe_id, current_user_id))
    try:
        scale = parse_scale(payload.scale)
        lines = _lines(recipe, scale=scale, system=payload.system, units=payload.units)
    except ConversionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    return ConvertResponse(scale=str(scale), system=payload.system, ingredients=lines)


# ---------------------------------------------------------------------------
# Dish pictures
# ---------------------------------------------------------------------------

_tasks: set[asyncio.Task] = set()
_picture_locks: dict[str, asyncio.Lock] = {}


async def make_picture(recipe: Recipe, *, api_key: str, model: str, quality: str) -> Any:
    """One generated picture of a dish (a seam for tests). Costs money: see dish_pictures.py."""
    from agent_system.adapters.outbound.recipes.dish_pictures import generate

    return await generate(recipe, api_key=api_key, model=model, quality=quality)


def schedule_picture(recipe_id: str, user_id: str, settings: Any) -> None:
    task = asyncio.get_running_loop().create_task(picture_recipe(recipe_id, user_id, settings))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def picture_recipe(recipe_id: str, user_id: str, settings: Any) -> None:
    """Make and store the picture for a recipe, or record why not. Never raises.

    One at a time per recipe. The daily cap is checked here, in code, immediately before the
    paid call, so no path (save, retry, a double click) can go past it.
    """
    async with _picture_locks.setdefault(recipe_id, asyncio.Lock()):
        try:
            async with _own_session() as session:
                repo = SQLAlchemyRecipeRepository(session)
                row = await repo.get(recipe_id, user_id)
                if row is None or await repo.get_image(recipe_id, user_id) is not None:
                    if row is not None and row.image_status != "done":
                        await repo.set_image_status(recipe_id, user_id, "done")
                        await session.commit()
                    return
                user = await SQLAlchemyUserRepository(session).get(UserId.from_string(user_id))
                api_key = user_api_key(user, settings) if user else None
                made = await repo.images_since(user_id, datetime.utcnow() - timedelta(hours=24))
                blocked = None
                if settings.recipe_images_per_day <= 0:
                    blocked = ("off", "Dish pictures are switched off.")
                elif not api_key:
                    blocked = ("no_key", "No OpenAI API key is available for pictures.")
                elif made >= settings.recipe_images_per_day:
                    blocked = ("capped", f"The limit of {settings.recipe_images_per_day} pictures in 24 hours is reached.")
                if blocked:
                    await repo.set_image_status(recipe_id, user_id, *blocked)
                    await session.commit()
                    return
                recipe = _recipe(row)

            picture = await make_picture(recipe, api_key=api_key, model=settings.recipe_image_model,
                                         quality=settings.recipe_image_quality)

            async with _own_session() as session:
                repo = SQLAlchemyRecipeRepository(session)
                if await repo.get(recipe_id, user_id) is None:      # deleted while the picture was being made
                    return
                await repo.put_image(recipe_id, user_id, content=picture.content, content_type=picture.content_type,
                                     prompt=picture.prompt, model=picture.model, cost_usd=picture.cost_usd)
                await repo.set_image_status(recipe_id, user_id, "done")
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - background work; the recipe itself is already saved
            logger.exception("recipes: picture failed for %s", recipe_id)
            try:
                async with _own_session() as session:
                    await SQLAlchemyRecipeRepository(session).set_image_status(
                        recipe_id, user_id, "failed", f"The picture could not be made ({type(exc).__name__}).")
                    await session.commit()
            except Exception:  # noqa: BLE001
                pass


@router.post("/{recipe_id}/image", status_code=status.HTTP_202_ACCEPTED)
async def request_picture(recipe_id: str, current_user_id: CurrentUserId, session: SessionDep,
                          settings: SettingsDep) -> RecipeDetail:
    """Ask for a kept recipe's picture (the retry button). Does nothing if it already has one."""
    row = await _row(session, recipe_id, current_user_id)
    if not row.saved:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Keep the recipe first; pictures are made for kept recipes.")
    if row.image_status not in ("done", "pending"):
        row.image_status, row.image_note = "pending", None
        await session.commit()
        schedule_picture(recipe_id, current_user_id, settings)
    return _detail(row)


@router.get("/{recipe_id}/image")
async def get_picture(recipe_id: str, current_user_id: CurrentUserId, session: SessionDep) -> Response:
    image = await SQLAlchemyRecipeRepository(session).get_image(recipe_id, current_user_id)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No picture")
    return Response(content=image.content, media_type=image.content_type,
                    headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


# ---------------------------------------------------------------------------
# Ingredient photos (public, freely licensed, shared by all users)
# ---------------------------------------------------------------------------

_photo_lock = asyncio.Lock()       # one conversation with Wikimedia at a time, per process


async def fetch_photos(keys: list[str], contact: str) -> dict[str, Any]:
    """Ingredient photos from Wikimedia, batched (a seam for tests)."""
    from agent_system.adapters.outbound.recipes.ingredient_photos import fetch_photos as fetch

    return await fetch(keys, contact=contact)


async def _ensure_photos(keys: list[str], contact: str) -> None:
    """Fetch and store the photos not looked up yet. Never raises. Definite answers, a photo or
    "this article has no free picture", are remembered; anything else is tried again later."""
    async with _photo_lock:
        try:
            async with _own_session() as session:
                repo = SQLAlchemyRecipeRepository(session)
                todo = [key for key in keys if await repo.get_ingredient_image(key) is None]
            if not todo:
                return
            found = await fetch_photos(todo, contact)
            async with _own_session() as session:
                repo = SQLAlchemyRecipeRepository(session)
                for key, photo in found.items():
                    if photo is None:
                        await repo.put_ingredient_image(key, status="missing")
                    else:
                        await repo.put_ingredient_image(
                            key, status="done", content=photo.content, content_type=photo.content_type,
                            title=photo.title, author=photo.author, license_name=photo.license_name,
                            license_url=photo.license_url, source_url=photo.source_url)
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - Wikimedia unreachable or rate limiting: tried again next time
            logger.warning("ingredient photos not fetched: %s: %s", type(exc).__name__, exc)


def _credit(key: str, row: IngredientImageModel | None) -> PhotoCredit:
    if row is None or row.status != "done":
        return PhotoCredit(key=key, available=False)
    return PhotoCredit(key=key, available=True, title=row.title, author=row.author, license_name=row.license_name,
                       license_url=row.license_url, source_url=row.source_url)


@router.get("/ingredient-photos/credits")
async def ingredient_photo_credits(
    current_user_id: CurrentUserId, settings: SettingsDep,
    keys: str = Query(..., max_length=4000, description="Photo keys, comma separated"),
) -> list[PhotoCredit]:
    """Which of these ingredient photos exist, with the credit each licence asks for. Photos not
    looked up yet are fetched now, within a short time budget; any still on the way are reported
    as not available and will be there on the next call."""
    wanted = list(dict.fromkeys(k for k in (part.strip() for part in keys.split(",")) if k in PHOTO_PAGES))[:80]
    async with _own_session() as session:
        repo = SQLAlchemyRecipeRepository(session)
        known = {key: await repo.get_ingredient_image(key) for key in wanted}
    missing = [key for key, row in known.items() if row is None]
    if missing and settings.recipe_photo_contact:
        task = asyncio.get_running_loop().create_task(_ensure_photos(missing, settings.recipe_photo_contact))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        await asyncio.wait([task], timeout=_PHOTO_BUDGET_S)      # if it runs late it still lands in the table
        async with _own_session() as session:
            repo = SQLAlchemyRecipeRepository(session)
            for key in missing:
                known[key] = await repo.get_ingredient_image(key)
    return [_credit(key, known[key]) for key in wanted]


@router.get("/ingredient-photos/{key}")
async def ingredient_photo(key: str, current_user_id: CurrentUserId, session: SessionDep) -> Response:
    row = await SQLAlchemyRecipeRepository(session).get_ingredient_image(key) if key in PHOTO_PAGES else None
    if row is None or row.status != "done" or not row.content:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No photo")
    return Response(content=row.content, media_type=row.content_type or "image/jpeg",
                    headers={"Cache-Control": "private, max-age=604800", "X-Content-Type-Options": "nosniff"})


# ---------------------------------------------------------------------------
# Pitch
# ---------------------------------------------------------------------------


def _model_name(model_string: str) -> str:
    return model_string.split(":", 1)[-1]


async def run_turn(*, deps: Any, api_key: str, model_string: str) -> Any:
    """One pitch (a seam for tests)."""
    from agent_system.adapters.outbound.llm.agents import _get_model
    from agent_system.adapters.outbound.llm.recipe_agent import run_pitch_turn
    from agent_system.composition_root.config import get_settings

    settings = get_settings()
    return await run_pitch_turn(deps=deps, model=_get_model(model_string, api_key),
                                max_requests=settings.chat_loop_max_requests,
                                timeout_s=max(settings.chat_loop_timeout_s, 150.0))


@router.post("/pitch")
async def pitch_recipes(payload: PitchBody, current_user_id: CurrentUserId, session: SessionDep,
                        settings: SettingsDep) -> StreamingResponse:
    """Pitch a card of dishes for what the caller fancies and has in the kitchen. Streams
    Server-Sent Events: tool_result while it searches, then `pitch` (the card) or `error`.

    A POST with the token in the Authorization header, so neither the request nor the token is
    ever in a URL.
    """
    from agent_system.adapters.outbound.llm.personas import is_valid_persona
    from agent_system.adapters.outbound.llm.recipe_agent import PitchRequest, RecipeDeps
    from agent_system.adapters.outbound.persistence.trace_repository import save_turn_trace
    from agent_system.adapters.outbound.telemetry import (
        TurnTrace,
        bind_trace,
        install_llm_capture,
        set_current_node,
    )

    user = await _user(session, current_user_id)
    api_key = user_api_key(user, settings)
    if not api_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="No OpenAI API key available. Add one under Settings → API key.")
    request = PitchRequest(**payload.model_dump(exclude={"persona"}))
    model_string = settings.recipe_pitch_model or settings.default_model

    queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()

    async def emit(event_type: str, node_name: str, text: str, data: dict | None = None) -> None:
        await queue.put(StreamEvent(event_type=event_type, node_name=node_name, message=text, data=data,
                                    timestamp=time.time()))

    async def find_cookbook(query: str, have: list[str], category: str | None) -> list[tuple[str, Recipe]]:
        async with _own_session() as own:
            hits = await _search(own, current_user_id, query, have, category, None, 12)
        return [(hit.key.id, hit.recipe) for hit in hits]

    async def run() -> None:
        trace = TurnTrace()
        trace.user_input = request.model_dump_json()
        try:
            install_llm_capture()
            deps = RecipeDeps(
                user_id=current_user_id, timezone=user.timezone or "UTC", trace=trace, emit=emit,
                persona=payload.persona if is_valid_persona(payload.persona) else None,
                request=request, find_cookbook=find_cookbook, find_web=find_web if request.allow_web else None,
                model_name=_model_name(model_string),
            )
            with bind_trace(trace):
                token = set_current_node("Recipes")
                try:
                    trace.enter_node("Recipes")
                    outcome = await run_turn(deps=deps, api_key=api_key, model_string=model_string)
                finally:
                    token.var.reset(token)
            answered = outcome.stopped == "answered"
            trace.finish(response=outcome.promo if answered else outcome.message,
                         error=None if answered else outcome.stopped)

            cards: list[dict[str, Any]] = []
            if answered:
                # Give every pitched recipe an id before announcing the card: the browser saves by id.
                async with _own_session() as own:
                    repo = SQLAlchemyRecipeRepository(own)
                    await _sweep_offers(own, current_user_id)
                    for card in outcome.cards:
                        row = await repo.get(card.library_id, current_user_id) if card.library_id else None
                        if row is None:
                            row = await _offer(repo, current_user_id, card.recipe)
                        cards.append({**_card(row, card.recipe).model_dump(mode="json"), "hype": card.hype})
                    await own.commit()
            await save_turn_trace(trace, user_id=current_user_id, conversation_id="recipes", source="recipes",
                                  database=get_database())
            if answered:
                await emit("pitch", "Recipes", "The card is ready", {
                    "promo": outcome.promo, "cards": cards, "tools_used": outcome.tools_used})
            else:
                await emit("error", "Recipes", outcome.message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("recipe pitch failed")
            await emit("error", "Recipes", f"Something went wrong ({type(exc).__name__}). Please try again.")
        finally:
            await queue.put(None)

    async def events() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(run())
        try:
            while (event := await queue.get()) is not None:
                yield event.to_sse()
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
