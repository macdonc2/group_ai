"""Find recipes by name, dish or ingredient. Plain matching in code; no model, no embeddings.

A few hundred recipes do not need a search engine. Each recipe is reduced to four bags of
normalised words (title, ingredient names, tags, everything else) and a query is scored
against them with fixed weights, so the same query always returns the same list in the same
order and every hit can be explained ("matched in the title", "uses 3 of your 4 ingredients").
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from agent_system.domain.recipes.models import Recipe

K = TypeVar("K")

_STOP = frozenset(["a", "an", "and", "the", "or", "of", "with", "for", "in", "on", "to", "from", "my", "some", "any", "recipe", "recipes", "dish", "dishes", "food", "make", "made", "cook", "cooked", "using", "use", "something"])
_WEIGHTS = {"title": 6.0, "ingredients": 3.0, "tags": 2.0, "other": 1.0}


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("oes"):
        return word[:-2]
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokens(text: str) -> list[str]:
    """Normalised words of `text`: lower case, accents removed, plurals folded, stop words dropped."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return [_singular(w) for w in re.findall(r"[a-z0-9]+", plain) if w not in _STOP and len(w) > 1]


@dataclass(frozen=True)
class SearchDoc:
    title: frozenset[str]
    ingredients: frozenset[str]
    tags: frozenset[str]
    other: frozenset[str]

    def bags(self) -> Iterable[tuple[str, frozenset[str]]]:
        return (("title", self.title), ("ingredients", self.ingredients), ("tags", self.tags), ("other", self.other))


def build_doc(recipe: Recipe) -> SearchDoc:
    other = " ".join([recipe.attribution or "", recipe.source_label, *recipe.pairings, *recipe.related,
                      *(v.name for v in recipe.variants)])
    return SearchDoc(
        title=frozenset(tokens(recipe.title)),
        ingredients=frozenset(t for item in recipe.ingredients for t in tokens(item.name)),
        tags=frozenset(tokens(" ".join([recipe.category, *recipe.tags]))),
        other=frozenset(tokens(other)),
    )


def _hit(word: str, bag: frozenset[str]) -> bool:
    """A query word matches a bag on equality, or as the start of a word once it is three letters
    long ("chick" finds chicken while the person is still typing)."""
    return word in bag or (len(word) >= 3 and any(candidate.startswith(word) for candidate in bag))


@dataclass(frozen=True)
class SearchHit(Generic[K]):
    key: K
    recipe: Recipe
    score: float
    matched_all: bool                               # every query word was found somewhere
    have: list[str] = field(default_factory=list)   # which of the person's ingredients it uses


def search(
    entries: Iterable[tuple[K, Recipe]],
    query: str = "",
    *,
    have: Iterable[str] = (),
    category: str | None = None,
    tag: str | None = None,
    limit: int = 30,
) -> list[SearchHit[K]]:
    """Recipes matching `query` and/or using the ingredients in `have`, best first.

    With a query, a recipe must have every query word in its title, ingredients or tags to rank
    in the first tier; if none does, recipes containing any of the words anywhere are returned
    instead (`matched_all=False`). With
    only `have`, recipes are ranked by how many of those ingredients they use. With neither,
    everything that passes the category and tag filters is returned in title order.
    """
    words = list(dict.fromkeys(tokens(query)))
    wanted = [(phrase.strip(), tokens(phrase)) for phrase in have if phrase.strip()]
    wanted = [(phrase, toks) for phrase, toks in wanted if toks]
    tag_token = tokens(tag)[0] if tag and tokens(tag) else None
    hits: list[SearchHit[K]] = []
    for key, recipe in entries:
        if category and recipe.category != category:
            continue
        doc = build_doc(recipe)
        if tag_token and tag_token not in doc.tags:
            continue
        score, strong = 0.0, 0
        for word in words:
            best = max((_WEIGHTS[name] for name, bag in doc.bags() if _hit(word, bag)), default=0.0)
            score += best
            strong += best > _WEIGHTS["other"]      # a mention in the notes or pairings is not "about" the word
        used = [phrase for phrase, toks in wanted if all(_hit(t, doc.ingredients) for t in toks)]
        if (words and score == 0 and not used) or (not words and wanted and not used):
            continue
        score += 3.0 * len(used)
        hits.append(SearchHit(key=key, recipe=recipe, score=score, matched_all=strong == len(words), have=used))
    if words and any(h.matched_all for h in hits):
        hits = [h for h in hits if h.matched_all]
    hits.sort(key=lambda h: (-h.score, h.recipe.title.lower()))
    return hits[:limit]
