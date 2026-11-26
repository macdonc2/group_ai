"""Kitchen units and the arithmetic between them. No model is ever asked to convert.

Everything here is exact rational arithmetic (`fractions.Fraction`):

* US volume units are defined from the US gallon, which is exactly 231 cubic inches,
  that is 3.785411784 litres. So 1 cup = 48 tsp exactly and 1 tsp = 4.92892159375 ml exactly.
* 1 lb is exactly 453.59237 g, and 1 oz is one sixteenth of that.

Two things are *not* exact, and the code says so instead of hiding it:

* **Volume <-> weight needs a density.** A cup of flour and a cup of honey do not weigh the
  same. `density_for(name)` knows a short list of common ingredients; for anything else the
  conversion is simply not offered. A result that used a density is flagged `approximate`.
* **Display rounding.** "0.4928 cups" is useless at a counter. `format_quantity` snaps to the
  fractions a measuring set has (1/8, 1/4, 1/3, 1/2 ...) for US units and to sensible steps
  for metric. The stored quantity is never rounded; only the text shown is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from typing import Literal


class Unit(StrEnum):
    TSP = "tsp"
    TBSP = "tbsp"
    FL_OZ = "fl_oz"
    CUP = "cup"
    PINT = "pint"
    QUART = "quart"
    GALLON = "gallon"
    ML = "ml"
    L = "l"
    OZ = "oz"
    LB = "lb"
    G = "g"
    KG = "kg"


Dimension = Literal["volume", "weight"]
System = Literal["us", "metric"]

_US_GALLON_ML = Fraction("3785.411784")   # 231 cubic inches, exact
_LB_G = Fraction("453.59237")             # international avoirdupois pound, exact

# One unit expressed in the base unit of its dimension: millilitres or grams.
_TO_BASE: dict[Unit, Fraction] = {
    Unit.TSP: _US_GALLON_ML / 768,
    Unit.TBSP: _US_GALLON_ML / 256,
    Unit.FL_OZ: _US_GALLON_ML / 128,
    Unit.CUP: _US_GALLON_ML / 16,
    Unit.PINT: _US_GALLON_ML / 8,
    Unit.QUART: _US_GALLON_ML / 4,
    Unit.GALLON: _US_GALLON_ML,
    Unit.ML: Fraction(1),
    Unit.L: Fraction(1000),
    Unit.OZ: _LB_G / 16,
    Unit.LB: _LB_G,
    Unit.G: Fraction(1),
    Unit.KG: Fraction(1000),
}

_DIMENSION: dict[Unit, Dimension] = {
    **dict.fromkeys((Unit.TSP, Unit.TBSP, Unit.FL_OZ, Unit.CUP, Unit.PINT, Unit.QUART, Unit.GALLON, Unit.ML, Unit.L), "volume"),
    **dict.fromkeys((Unit.OZ, Unit.LB, Unit.G, Unit.KG), "weight"),
}

_SYSTEM: dict[Unit, System] = {
    **dict.fromkeys((Unit.TSP, Unit.TBSP, Unit.FL_OZ, Unit.CUP, Unit.PINT, Unit.QUART, Unit.GALLON, Unit.OZ, Unit.LB), "us"),
    **dict.fromkeys((Unit.ML, Unit.L, Unit.G, Unit.KG), "metric"),
}

VOLUME_UNITS: tuple[Unit, ...] = tuple(u for u in Unit if _DIMENSION[u] == "volume")
WEIGHT_UNITS: tuple[Unit, ...] = tuple(u for u in Unit if _DIMENSION[u] == "weight")

# How a unit is written next to a number: (singular, plural).
_LABELS: dict[Unit, tuple[str, str]] = {
    Unit.TSP: ("tsp", "tsp"),
    Unit.TBSP: ("Tbsp", "Tbsp"),
    Unit.FL_OZ: ("fl oz", "fl oz"),
    Unit.CUP: ("cup", "cups"),
    Unit.PINT: ("pint", "pints"),
    Unit.QUART: ("quart", "quarts"),
    Unit.GALLON: ("gallon", "gallons"),
    Unit.ML: ("ml", "ml"),
    Unit.L: ("L", "L"),
    Unit.OZ: ("oz", "oz"),
    Unit.LB: ("lb", "lb"),
    Unit.G: ("g", "g"),
    Unit.KG: ("kg", "kg"),
}

# What people type, and what cookbooks print. Looked up lower-cased with a trailing "." removed.
_ALIASES: dict[str, Unit] = {
    "tsp": Unit.TSP, "tsps": Unit.TSP, "teaspoon": Unit.TSP, "teaspoons": Unit.TSP,
    "tbsp": Unit.TBSP, "tbsps": Unit.TBSP, "tbs": Unit.TBSP, "tablespoon": Unit.TBSP, "tablespoons": Unit.TBSP,
    "fl oz": Unit.FL_OZ, "fl_oz": Unit.FL_OZ, "floz": Unit.FL_OZ, "fluid ounce": Unit.FL_OZ,
    "fluid ounces": Unit.FL_OZ, "fluid oz": Unit.FL_OZ,
    "cup": Unit.CUP, "cups": Unit.CUP,
    "pt": Unit.PINT, "pint": Unit.PINT, "pints": Unit.PINT,
    "qt": Unit.QUART, "qts": Unit.QUART, "quart": Unit.QUART, "quarts": Unit.QUART,
    "gal": Unit.GALLON, "gallon": Unit.GALLON, "gallons": Unit.GALLON,
    "ml": Unit.ML, "milliliter": Unit.ML, "milliliters": Unit.ML, "millilitre": Unit.ML, "millilitres": Unit.ML,
    "l": Unit.L, "liter": Unit.L, "liters": Unit.L, "litre": Unit.L, "litres": Unit.L,
    "oz": Unit.OZ, "ounce": Unit.OZ, "ounces": Unit.OZ,
    "lb": Unit.LB, "lbs": Unit.LB, "pound": Unit.LB, "pounds": Unit.LB,
    "g": Unit.G, "gram": Unit.G, "grams": Unit.G,
    "kg": Unit.KG, "kilogram": Unit.KG, "kilograms": Unit.KG,
}


class ConversionError(ValueError):
    """The conversion asked for cannot be done (and why)."""


def dimension(unit: Unit) -> Dimension:
    return _DIMENSION[unit]


def system_of(unit: Unit) -> System:
    return _SYSTEM[unit]


def parse_unit(text: str) -> Unit | None:
    """The unit a word stands for ("Tbsp", "tablespoons", "fl oz"), or None."""
    return _ALIASES.get(re.sub(r"\s+", " ", text.strip().lower().rstrip(".")))


def unit_label(unit: Unit, quantity: Fraction | None = None) -> str:
    singular, plural = _LABELS[unit]
    return singular if quantity is not None and quantity <= 1 else plural


# ---------------------------------------------------------------------------
# Densities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Density:
    """Grams in one US cup of an ingredient, with the words that must not be near it."""

    grams_per_cup: Fraction
    not_with: frozenset[str] = frozenset()

    @property
    def grams_per_ml(self) -> Fraction:
        return self.grams_per_cup / _TO_BASE[Unit.CUP]


def _d(grams_per_cup: int, *not_with: str) -> Density:
    return Density(Fraction(grams_per_cup), frozenset(not_with))


# Grams per US cup, from the USDA FoodData Central household measures (rounded to the gram).
# The key must be the *end* of the ingredient name ("all-purpose flour" ends in "flour";
# "flour tortillas" does not), and the longest matching key wins ("brown sugar" over "sugar").
# Deliberately absent: salt. A cup of Diamond Crystal kosher salt weighs about 135 g and a cup
# of Morton about 240 g, and recipes rarely say which, so any single number would be wrong.
_COOKED = ("cooked", "leftover", "steamed", "prepared")
DENSITIES: dict[str, Density] = {
    "water": _d(237, "chestnuts", "chestnut"),
    "broth": _d(240), "stock": _d(240),
    "milk": _d(244, "condensed", "evaporated", "powdered", "dry", "malted"),
    "buttermilk": _d(245),
    "coconut milk": _d(240), "almond milk": _d(240), "oat milk": _d(240),
    "sweetened condensed milk": _d(306), "evaporated milk": _d(252),
    "half-and-half": _d(242), "half and half": _d(242),
    "cream": _d(238, "ice", "cheese", "soup", "tartar"),
    "heavy cream": _d(238), "whipping cream": _d(238), "light cream": _d(240),
    "sour cream": _d(230), "yogurt": _d(245), "greek yogurt": _d(245),
    "cream cheese": _d(232),
    "butter": _d(227, "lettuce", "beans", "bean", "nut", "cashew", "sunflower", "apple", "cocoa", "cookie"),
    "peanut butter": _d(258), "almond butter": _d(250),
    "oil": _d(218), "olive oil": _d(216),
    "flour": _d(125, "almond", "coconut", "rice", "corn", "tapioca", "chickpea", "oat", "masa"),
    "all-purpose flour": _d(125), "all purpose flour": _d(125), "ap flour": _d(125),
    "bread flour": _d(137), "whole wheat flour": _d(120), "almond flour": _d(96),
    "sugar": _d(200, "coconut", "palm", "snap", "maple", "pearl"),
    "granulated sugar": _d(200), "white sugar": _d(200),
    "brown sugar": _d(220), "powdered sugar": _d(120), "confectioners sugar": _d(120),
    "confectioners' sugar": _d(120), "icing sugar": _d(120),
    "honey": _d(339, "mustard"), "maple syrup": _d(315), "molasses": _d(337), "corn syrup": _d(341),
    "rice": _d(185, *_COOKED, "wild", "cauliflower", "arborio"),
    "white rice": _d(185, *_COOKED), "long-grain rice": _d(185, *_COOKED), "jasmine rice": _d(185, *_COOKED),
    "basmati rice": _d(185, *_COOKED), "brown rice": _d(185, *_COOKED),
    "rolled oats": _d(81), "old-fashioned oats": _d(81),
    "cornstarch": _d(128), "cocoa powder": _d(86), "cornmeal": _d(157),
    "breadcrumbs": _d(108, "panko"), "bread crumbs": _d(108, "panko"), "panko": _d(60),
    "soy sauce": _d(255), "vinegar": _d(239), "lemon juice": _d(244), "lime juice": _d(242),
    "orange juice": _d(248), "wine": _d(236), "ketchup": _d(240), "mayonnaise": _d(220),
    "tomato paste": _d(262), "tomato sauce": _d(245), "salsa": _d(259),
    "grated parmesan": _d(100), "parmesan": _d(100, "wedge", "rind", "block"),
}

_NAME_WORD = re.compile(r"[a-z'-]+")


def _words(name: str) -> list[str]:
    cleaned = re.sub(r"\([^)]*\)", " ", name.lower()).replace("’", "'")
    return _NAME_WORD.findall(cleaned.split(",", 1)[0])


def density_for(name: str) -> Density | None:
    """The density of a named ingredient, or None when it is not one we know well enough.

    Matching is deliberately strict. A wrong density silently gives a wrong weight, so a miss
    ("not offered") is the safe failure and a loose match is the dangerous one.
    """
    words = _words(name)
    if not words:
        return None
    for start in range(len(words)):                       # longest suffix first
        found = DENSITIES.get(" ".join(words[start:]))
        if found is not None:
            return None if found.not_with & set(words[:start]) else found
    return None


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Converted:
    quantity: Fraction
    unit: Unit
    approximate: bool = False   # True when a density was used


def convert(quantity: Fraction, unit: Unit, to: Unit, density: Density | None = None) -> Converted:
    """`quantity` of `unit` expressed in `to`. Exact within a dimension; crossing between
    volume and weight needs `density` and is marked approximate."""
    if unit == to:
        return Converted(quantity, to)
    base = quantity * _TO_BASE[unit]                      # ml or g
    if _DIMENSION[unit] == _DIMENSION[to]:
        return Converted(base / _TO_BASE[to], to)
    if density is None:
        raise ConversionError(f"{unit.value} to {to.value} needs a density, and this ingredient has none on file")
    other = base * density.grams_per_ml if _DIMENSION[unit] == "volume" else base / density.grams_per_ml
    return Converted(other / _TO_BASE[to], to, approximate=True)


def targets(unit: Unit, density: Density | None = None) -> list[Unit]:
    """Every unit a quantity in `unit` can be shown in: the same dimension always, the other
    one only when the ingredient's density is known."""
    same = VOLUME_UNITS if _DIMENSION[unit] == "volume" else WEIGHT_UNITS
    other = WEIGHT_UNITS if _DIMENSION[unit] == "volume" else VOLUME_UNITS
    return list(same) + (list(other) if density is not None else [])


# The unit a cook would reach for, by size. Each ladder is (unit, smallest quantity of that
# unit worth using); the first rung that fits, reading from the largest, is chosen.
_LADDERS: dict[tuple[System, Dimension], tuple[tuple[Unit, Fraction], ...]] = {
    ("us", "volume"): ((Unit.GALLON, Fraction(1)), (Unit.QUART, Fraction(1)), (Unit.CUP, Fraction(1, 4)),
                       (Unit.TBSP, Fraction(1)), (Unit.TSP, Fraction(0))),
    ("us", "weight"): ((Unit.LB, Fraction(1)), (Unit.OZ, Fraction(0))),
    ("metric", "volume"): ((Unit.L, Fraction(1)), (Unit.ML, Fraction(0))),
    ("metric", "weight"): ((Unit.KG, Fraction(1)), (Unit.G, Fraction(0))),
}


def natural_unit(quantity: Fraction, unit: Unit, system: System) -> Converted:
    """The same amount in the most natural unit of `system`, staying in its dimension:
    3 tsp becomes 1 Tbsp, 16 Tbsp becomes 1 cup, 1500 ml becomes 1.5 L, 1 cup becomes 237 ml.

    For US units a rung is preferred when the amount is exactly a measuring-set fraction
    there: 5 Tbsp stays "5 Tbsp" rather than becoming "0.31 cups". When no rung is exact
    (an amount that came from metric), the largest fitting rung is used as it is.
    """
    fitting = [c for rung, minimum in _LADDERS[(system, _DIMENSION[unit])]
               if (c := convert(quantity, unit, rung)).quantity >= minimum]
    if system == "us":
        for candidate in fitting:
            if candidate.quantity % 1 in _KITCHEN_STEPS:
                return candidate
    return fitting[0]   # every ladder ends at a rung with no minimum, so this is never empty


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

_GLYPHS = {
    Fraction(1, 8): "⅛", Fraction(1, 4): "¼", Fraction(1, 3): "⅓", Fraction(3, 8): "⅜", Fraction(1, 2): "½",
    Fraction(5, 8): "⅝", Fraction(2, 3): "⅔", Fraction(3, 4): "¾", Fraction(7, 8): "⅞",
}
_KITCHEN_STEPS = sorted({Fraction(n, d) for d in (2, 3, 4, 8) for n in range(d + 1)})
_SNAP_TOLERANCE = Fraction(3, 100)   # show a kitchen fraction when it is within 3% of the true amount


def _decimal(value: Fraction, places: int) -> str:
    text = f"{float(value):.{places}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _round_to(value: Fraction, step: Fraction) -> Fraction:
    return Fraction(round(value / step)) * step


def _snap(quantity: Fraction) -> Fraction | None:
    """The measuring-set amount within 3% of `quantity` (2, 1 1/2, 3/4 ...), or None."""
    if quantity <= 0:
        return None
    whole = quantity.numerator // quantity.denominator
    snapped = whole + min(_KITCHEN_STEPS, key=lambda step: abs(step - (quantity - whole)))
    return snapped if snapped > 0 and abs(snapped - quantity) <= quantity * _SNAP_TOLERANCE else None


def format_fraction(quantity: Fraction) -> str:
    """A quantity as a cook writes it: "1½", "¾", "2". Falls back to a decimal when no
    measuring-set fraction is within 3%."""
    if quantity <= 0:
        return "0"
    snapped = _snap(quantity)
    if snapped is None:
        return _decimal(quantity, 2 if quantity < 10 else 1)
    whole = snapped.numerator // snapped.denominator
    rest = snapped - whole
    return str(whole) if rest == 0 else f"{whole or ''}{_GLYPHS[rest]}"


def format_quantity(quantity: Fraction, unit: Unit | None) -> str:
    """The number to show for `quantity` of `unit` (None = a count: eggs, cloves, cans)."""
    if unit is None or _SYSTEM[unit] == "us":
        return format_fraction(quantity)
    if unit in (Unit.L, Unit.KG):
        return _decimal(quantity, 2)
    # grams and millilitres: no false precision
    if quantity >= 100:
        return _decimal(_round_to(quantity, Fraction(5)), 0)
    if quantity >= 10:
        return _decimal(_round_to(quantity, Fraction(1)), 0)
    if quantity >= 1:
        return _decimal(_round_to(quantity, Fraction(1, 2)), 1)
    return _decimal(quantity, 2)


# ---------------------------------------------------------------------------
# Reading quantities
# ---------------------------------------------------------------------------

_VULGAR = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5",
    "⅙": "1/6", "⅚": "5/6", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
}
NUMBER_PATTERN = r"(?:\d+\s+\d+\s*/\s*\d+|\d+\s*/\s*\d+|\d+(?:\.\d+)?|\.\d+)"
MAX_QUANTITY = Fraction(100_000)


def normalize_numbers(text: str) -> str:
    """"1½" -> "1 1/2", "⅓" -> "1/3", and the fraction slash to "/", so one pattern reads them all."""
    out = text.replace("⁄", "/")
    for glyph, plain in _VULGAR.items():
        out = re.sub(rf"(\d)\s*{glyph}", rf"\1 {plain}", out).replace(glyph, plain)
    return out


def parse_quantity(text: str) -> Fraction:
    """Read one amount: "2", "1 1/2", "3/4", "0.25", "1½". Raises ValueError for anything else."""
    cleaned = normalize_numbers(str(text)).strip()
    if not re.fullmatch(NUMBER_PATTERN, cleaned):
        raise ValueError(f"{text!r} is not a quantity (use a number such as 2, 1 1/2, 3/4 or 0.25)")
    parts = cleaned.split()
    try:
        if len(parts) == 2 and "/" in parts[1]:
            value = Fraction(parts[0]) + Fraction(parts[1])
        else:
            value = Fraction(re.sub(r"\s+", "", cleaned))
    except ZeroDivisionError:
        raise ValueError(f"{text!r} divides by zero") from None
    if not 0 < value <= MAX_QUANTITY:
        raise ValueError(f"{text!r} is out of range")
    return value
