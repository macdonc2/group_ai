"""A small made-up cookbook for tests. Not from anyone's real cookbook."""

from agent_system.domain.recipes.cookbook import SeedFile, recipe_from_seed
from agent_system.domain.recipes.models import Recipe

COOKBOOK = {
    "books": [{"id": "test-kitchen", "title": "Test Kitchen Vol 1", "source_file": "x.pdf", "notes": None}],
    "recipes": [
        {
            "id": "lime-shrimp-tacos", "title": "Lime Shrimp Tacos", "book_id": "test-kitchen", "page": 12,
            "attribution": "A. Tester", "source_url": None, "servings": "Serves 4",
            "times": {"prep": "15 min", "cook": "10 min", "total": None, "raw": "15 + 10"},
            "tags": ["easy", "healthy"], "category": "seafood",
            "ingredient_groups": [
                {"name": None, "items": ["1 lb large shrimp, peeled", "2 Tbsp olive oil", "1 Tbsp lime juice",
                                         "8 corn tortillas", "1½ tsp kosher salt, ¾ tsp pepper"]},
                {"name": "Slaw", "items": ["2 cups shredded cabbage", "¼ cup sour cream"]},
            ],
            "steps": ["Toss the shrimp with oil, lime, salt and pepper.", "Sear 2 minutes a side.", "Serve in tortillas with slaw."],
            "variants": [{"name": "Grill", "untested": True, "steps": ["Skewer and grill."]}],
            "substitutions": ["Use cod instead of shrimp."], "notes": ["Do not overcook."], "pairings": ["Rice"],
            "related": [], "completeness": "complete", "gaps": [], "also_in": [],
        },
        {
            "id": "peanut-noodles", "title": "Peanut Noodles", "book_id": "test-kitchen", "page": 20,
            "attribution": None, "source_url": "https://example.com/noodles", "servings": "Serves 2",
            "times": {"prep": None, "cook": None, "total": "20 min", "raw": "20 min"},
            "tags": ["easy"], "category": "pasta",
            "ingredient_groups": [{"name": None, "items": ["8 oz spaghetti", "¼ cup peanut butter", "2 Tbsp soy sauce",
                                                         "1 Tbsp lime juice", "2 scallions, sliced"]}],
            "steps": ["Boil the noodles.", "Whisk the sauce and toss."],
            "variants": [], "substitutions": [], "notes": [], "pairings": [], "related": [],
            "completeness": "complete", "gaps": [], "also_in": [],
        },
        {
            "id": "chicken-soup", "title": "Sunday Chicken Soup", "book_id": "test-kitchen", "page": None,
            "attribution": None, "source_url": None, "servings": None,
            "times": {"prep": None, "cook": None, "total": None, "raw": None},
            "tags": ["healthy"], "category": "not-a-category",
            "ingredient_groups": [{"name": None, "items": ["1 whole chicken (4–5 lb)", "6 cups water", "2 carrots, diced",
                                                         "2 cups flour"]}],
            "steps": ["Simmer everything for an hour."],
            "variants": [], "substitutions": [], "notes": [], "pairings": [], "related": [],
            "completeness": "partial", "gaps": ["Seasoning amounts were not recorded."], "also_in": [],
        },
    ],
}


def cookbook_recipes() -> dict[str, Recipe]:
    seed = SeedFile.model_validate(COOKBOOK)
    return {r.id: recipe_from_seed(r, "Test Kitchen Vol 1") for r in seed.recipes}
