"""Read a printed ingredient line into structured data, and scale and convert it.

`parse_ingredient` is a small, strict reader, not a guesser. It understands the common shape

    <amount> [<unit>] <name>[, <note>]        "1½ lb baby bok choy, halved (or broccoli florets)"

and returns the line *as written* (no quantity) whenever reading it with certainty is not
possible, for example when one line holds two amounts ("1½ tsp salt, ¾ tsp pepper") or an
alternative with its own number ("3 breasts or 6 cutlets"). Scaling such a line would change
one number and not the other, which is worse than not scaling it; the UI says the line was
left alone instead.

`present` is the single place a line is scaled, converted and formatted for display.
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel

from agent_system.domain.recipes.models import Ingredient, ingredient_text
from agent_system.domain.recipes.units import (
    NUMBER_PATTERN,
    ConversionError,
    Unit,
    convert,
    density_for,
    dimension,
    format_quantity,
    natural_unit,
    normalize_numbers,
    parse_quantity,
    parse_unit,
    targets,
    unit_label,
)

_WORD_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_UNIT_WORDS = (r"fluid\s+ounces?|fluid\s+oz|fl\.?\s*oz|teaspoons?|tablespoons?|tsps?|tbsps?|tbs|cups?|pints?|pt|"
               r"quarts?|qts?|gallons?|gal|milliliters?|millilitres?|ml|liters?|litres?|l|ounces?|oz|pounds?|lbs?|"
               r"kilograms?|kg|grams?|g")
_LEAD = re.compile(
    rf"^\s*(?P<low>{NUMBER_PATTERN})(?:\s*(?:-|to)\s*(?P<high>{NUMBER_PATTERN}))?"
    rf"(?:\s*(?P<unit>{_UNIT_WORDS})\b\.?)?\s*(?:of\s+)?(?P<rest>.*)$",
    re.IGNORECASE,
)
# A second amount with a unit, outside parentheses: the line holds more than one ingredient.
_SECOND_AMOUNT = re.compile(rf"{NUMBER_PATTERN}\s*-?\s*(?:{_UNIT_WORDS})\b", re.IGNORECASE)
# Numbers that describe the ingredient rather than measure it: "1-inch pieces", "93% lean".
_DESCRIPTIVE = re.compile(
    rf"{NUMBER_PATTERN}(?:\s*(?:-|to)\s*{NUMBER_PATTERN})?\s*(?:-?\s*(?:inch(?:es)?|in\.|cm|mm)\b|%)", re.IGNORECASE)
# The same amount printed a second time in another unit: "300 g/10 oz shrimp". The first is kept.
_ALTERNATE = re.compile(rf"^\s*/\s*{NUMBER_PATTERN}\s*(?:{_UNIT_WORDS})\b\.?", re.IGNORECASE)
# A package size before the thing counted: "2 10-oz cans tomatoes" is 2 cans, each 10 oz.
_PACK_SIZE = re.compile(rf"^(?P<size>{NUMBER_PATTERN}\s*-?\s*(?:{_UNIT_WORDS}))\b\.?\s+(?P<rest>\S.*)$", re.IGNORECASE)
_PARENS = re.compile(r"\(([^()]*)\)")
_HEDGE = re.compile(r"^(?:about|approx\.?|approximately|roughly|around|~)\s*", re.IGNORECASE)


def _as_written(raw: str) -> Ingredient:
    return Ingredient(raw=raw, name=raw[:300])


def _split_name_note(rest: str) -> tuple[str, list[str]]:
    """"flour (AP or GF), for dredging" -> ("flour", ["AP or GF", "for dredging"])."""
    notes = [m.strip() for m in _PARENS.findall(rest) if m.strip()]
    plain = _PARENS.sub(" ", rest)
    plain = plain.replace("(", " ").replace(")", " ")          # an unclosed bracket in the source
    name, _, after = plain.partition(",")
    if after.strip():
        notes.append(re.sub(r"\s+", " ", after).strip(" ,"))
    name = re.sub(r"\s+", " ", name).strip(" ,;:-")
    return name, notes


def _more_than_one(outside: str, name: str) -> bool:
    """True when the text after the first amount holds another amount, so the line cannot be
    scaled or converted as one thing. `outside` is that text with parentheses removed."""
    if _SECOND_AMOUNT.search(outside):
        return True
    if re.search(r"\s\+\s*\d|\bor\s+\d|\beach\b", outside, re.IGNORECASE):
        return True
    if any(re.match(r"\s*~?\d", part) for part in outside.split(",")[1:]):    # ", 2 scallions"
        return True
    return bool(re.search(r"\d", _DESCRIPTIVE.sub(" ", name)))


def parse_ingredient(raw: str) -> Ingredient:
    """Structured form of one ingredient line. Never raises for odd text: a line that cannot be
    read with certainty comes back as written."""
    raw = re.sub(r"\s+", " ", raw).strip()[:4000]
    if not raw:
        raise ValueError("an ingredient line cannot be empty")
    text = normalize_numbers(raw).replace("–", "-").replace("—", "-")
    extra_notes: list[str] = []
    if re.match(r"optional\s+\d", text, re.IGNORECASE):
        text, extra_notes = text.split(" ", 1)[1], ["optional"]
    text = _HEDGE.sub("", text)

    first = text.split(" ", 1)
    if first[0].lower() in _WORD_NUMBERS and len(first) == 2 and not re.match(r"(pinch|dash|few|little|bit|couple)\b", first[1], re.IGNORECASE):
        text = f"{_WORD_NUMBERS[first[0].lower()]} {first[1]}"

    match = _LEAD.match(text)
    if match is None:
        name, notes = _split_name_note(text)
        if not name or re.search(r"\d", name):
            return _as_written(raw)
        return Ingredient(raw=raw, name=name[:300], note="; ".join(notes)[:500] or None)

    rest = match["rest"]
    if match["unit"]:
        rest = _ALTERNATE.sub("", rest)
    elif (pack := _PACK_SIZE.match(rest)) and not match["high"]:
        rest, extra_notes = pack["rest"], [*extra_notes, re.sub(r"\s+", " ", pack["size"]) + " each"]
    rest = rest.strip()
    if rest[:1] in "-/%+" or not rest:                        # "10-oz can", "1/2 oz/14 g": not a plain amount
        return _as_written(raw)
    name, notes = _split_name_note(rest)
    if not name or _more_than_one(_PARENS.sub(" ", rest), name):
        return _as_written(raw)
    try:
        low = parse_quantity(match["low"])
        high = parse_quantity(match["high"]) if match["high"] else None
    except ValueError:
        return _as_written(raw)
    if high is not None and high <= low:
        return _as_written(raw)
    unit = parse_unit(match["unit"]) if match["unit"] else None
    if match["unit"] and unit is None:
        return _as_written(raw)
    return Ingredient(raw=raw, quantity=low, quantity_max=high, unit=unit, name=name[:300],
                      note="; ".join([*notes, *extra_notes])[:500] or None)


# ---------------------------------------------------------------------------
# Scaling, converting and display
# ---------------------------------------------------------------------------

UnitSystem = Literal["original", "us", "metric"]


class ShownIngredient(BaseModel):
    """One ingredient line ready to display, after scaling and conversion."""

    text: str                         # the whole line: "355 ml chicken broth, warmed"
    amount: str | None                # "355" / "1½–2"; None for an as-written line
    unit: Unit | None                 # the unit shown
    unit_label: str | None            # "ml", "cups"
    name: str
    note: str | None
    converted: bool                   # shown in a different unit from the one written
    approximate: bool                 # a density was used (volume <-> weight)
    not_scaled: bool                  # the recipe was scaled but this line could not be
    can_convert_to: list[Unit]        # units this line can be switched to


def present(item: Ingredient, *, scale: Fraction = Fraction(1), system: UnitSystem = "original",
            to: Unit | None = None) -> ShownIngredient:
    """Scale `item`, convert it and format it. `to` (one line's own choice) wins over `system`.

    Raises ConversionError if `to` is not a unit this line can be shown in.
    """
    if scale <= 0:
        raise ConversionError("scale must be greater than zero")
    if item.quantity is None:
        if to is not None:
            raise ConversionError("this line has no amount the code could read, so it cannot be converted")
        return ShownIngredient(text=item.raw, amount=None, unit=None, unit_label=None, name=item.name, note=item.note,
                               converted=False, approximate=False, can_convert_to=[],
                               not_scaled=scale != 1 and item.unscaled_numbers)

    low, high, unit = item.quantity * scale, (item.quantity_max * scale if item.quantity_max else None), item.unit
    density = density_for(item.name) if unit is not None else None
    choices = targets(unit, density) if unit is not None else []
    approximate = False
    if unit is not None:
        target: Unit | None = to
        if target is None and system != "original":
            target = natural_unit(high or low, unit, system).unit
        if target is not None and target != unit:
            if target not in choices:
                raise ConversionError(f"{item.name}: {unit.value} cannot be shown as {target.value}"
                                      + ("" if dimension(target) == dimension(unit) or density else
                                         " (no density on file for this ingredient)"))
            done = convert(low, unit, target, density)
            low, approximate = done.quantity, done.approximate
            high = convert(high, unit, target, density).quantity if high is not None else None
            unit = target
    elif to is not None:
        raise ConversionError(f"{item.name} is counted, not measured, so it has no unit to convert")

    amount = format_quantity(low, unit) + (f"–{format_quantity(high, unit)}" if high is not None else "")
    if item.unit == unit and scale == 1:
        text = item.raw                                    # untouched: show exactly what was printed
    else:
        text = ("about " if approximate else "") + ingredient_text(low, high, unit, item.name, item.note)
    return ShownIngredient(
        text=text, amount=amount, unit=unit, unit_label=unit_label(unit, high or low) if unit else None,
        name=item.name, note=item.note, converted=unit != item.unit, approximate=approximate, not_scaled=False,
        can_convert_to=[u for u in choices if u != unit],
    )


def parse_scale(value: str | int | float | Fraction | None) -> Fraction:
    """A scale factor from "2", "1/2", 0.5 ... limited to a sane kitchen range."""
    if value is None or value == "":
        return Fraction(1)
    try:
        scale = value if isinstance(value, Fraction) else parse_quantity(str(value))
    except ValueError:
        raise ConversionError(f"{value!r} is not a scale (use a number such as 2 or 1/2)") from None
    if not Fraction(1, 16) <= scale <= 64:
        raise ConversionError("scale must be between 1/16 and 64")
    return scale
