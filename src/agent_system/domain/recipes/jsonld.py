"""Read a recipe out of a web page's own structured data. Code only; no model reads the page.

Most recipe sites publish each recipe twice: once as prose for people and once as a
`schema.org/Recipe` object in a `<script type="application/ld+json">` block for search
engines. This module reads the second. That has three consequences worth knowing:

* The recipe shown is the publisher's own ingredient list and method, field for field. No
  model paraphrased, summarised or "fixed" it, so there is nothing to hallucinate.
* A page without that block yields nothing. We do not fall back to guessing from the prose.
* The page is still untrusted input. Every string is stripped of markup, cut to a length
  limit and validated as a `Recipe`; it is only ever rendered as text.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from agent_system.domain.recipes.ingredients import parse_ingredient
from agent_system.domain.recipes.models import (
    Category,
    IngredientGroup,
    Recipe,
    RecipeSource,
    RecipeTimes,
)

_SCRIPT = re.compile(r"<script[^>]*type\s*=\s*[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script>",
                     re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]{0,2000}>")
_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:\d+(?:\.\d+)?S)?)?$", re.IGNORECASE)
MAX_BLOCK_CHARS = 400_000


def _clean(value: Any, limit: int) -> str:
    """Plain text from a JSON-LD string: entities decoded, tags and control characters removed."""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    text = html.unescape(html.unescape(str(value)))
    text = _TAG.sub(lambda m: " " if re.match(r"</?(?:br|p|li|div|ul|ol|h\d|tr|td)\b", m.group(), re.IGNORECASE) else "", text)
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    return " ".join(text.split())[:limit]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _is_recipe(node: Any) -> bool:
    return isinstance(node, dict) and any(str(t).lower().endswith("recipe") for t in _as_list(node.get("@type")))


def _walk(node: Any, depth: int = 0) -> list[dict[str, Any]]:
    """Every Recipe object in a JSON-LD document: top level, inside a list, or inside @graph."""
    if depth > 6:
        return []
    if isinstance(node, list):
        return [found for item in node[:200] for found in _walk(item, depth + 1)]
    if not isinstance(node, dict):
        return []
    if _is_recipe(node):
        return [node]
    return [found for key in ("@graph", "mainEntity", "mainEntityOfPage", "itemListElement", "item")
            for found in _walk(node.get(key), depth + 1)]


def _duration(value: Any) -> str | None:
    """ISO 8601 "PT1H30M" as "1 hr 30 min"."""
    match = _DURATION.match(_clean(value, 40))
    if not match:
        return None
    days, hours, minutes = (int(g) if g else 0 for g in match.groups())
    hours += days * 24
    hours, minutes = hours + minutes // 60, minutes % 60
    parts = ([f"{hours} hr"] if hours else []) + ([f"{minutes} min"] if minutes else [])
    return " ".join(parts) or None


def _steps(value: Any, depth: int = 0) -> list[str]:
    if depth > 4:
        return []
    out: list[str] = []
    for item in _as_list(value):
        if isinstance(item, str):
            # one string holding the whole method: split on line breaks
            out.extend(t for part in re.split(r"(?:<br\s*/?>|</p>|</li>|\n)+", item) if (t := _clean(part, 4000)))
        elif isinstance(item, dict):
            if "itemListElement" in item:                      # HowToSection
                out.extend(_steps(item.get("itemListElement"), depth + 1))
            elif text := _clean(item.get("text") or item.get("name"), 4000):
                out.append(text)
    return out


def _names(value: Any) -> list[str]:
    out = []
    for item in _as_list(value)[:5]:
        name = _clean(item.get("name") if isinstance(item, dict) else item, 120)
        if name and not name.startswith(("http://", "https://")):
            out.append(name)
    return out


def _servings(value: Any) -> str | None:
    for item in _as_list(value):
        text = _clean(item, 120)
        if text:
            return f"Serves {text}" if text.isdigit() else text
    return None


_CATEGORY_WORDS: tuple[tuple[Category, tuple[str, ...]], ...] = (
    ("dessert", ("dessert", "cake", "cookie", "brownie", "pie", "pudding", "ice cream", "cobbler", "fudge", "cupcake")),
    ("soup", ("soup", "stew", "chowder", "chili", "bisque")),
    ("salad", ("salad", "slaw")),
    ("breakfast", ("breakfast", "pancake", "waffle", "omelet", "brunch", "granola")),
    ("pasta", ("pasta", "spaghetti", "lasagna", "noodle", "macaroni", "penne", "fettuccine")),
    ("baking", ("bread", "muffin", "biscuit", "scone", "roll")),
    ("seafood", ("shrimp", "salmon", "fish", "crab", "lobster", "scallop", "tuna", "cod", "seafood")),
    ("chicken", ("chicken", "turkey")),
    ("beef", ("beef", "steak", "brisket", "burger")),
    ("pork", ("pork", "bacon", "ham", "sausage")),
    ("lamb", ("lamb",)),
    ("drink", ("cocktail", "smoothie", "drink", "lemonade")),
    ("sauce", ("sauce", "dressing", "marinade", "gravy")),
)


def guess_category(*texts: str) -> Category:
    """A category from keywords in the title and the page's own category labels. A fixed word
    list, checked in order; "other" when nothing matches."""
    blob = " ".join(texts).lower()
    for category, words in _CATEGORY_WORDS:
        if any(re.search(rf"\b{re.escape(word)}s?\b", blob) for word in words):
            return category
    return "other"


def site_name(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.") or "the web"


def recipe_from_jsonld(node: dict[str, Any], url: str) -> Recipe | None:
    """One schema.org Recipe object as a `Recipe`, or None if it lacks a name, ingredients or method."""
    title = _clean(node.get("name") or node.get("headline"), 300)
    lines = [text for item in _as_list(node.get("recipeIngredient") or node.get("ingredients"))[:120]
             if (text := _clean(item, 500))]
    steps = _steps(node.get("recipeInstructions"))[:80]
    if not title or len(lines) < 2 or not steps:
        return None
    labels = [_clean(v, 40) for v in _as_list(node.get("recipeCategory")) + _as_list(node.get("recipeCuisine"))]
    keywords = node.get("keywords")
    if isinstance(keywords, str):
        keywords = keywords.split(",")
    labels += [_clean(v, 40) for v in _as_list(keywords)]
    tags = list(dict.fromkeys(t.lower() for t in labels if t and len(t) <= 40))[:8]
    site = site_name(url)
    authors = _names(node.get("author"))
    try:
        return Recipe(
            title=title, source=RecipeSource.WEB, source_label=site, source_url=url,
            attribution=", ".join([*authors, site])[:500],
            servings=_servings(node.get("recipeYield")),
            times=RecipeTimes(prep=_duration(node.get("prepTime")), cook=_duration(node.get("cookTime")),
                              total=_duration(node.get("totalTime"))),
            category=guess_category(title, " ".join(tags[:4])),
            tags=tags,
            ingredient_groups=[IngredientGroup(items=[parse_ingredient(line) for line in lines])],
            steps=steps,
        )
    except ValidationError:
        return None


def recipes_from_html(page: str, url: str) -> list[Recipe]:
    """Every recipe a page declares in JSON-LD. An empty list when it declares none."""
    found: list[Recipe] = []
    for block in _SCRIPT.findall(page)[:20]:
        if len(block) > MAX_BLOCK_CHARS:
            continue
        try:
            data = json.loads(block.strip())
        except (ValueError, RecursionError):
            continue
        for node in _walk(data):
            recipe = recipe_from_jsonld(node, url)
            if recipe is not None and all(recipe.title != seen.title for seen in found):
                found.append(recipe)
    return found[:5]
