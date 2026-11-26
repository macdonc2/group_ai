"""Reading ingredient lines, and scaling, converting and showing them."""

from fractions import Fraction

import pytest

from agent_system.domain.recipes.ingredients import parse_ingredient, parse_scale, present
from agent_system.domain.recipes.models import Ingredient
from agent_system.domain.recipes.units import ConversionError, Unit

pytestmark = pytest.mark.unit

F = Fraction


@pytest.mark.parametrize(
    ("line", "quantity", "top", "unit", "name", "note"),
    [
        ("1½ lb baby bok choy, halved (or broccoli florets)", F(3, 2), None, Unit.LB, "baby bok choy",
         "or broccoli florets; halved"),
        ("3/4 tsp garlic powder", F(3, 4), None, Unit.TSP, "garlic powder", None),
        ("2 1/2 cups light cream", F(5, 2), None, Unit.CUP, "light cream", None),
        ("¼ cup flour (AP or GF), for dredging", F(1, 4), None, Unit.CUP, "flour", "AP or GF; for dredging"),
        ("3-4 Tbsp shrimp oil (next recipe)", F(3), F(4), Unit.TBSP, "shrimp oil", "next recipe"),
        ("½–¾ cup heavy cream", F(1, 2), F(3, 4), Unit.CUP, "heavy cream", None),
        ("4 garlic cloves, minced", F(4), None, None, "garlic cloves", "minced"),
        ("2 large eggs, beaten", F(2), None, None, "large eggs", "beaten"),
        ("4 (6-oz) salmon fillets", F(4), None, None, "salmon fillets", "6-oz"),
        ("2.7 g beef base", F(27, 10), None, Unit.G, "beef base", None),
        ("4 fl oz bourbon", F(4), None, Unit.FL_OZ, "bourbon", None),
        ("2 tablespoons of olive oil", F(2), None, Unit.TBSP, "olive oil", None),
        ("1 lb 93% lean ground beef", F(1), None, Unit.LB, "93% lean ground beef", None),
        ("1½ lb baby potatoes, sliced ⅛ inch thick", F(3, 2), None, Unit.LB, "baby potatoes", "sliced 1/8 inch thick"),
        ("300 g/10 oz whole shrimp", F(300), None, Unit.G, "whole shrimp", None),
        ("two 10-oz cans cream of chicken soup, undiluted", F(2), None, None, "cans cream of chicken soup",
         "undiluted; 10-oz each"),
        ("about 1 Tbsp butter", F(1), None, Unit.TBSP, "butter", None),
        ("optional 2 Tbsp bourbon", F(2), None, Unit.TBSP, "bourbon", "optional"),
        ("1 Tbsp lime juice + wedges", F(1), None, Unit.TBSP, "lime juice + wedges", None),
    ],
)
def test_a_plain_line_is_read_into_parts(line, quantity, top, unit, name, note):
    item = parse_ingredient(line)
    assert (item.quantity, item.quantity_max, item.unit, item.name, item.note) == (quantity, top, unit, name, note)
    assert item.raw == line


@pytest.mark.parametrize(
    "line",
    [
        "1½ tsp kosher salt, ¾ tsp pepper, divided",          # two amounts
        "½ cup sugar + 1 Tbsp water",
        "1 Tbsp kosher salt OR 1 1/2 tsp sea salt",
        "3 large chicken breasts or 6 cutlets (~2¼ lb)",      # an alternative with its own number
        "5 slices ginger, 2 scallions",
        "¾ tsp each kosher salt and pepper",
        "10-oz can Ro-Tel, drained",                           # a package size, not an amount
        "1 cup flour first, then another 1 1/3 cups flour",
        "Juice of 2 limes (¼ cup)",
    ],
)
def test_a_line_that_cannot_be_read_with_certainty_is_kept_as_written(line):
    """Scaling half of a two-amount line would be worse than scaling none of it."""
    item = parse_ingredient(line)
    assert item.quantity is None
    assert item.unit is None
    assert item.name == line
    assert item.raw == line
    assert item.unscaled_numbers is True


def test_a_line_with_no_amount_is_just_a_name():
    item = parse_ingredient("Paprika")
    assert (item.quantity, item.name, item.unscaled_numbers) == (None, "Paprika", False)
    assert parse_ingredient("A pinch of salt").quantity is None


def test_an_empty_line_is_an_error():
    with pytest.raises(ValueError, match="empty"):
        parse_ingredient("   ")


# ---- present --------------------------------------------------------------


def test_an_untouched_line_is_shown_exactly_as_printed():
    shown = present(parse_ingredient("¾ cup chicken broth, warmed"))
    assert shown.text == "¾ cup chicken broth, warmed"
    assert shown.converted is False
    assert shown.amount == "¾"
    assert Unit.ML in shown.can_convert_to
    assert Unit.QUART in shown.can_convert_to
    assert Unit.CUP not in shown.can_convert_to


def test_scaling_multiplies_exactly_and_keeps_the_unit():
    shown = present(parse_ingredient("1/3 cup brown sugar"), scale=F(3))
    assert (shown.amount, shown.unit, shown.text) == ("1", Unit.CUP, "1 cup brown sugar")
    assert present(parse_ingredient("3-4 Tbsp oil"), scale=F(1, 2)).text == "1½–2 Tbsp oil"
    assert present(parse_ingredient("4 garlic cloves, minced"), scale=F(2)).text == "8 garlic cloves, minced"


def test_the_metric_system_converts_measured_lines_and_leaves_counts_alone():
    assert present(parse_ingredient("¾ cup chicken broth"), system="metric").text == "175 ml chicken broth"
    assert present(parse_ingredient("1 lb crabmeat, picked over"), system="metric").text == "455 g crabmeat, picked over"
    eggs = present(parse_ingredient("2 large eggs"), system="metric")
    assert eggs.text == "2 large eggs"
    assert eggs.unit is None
    assert eggs.can_convert_to == []


def test_the_us_system_converts_metric_lines():
    assert present(parse_ingredient("500 ml water"), system="us").text == "2⅛ cups water"
    assert present(parse_ingredient("15 ml soy sauce"), system="us").text == "1 Tbsp soy sauce"


def test_one_line_can_be_switched_to_any_unit_it_supports():
    broth = parse_ingredient("6 cups water")
    assert present(broth, to=Unit.QUART).text == "1½ quarts water"
    assert present(broth, to=Unit.ML).text == "1420 ml water"
    assert present(broth, to=Unit.TSP).amount == "288"
    assert present(broth, system="metric", to=Unit.CUP).text == "6 cups water"     # the line's own choice wins


def test_weight_is_offered_only_with_a_density_and_marked_approximate():
    flour = present(parse_ingredient("2 cups flour"), to=Unit.G)
    assert flour.text == "about 250 g flour"
    assert flour.approximate is True
    assert flour.converted is True
    salt = parse_ingredient("1 tsp kosher salt")
    assert Unit.G not in present(salt).can_convert_to
    with pytest.raises(ConversionError, match="no density"):
        present(salt, to=Unit.G)


def test_a_count_or_an_as_written_line_cannot_be_converted():
    with pytest.raises(ConversionError, match="counted"):
        present(parse_ingredient("2 eggs"), to=Unit.G)
    with pytest.raises(ConversionError, match="no amount"):
        present(parse_ingredient("1 tsp salt, ½ tsp pepper"), to=Unit.ML)


def test_scaling_flags_the_lines_it_had_to_leave_alone():
    mixed = present(parse_ingredient("1½ tsp salt, ¾ tsp pepper, divided"), scale=F(2))
    assert mixed.text == "1½ tsp salt, ¾ tsp pepper, divided"
    assert mixed.not_scaled is True
    assert present(parse_ingredient("Paprika"), scale=F(2)).not_scaled is False     # nothing to scale
    assert present(parse_ingredient("1½ tsp salt, ¾ tsp pepper"), scale=F(1)).not_scaled is False


def test_scale_is_parsed_and_bounded():
    assert parse_scale("1/2") == F(1, 2)
    assert parse_scale("2") == 2
    assert parse_scale(None) == 1
    assert parse_scale("1.5") == F(3, 2)
    for bad in ("0", "abc", "1000", "-2"):
        with pytest.raises(ConversionError):
            parse_scale(bad)


def test_the_ingredient_model_refuses_inconsistent_data():
    with pytest.raises(ValueError, match="needs a quantity"):
        Ingredient(raw="cup flour", unit=Unit.CUP, name="flour")
    with pytest.raises(ValueError, match="range"):
        Ingredient(raw="3-2 cups", quantity=F(3), quantity_max=F(2), unit=Unit.CUP, name="flour")
    with pytest.raises(ValueError, match="greater than zero"):
        Ingredient(raw="0 cups", quantity=F(0), unit=Unit.CUP, name="flour")


def test_quantities_survive_json_exactly():
    item = parse_ingredient("1/3 cup brown sugar")
    again = Ingredient.model_validate_json(item.model_dump_json())
    assert again == item
    assert again.quantity == F(1, 3)
    assert '"1/3"' in item.model_dump_json()
