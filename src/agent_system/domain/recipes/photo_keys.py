"""Which ingredients have a photo, and which Wikipedia article the photo comes from.

A fixed list, on purpose. The photo lookup fetches from the internet, so what it may ask for
is decided here in code and not by an ingredient name that a model or a web page supplied:
`photo_key("2 cups unicorn tears")` is simply None and nothing is fetched. The list covers
the common ingredients of the cookbooks; anything else gets a lettered tile in the UI.

Matching: an entry matches when its words appear together in the ingredient's name. The
longest entry wins ("coconut milk" over "milk") and, between equals, the one nearest the end
of the name, where English puts the thing itself ("butter lettuce" is lettuce).
"""

from __future__ import annotations

from agent_system.domain.recipes.search import tokens

# key (shown in addresses and stored in the database) -> English Wikipedia article title
PHOTO_PAGES: dict[str, str] = {
    "garlic": "Garlic", "onion": "Onion", "red onion": "Red onion", "shallot": "Shallot", "scallion": "Scallion",
    "green onion": "Scallion", "leek": "Leek", "chive": "Chives", "ginger": "Ginger", "olive oil": "Olive oil",
    "oil": "Cooking oil", "sesame oil": "Sesame oil", "butter": "Butter", "salt": "Salt", "kosher salt": "Kosher salt",
    "sea salt": "Sea salt", "pepper": "Black pepper", "black pepper": "Black pepper", "white pepper": "White pepper",
    "flour": "Flour", "sugar": "Sugar", "brown sugar": "Brown sugar", "powdered sugar": "Powdered sugar",
    "honey": "Honey", "maple syrup": "Maple syrup", "molass": "Molasses", "water": "Drinking water",
    "egg": "Egg as food", "milk": "Milk", "buttermilk": "Buttermilk", "heavy cream": "Cream", "cream": "Cream",
    "sour cream": "Sour cream", "cream cheese": "Cream cheese", "yogurt": "Yogurt", "half half": "Half and half",
    "evaporated milk": "Evaporated milk", "condensed milk": "Condensed milk", "coconut milk": "Coconut milk",
    "parmesan": "Parmesan", "cheddar": "Cheddar cheese", "mozzarella": "Mozzarella", "pepper jack": "Pepper jack cheese",
    "feta": "Feta", "monterey jack": "Monterey Jack", "cheese": "Cheese",
    "lime": "Lime (fruit)", "lemon": "Lemon", "orange": "Orange (fruit)", "lime juice": "Lime (fruit)",
    "lemon juice": "Lemon", "orange juice": "Orange juice", "mango": "Mango", "pineapple": "Pineapple",
    "apple": "Apple", "banana": "Banana", "avocado": "Avocado", "coconut": "Coconut",
    "cilantro": "Coriander", "parsley": "Parsley", "dill": "Dill", "basil": "Basil", "thyme": "Thyme",
    "oregano": "Oregano", "rosemary": "Rosemary", "sage": "Salvia officinalis", "mint": "Mentha", "bay leaf": "Bay leaf",
    "bay leave": "Bay leaf", "cumin": "Cumin", "paprika": "Paprika", "cayenne": "Cayenne pepper",
    "chili powder": "Chili powder", "cinnamon": "Cinnamon", "nutmeg": "Nutmeg", "turmeric": "Turmeric",
    "garam masala": "Garam masala", "curry powder": "Curry powder", "garlic powder": "Garlic powder",
    "onion powder": "Onion powder", "red pepper flake": "Crushed red pepper", "crushed red pepper": "Crushed red pepper",
    "vanilla": "Vanilla extract", "saffron": "Saffron", "coriander": "Coriander", "mustard": "Mustard (condiment)",
    "dijon": "Dijon mustard", "soy sauce": "Soy sauce", "fish sauce": "Fish sauce", "worcestershire": "Worcestershire sauce",
    "ketchup": "Ketchup", "mayonnaise": "Mayonnaise", "hot sauce": "Hot sauce", "tabasco": "Tabasco sauce",
    "sriracha": "Sriracha", "harissa": "Harissa", "miso": "Miso", "hoisin": "Hoisin sauce", "tomato paste": "Tomato paste",
    "tomato sauce": "Tomato sauce", "salsa": "Salsa (food)", "vinegar": "Vinegar", "rice vinegar": "Rice vinegar",
    "balsamic vinegar": "Balsamic vinegar", "apple cider vinegar": "Apple cider vinegar", "wine": "Wine",
    "white wine": "White wine", "red wine": "Red wine", "sherry": "Sherry", "bourbon": "Bourbon whiskey", "beer": "Beer",
    "broth": "Broth", "stock": "Stock (food)", "rice": "Rice", "spaghetti": "Spaghetti", "pasta": "Pasta",
    "noodle": "Noodle", "egg noodle": "Noodle", "penne": "Penne", "tortilla": "Tortilla", "corn tortilla": "Corn tortilla",
    "bread": "Bread", "panko": "Bread crumbs", "breadcrumb": "Bread crumbs", "bread crumb": "Bread crumbs",
    "cornstarch": "Corn starch", "baking powder": "Baking powder", "baking soda": "Sodium bicarbonate",
    "oat": "Rolled oats", "cornmeal": "Cornmeal", "hominy": "Hominy", "shortening": "Shortening", "lard": "Lard",
    "chicken": "Chicken as food", "chicken thigh": "Chicken as food", "chicken breast": "Chicken as food",
    "beef": "Beef", "ground beef": "Ground beef", "steak": "Steak", "pork": "Pork", "pork tenderloin": "Pork tenderloin",
    "ground pork": "Ground meat", "bacon": "Bacon", "sausage": "Sausage", "ham": "Ham", "lamb": "Lamb and mutton",
    "shrimp": "Shrimp and prawn as food", "salmon": "Salmon as food", "cod": "Cod as food", "tuna": "Tuna",
    "crab": "Crab meat", "crabmeat": "Crab meat", "scallop": "Scallop", "anchovy": "Anchovies as food",
    "sardine": "Sardines as food", "fish": "Fish as food", "oyster": "Oyster", "mussel": "Mussel", "clam": "Clam",
    "tomato": "Tomato", "cherry tomato": "Cherry tomato", "potato": "Potato", "sweet potato": "Sweet potato",
    "carrot": "Carrot", "celery": "Celery", "bell pepper": "Bell pepper", "jalapeno": "Jalapeño",
    "poblano": "Poblano", "serrano": "Serrano pepper", "chile": "Chili pepper", "chili": "Chili pepper", "chily": "Chili pepper",
    "mushroom": "Edible mushroom", "cremini": "Agaricus bisporus", "spinach": "Spinach", "kale": "Kale",
    "cabbage": "Cabbage", "bok choy": "Bok choy", "broccoli": "Broccoli", "cauliflower": "Cauliflower",
    "zucchini": "Zucchini", "squash": "Cucurbita", "spaghetti squash": "Spaghetti squash", "eggplant": "Eggplant",
    "cucumber": "Cucumber", "lettuce": "Lettuce", "chard": "Chard", "green bean": "Green bean", "pea": "Pea",
    "corn": "Maize", "bean": "Bean", "black bean": "Black turtle bean", "navy bean": "Navy bean", "chickpea": "Chickpea",
    "lentil": "Lentil", "peanut": "Peanut", "peanut butter": "Peanut butter", "almond": "Almond",
    "almond butter": "Almond butter", "cashew": "Cashew", "pecan": "Pecan", "walnut": "Walnut", "sesame seed": "Sesame",
    "olive": "Olive", "caper": "Caper", "pickle": "Pickled cucumber", "chocolate": "Chocolate",
    "chocolate chip": "Chocolate chip", "cocoa": "Cocoa solids", "raisin": "Raisin", "horseradish": "Horseradish",
    "lemongrass": "Cymbopogon", "tofu": "Tofu", "bean sprout": "Sprouting",
}

_KEYS: dict[tuple[str, ...], str] = {tuple(key.split()): key for key in PHOTO_PAGES}
_LONGEST = max(len(k) for k in _KEYS)


def photo_key(name: str) -> str | None:
    """The photo entry for an ingredient name, or None when the list has nothing for it."""
    words = tokens(name.split(",", 1)[0])
    best: tuple[int, int, str] | None = None                # (length, position, key)
    for size in range(min(_LONGEST, len(words)), 0, -1):
        for start in range(len(words) - size + 1):
            key = _KEYS.get(tuple(words[start:start + size]))
            if key is not None and (best is None or (size, start) > best[:2]):
                best = (size, start, key)
        if best is not None:
            break
    return best[2] if best else None
