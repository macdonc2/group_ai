"""Typed recipe data. Everything the Recipes mode stores, shows or hands to a model is one of
these models, validated on the way in.

The same `Recipe` holds a cookbook recipe, a recipe parsed from a web page and one a model
wrote. `source` says which, and it is set by code at the point the recipe enters the system,
never by a model, so the badge in the UI ("From the cookbook" / "Written by the model" /
"From the web") cannot be talked into lying.

Quantities are `fractions.Fraction`, stored in JSON as strings such as "3/4". A float would
turn 1/3 cup into 0.333... and scaling by 3 into 0.999 cups; a fraction scales and converts
exactly and is rounded only when it is formatted for display.
"""

from __future__ import annotations

import re
from enum import StrEnum
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from agent_system.domain.recipes.units import MAX_QUANTITY, Unit, format_quantity, unit_label

Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=40)]

CATEGORIES = ("chicken", "beef", "lamb", "pork", "seafood", "vegetarian", "dessert", "baking", "soup", "side",
              "sauce", "seasoning", "breakfast", "pasta", "salad", "drink", "other")
Category = Literal["chicken", "beef", "lamb", "pork", "seafood", "vegetarian", "dessert", "baking", "soup", "side",
                   "sauce", "seasoning", "breakfast", "pasta", "salad", "drink", "other"]


class RecipeSource(StrEnum):
    COOKBOOK = "cookbook"   # imported from the owner's cookbook file, text as printed
    MODEL = "model"         # written by a language model; nobody has cooked it
    WEB = "web"             # parsed in code from a web page's own recipe data


class Ingredient(BaseModel):
    """One ingredient line as data.

    `raw` is always the line as written and is what "as written" shows. `quantity`, `unit`
    and `name` are present when the line could be read with certainty; a line that could not
    ("1½ tsp salt, ¾ tsp pepper, divided") keeps `quantity=None` and is shown as written,
    never guessed at. `unit=None` with a quantity is a count: 4 garlic cloves, 2 cans.
    """

    model_config = ConfigDict(frozen=True)

    raw: Line
    quantity: Fraction | None = None
    quantity_max: Fraction | None = None      # the top of a range: "3-4 Tbsp"
    unit: Unit | None = None
    name: Short
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None

    @field_validator("quantity", "quantity_max")
    @classmethod
    def _positive(cls, value: Fraction | None) -> Fraction | None:
        if value is not None and not 0 < value <= MAX_QUANTITY:
            raise ValueError("a quantity must be greater than zero and not absurdly large")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Ingredient:
        if self.quantity is None and (self.unit is not None or self.quantity_max is not None):
            raise ValueError("a unit or a range needs a quantity")
        if self.quantity_max is not None and self.quantity is not None and self.quantity_max <= self.quantity:
            raise ValueError("the top of a range must be larger than the bottom")
        return self

    @property
    def measured(self) -> bool:
        return self.quantity is not None

    @property
    def unscaled_numbers(self) -> bool:
        """True for an as-written line that contains amounts the code could not read, so
        scaling the recipe leaves this line for the cook to adjust by hand."""
        return self.quantity is None and bool(re.search(r"[\d½⅓⅔¼¾⅛⅜⅝⅞]", self.raw))


def ingredient_text(quantity: Fraction | None, quantity_max: Fraction | None, unit: Unit | None, name: str,
                    note: str | None = None) -> str:
    """One display line built from structured parts: "1½ cups flour, sifted"."""
    parts: list[str] = []
    if quantity is not None:
        amount = format_quantity(quantity, unit)
        if quantity_max is not None:
            amount += "–" + format_quantity(quantity_max, unit)
        parts.append(amount)
        if unit is not None:
            parts.append(unit_label(unit, quantity_max or quantity))
    parts.append(name)
    text = " ".join(parts)
    return f"{text}, {note}" if note else text


class IngredientGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: Short | None = None                 # "Sauce", "For the crust"; None for the only group
    items: Annotated[list[Ingredient], Field(min_length=1, max_length=120)]


class RecipeTimes(BaseModel):
    model_config = ConfigDict(frozen=True)

    prep: Short | None = None
    cook: Short | None = None
    total: Short | None = None


class RecipeVariant(BaseModel):
    """An alternate method printed with the recipe (Instant Pot, slow cooker)."""

    model_config = ConfigDict(frozen=True)

    name: Short
    untested: bool = False
    steps: Annotated[list[Line], Field(max_length=60)] = []


class Recipe(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: Short
    source: RecipeSource
    source_label: Short                        # "Family Cookbook, p. 12", "example.com", "Written by gpt-6-astra"
    source_url: Annotated[str, StringConstraints(max_length=2000)] | None = None
    attribution: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    servings: Short | None = None
    times: RecipeTimes = RecipeTimes()
    category: Category = "other"
    tags: Annotated[list[Tag], Field(max_length=20)] = []
    # A recovered cookbook entry may be missing its ingredients or its method (`complete=False`,
    # with the holes listed in `gaps`), so neither list is required here. Recipes written by a
    # model or read from the web are held to a stricter rule where they are built.
    ingredient_groups: Annotated[list[IngredientGroup], Field(max_length=20)] = []
    steps: Annotated[list[Line], Field(max_length=80)] = []
    variants: Annotated[list[RecipeVariant], Field(max_length=10)] = []
    substitutions: Annotated[list[Line], Field(max_length=40)] = []
    notes: Annotated[list[Line], Field(max_length=40)] = []
    pairings: Annotated[list[Short], Field(max_length=40)] = []
    related: Annotated[list[Short], Field(max_length=40)] = []     # titles of component recipes it refers to
    complete: bool = True                      # False for a cookbook entry recovered with gaps
    gaps: Annotated[list[Line], Field(max_length=40)] = []

    @field_validator("source_url")
    @classmethod
    def _http_only(cls, value: str | None) -> str | None:
        if value is not None and not re.match(r"https?://[^\s]+$", value):
            raise ValueError("source_url must be an http(s) address")
        return value

    @property
    def ingredients(self) -> list[Ingredient]:
        return [item for group in self.ingredient_groups for item in group.items]
