"""The cookbook file format, and turning it into `Recipe`s.

The file is the JSON produced from the owner's cookbooks: `{"books": [...], "recipes": [...]}`
(or one book as `{"book": {...}, "recipes": [...]}`). It is private content that is uploaded
into the database by its owner; it is never part of this repository or of the image.

The text is transcribed, not edited: titles, ingredient lines and steps are kept as printed.
The only thing added is the structured reading of each ingredient line (`parse_ingredient`),
and the printed line is kept beside it.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_system.domain.recipes.ingredients import parse_ingredient
from agent_system.domain.recipes.models import (
    CATEGORIES,
    IngredientGroup,
    Recipe,
    RecipeSource,
    RecipeTimes,
    RecipeVariant,
)

MAX_RECIPES = 2000


def _short(value: str | None, limit: int = 300) -> str | None:
    text = " ".join((value or "").split())
    return text[:limit] or None


class SeedBook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Annotated[str, Field(min_length=1, max_length=80)]
    title: Annotated[str, Field(min_length=1, max_length=300)]
    notes: str | None = None


class SeedTimes(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prep: str | None = None
    cook: str | None = None
    total: str | None = None
    raw: str | None = None


class SeedGroup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    items: list[str] = []


class SeedVariant(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    untested: bool = False
    steps: list[str] = []


class SeedRecipe(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Annotated[str, Field(min_length=1, max_length=200)]
    title: Annotated[str, Field(min_length=1, max_length=300)]
    book_id: Annotated[str, Field(min_length=1, max_length=80)]
    page: int | None = None
    attribution: str | None = None
    source_url: str | None = None
    servings: str | None = None
    times: SeedTimes = SeedTimes()
    tags: list[str] = []
    category: str = "other"
    ingredient_groups: list[SeedGroup] = []
    steps: list[str] = []
    variants: list[SeedVariant] = []
    substitutions: list[str] = []
    notes: list[str] = []
    pairings: list[str] = []
    related: list[str] = []
    completeness: str = "complete"
    gaps: list[str] = []


class SeedFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    books: list[SeedBook] = []
    recipes: Annotated[list[SeedRecipe], Field(min_length=1, max_length=MAX_RECIPES)]

    @model_validator(mode="before")
    @classmethod
    def _single_book(cls, data: object) -> object:
        if isinstance(data, dict) and "book" in data and "books" not in data:
            return {**data, "books": [data["book"]]}
        return data

    @model_validator(mode="after")
    def _unique_ids(self) -> SeedFile:
        seen: set[str] = set()
        for recipe in self.recipes:
            if recipe.id in seen:
                raise ValueError(f"recipe id {recipe.id!r} appears more than once")
            seen.add(recipe.id)
        return self


def _lines(values: list[str], limit: int = 4000) -> list[str]:
    return [text[:limit] for value in values if (text := " ".join(str(value).split()))]


def recipe_from_seed(seed: SeedRecipe, book_title: str | None) -> Recipe:
    """One cookbook entry as a `Recipe`. Raises `pydantic.ValidationError` if it does not fit."""
    groups = [
        IngredientGroup(name=_short(group.name), items=[parse_ingredient(line) for line in _lines(group.items)])
        for group in seed.ingredient_groups if _lines(group.items)
    ]
    label = book_title or seed.book_id
    if seed.page is not None:
        label = f"{label}, p. {seed.page}"
    url = seed.source_url.strip() if seed.source_url else None
    return Recipe(
        title=seed.title,
        source=RecipeSource.COOKBOOK,
        source_label=label[:300],
        source_url=url if url and url.startswith(("http://", "https://")) and " " not in url else None,
        attribution=_short(seed.attribution, 500),
        servings=_short(seed.servings),
        times=RecipeTimes(prep=_short(seed.times.prep), cook=_short(seed.times.cook),
                          total=_short(seed.times.total) or (_short(seed.times.raw) if not (seed.times.prep or seed.times.cook) else None)),
        category=seed.category if seed.category in CATEGORIES else "other",
        tags=list(dict.fromkeys(t.strip().lower()[:40] for t in seed.tags if t.strip()))[:20],
        ingredient_groups=groups[:20],
        steps=_lines(seed.steps)[:80],
        variants=[RecipeVariant(name=v.name[:300], untested=v.untested, steps=_lines(v.steps)[:60])
                  for v in seed.variants if v.name.strip()][:10],
        substitutions=_lines(seed.substitutions)[:40],
        notes=_lines(seed.notes)[:40],
        pairings=_lines(seed.pairings, 300)[:40],
        related=_lines(seed.related, 300)[:40],
        complete=seed.completeness == "complete",
        gaps=_lines(seed.gaps)[:40],
    )
