"""Unit conversion: exact inside a dimension, density-gated across, and honest display."""

from fractions import Fraction

import pytest

from agent_system.domain.recipes.units import (
    ConversionError,
    Unit,
    convert,
    density_for,
    format_fraction,
    format_quantity,
    natural_unit,
    parse_quantity,
    parse_unit,
    targets,
    unit_label,
)

pytestmark = pytest.mark.unit

F = Fraction


@pytest.mark.parametrize(
    ("quantity", "unit", "to", "expected"),
    [
        (F(1), Unit.TBSP, Unit.TSP, F(3)),
        (F(1), Unit.CUP, Unit.TBSP, F(16)),
        (F(1), Unit.CUP, Unit.TSP, F(48)),
        (F(1), Unit.FL_OZ, Unit.TBSP, F(2)),
        (F(1), Unit.PINT, Unit.CUP, F(2)),
        (F(1), Unit.QUART, Unit.CUP, F(4)),
        (F(1), Unit.GALLON, Unit.QUART, F(4)),
        (F(1), Unit.L, Unit.ML, F(1000)),
        (F(1), Unit.LB, Unit.OZ, F(16)),
        (F(1), Unit.KG, Unit.G, F(1000)),
        (F(3, 4), Unit.CUP, Unit.TBSP, F(12)),
    ],
)
def test_conversions_inside_a_dimension_are_exact(quantity, unit, to, expected):
    done = convert(quantity, unit, to)
    assert done.quantity == expected
    assert done.unit is to
    assert done.approximate is False


def test_us_and_metric_use_the_legal_definitions():
    assert convert(F(1), Unit.TSP, Unit.ML).quantity == F("4.92892159375")       # gallon = 231 cubic inches
    assert convert(F(1), Unit.CUP, Unit.ML).quantity == F("236.5882365")
    assert convert(F(1), Unit.LB, Unit.G).quantity == F("453.59237")
    assert convert(F(1), Unit.OZ, Unit.G).quantity == F("28.349523125")


def test_a_round_trip_returns_exactly_what_went_in():
    start = F(7, 3)
    there = convert(start, Unit.CUP, Unit.ML)
    assert convert(there.quantity, Unit.ML, Unit.CUP).quantity == start       # no float drift


def test_volume_to_weight_is_refused_without_a_density():
    with pytest.raises(ConversionError, match="density"):
        convert(F(1), Unit.CUP, Unit.G)


def test_volume_to_weight_uses_the_density_and_says_it_is_approximate():
    flour = density_for("all-purpose flour")
    grams = convert(F(1), Unit.CUP, Unit.G, flour)
    assert grams.quantity == 125
    assert grams.approximate is True
    back = convert(F(125), Unit.G, Unit.CUP, flour)
    assert back.quantity == 1
    assert back.approximate is True
    assert convert(F(1), Unit.TBSP, Unit.G, density_for("butter")).quantity == F(227, 16)


@pytest.mark.parametrize(
    ("name", "grams_per_cup"),
    [("flour", 125), ("unsalted butter", 227), ("light brown sugar", 220), ("dry white wine", 236),
     ("heavy cream", 238), ("low-sodium chicken broth", 240), ("rice vinegar", 239), ("Greek yogurt", 245),
     ("flour (AP or GF), for dredging", 125), ("sweetened condensed milk", 306)],
)
def test_density_is_found_for_ingredients_named_at_the_end(name, grams_per_cup):
    assert density_for(name).grams_per_cup == grams_per_cup


@pytest.mark.parametrize(
    "name",
    ["kosher salt", "salt", "butter lettuce", "flour tortillas", "cooked brown rice", "ice cream", "almond flour mix",
     "sugar snap peas", "cream of chicken soup", "sunflower butter", "coconut sugar", "chicken thighs", ""],
)
def test_density_is_not_guessed(name):
    """A wrong density gives a wrong weight with no warning, so a miss must stay a miss."""
    assert density_for(name) is None


def test_targets_offer_weight_only_when_the_density_is_known():
    assert Unit.G not in targets(Unit.CUP)
    assert Unit.ML in targets(Unit.CUP)
    assert Unit.QUART in targets(Unit.CUP)
    assert Unit.G in targets(Unit.CUP, density_for("sugar"))
    assert Unit.CUP not in targets(Unit.LB)
    assert Unit.G in targets(Unit.LB)


@pytest.mark.parametrize(
    ("quantity", "unit", "system", "shown"),
    [
        (F(3), Unit.TSP, "us", "1 Tbsp"),
        (F(16), Unit.TBSP, "us", "1 cup"),
        (F(5), Unit.TBSP, "us", "5 Tbsp"),            # not "0.31 cups"
        (F(6), Unit.CUP, "us", "1½ quarts"),
        (F(1, 8), Unit.TSP, "us", "⅛ tsp"),
        (F(1), Unit.CUP, "metric", "235 ml"),
        (F(1500), Unit.ML, "metric", "1.5 L"),
        (F(2), Unit.LB, "metric", "905 g"),
        (F(250), Unit.ML, "us", "1.06 cups"),          # no measuring-cup fraction is close: say so
        (F(20), Unit.OZ, "us", "1¼ lb"),
    ],
)
def test_natural_unit_picks_what_a_cook_would_reach_for(quantity, unit, system, shown):
    done = natural_unit(quantity, unit, system)
    assert f"{format_quantity(done.quantity, done.unit)} {unit_label(done.unit, done.quantity)}" == shown


@pytest.mark.parametrize(
    ("value", "text"),
    [(F(1, 2), "½"), (F(3, 2), "1½"), (F(2), "2"), (F(1, 3), "⅓"), (F(11, 8), "1⅜"), (F(33, 100), "⅓"),
     (F(2, 5), "0.4"), (F(101, 100), "1"), (F(1, 16), "0.06")],
)
def test_fractions_snap_to_a_measuring_set_only_when_close(value, text):
    assert format_fraction(value) == text


@pytest.mark.parametrize(
    ("value", "unit", "text"),
    [(F(473, 2), Unit.ML, "235"), (F(59), Unit.ML, "59"), (F(739, 100), Unit.ML, "7.5"), (F(3, 4), Unit.G, "0.75"),
     (F(27, 10), Unit.G, "2.5"), (F(118, 100), Unit.L, "1.18"), (F(3), None, "3")],
)
def test_metric_amounts_are_rounded_for_display_only(value, unit, text):
    assert format_quantity(value, unit) == text


@pytest.mark.parametrize(
    ("text", "value"),
    [("2", F(2)), ("1 1/2", F(3, 2)), ("3/4", F(3, 4)), ("0.25", F(1, 4)), ("1½", F(3, 2)), ("⅓", F(1, 3)),
     (".5", F(1, 2)), (" 2 1/4 ", F(9, 4))],
)
def test_quantities_are_read_exactly(text, value):
    assert parse_quantity(text) == value


@pytest.mark.parametrize("text", ["", "two", "1/0", "-1", "1 cup", "1e9", "0", "1/2/3", "999999999"])
def test_bad_quantities_are_rejected(text):
    with pytest.raises(ValueError):  # noqa: PT011 - any ValueError is the contract
        parse_quantity(text)


def test_unit_words_are_recognised():
    assert parse_unit("Tbsp.") is Unit.TBSP
    assert parse_unit("tablespoons") is Unit.TBSP
    assert parse_unit("fl  oz") is Unit.FL_OZ
    assert parse_unit("QT") is Unit.QUART
    assert parse_unit("lbs") is Unit.LB
    assert parse_unit("pinch") is None
    assert parse_unit("clove") is None
