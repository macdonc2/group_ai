# Recipes

The **Recipes** tab ("Kitchen Stadium") finds recipes, pitches dishes for what you fancy and
have in the kitchen, keeps a list of the ones you want, shows ingredients in whichever units
you like, and puts a picture on every dish and most ingredients. It looks and talks like an
80s wrestling pay-per-view.

This page explains how it is built and, for each part, what is decided by code and what is
left to a model.

## The short version

| Part | Who does the work | Model call? |
|---|---|---|
| Find (search the cookbooks) | Word matching with fixed weights, `domain/recipes/search.py` | No |
| Scout the web | Search engine, then the page's own schema.org recipe data read by code, `domain/recipes/jsonld.py` | No |
| Pitch | A PydanticAI agent picks dishes and writes the promo; code checks every pick, `llm/recipe_agent.py` | Yes, one turn |
| Saved list | A flag on a row the server already holds | No |
| Scaling and unit conversion | Exact fractions, `domain/recipes/units.py` and `ingredients.py` | No |
| Dish picture | Image model, prompt assembled in code, stored in our database | Yes, one image per kept recipe |
| Ingredient photo | Freely licensed Wikipedia photo, fixed list of ingredients, stored in our database | No |

## Where recipes come from

Every recipe is a `Recipe` (`domain/recipes/models.py`) with a `source` of `cookbook`, `web`
or `model`. The source is set by code at the point the recipe enters the system:

- **Cookbook**: the owner uploads the cookbook file (`POST /recipes/cookbooks`, the JSON made
  from the cookbooks; see `domain/recipes/cookbook.py`). Titles, ingredient lines and steps
  are kept as printed. The file is private content: it is **not** in this repository or in
  the image, and the recipes are visible only to the account that imported them. Importing
  the same file again updates entries in place.
- **Web**: a search (`ddgs`) or a pasted address; the page is fetched with the same rules as
  the chat's page reader (public addresses only, robots.txt honoured, honest User-Agent) and
  its `application/ld+json` Recipe object is read field by field. A page without that data
  gives nothing: there is no fallback that guesses from the prose, and no model reads the page.
- **Model**: the pitch agent may write a new recipe. It arrives as structured fields and
  `recipe_from_draft` builds the `Recipe`, stamping `source=model` and "Written by
  <model name>". The model's output type has no source field, so it cannot claim otherwise.

The badge on a card ("From the cookbook", "Model-written · untested", "From the web") is
drawn from `source`, never from recipe text.

**Recipe text never comes from the browser.** A pitched or looked-up recipe is stored as an
*offer* (a row with `saved=false`) and the browser gets its id. "Keep it" sets the flag.
Offers nobody keeps are deleted after three days. So the client can never submit a recipe
that says it came from the cookbook.

## Ingredients as data

An ingredient is stored as `raw` (the line as printed), `quantity`, `quantity_max` (for
"3-4 Tbsp"), `unit`, `name` and `note`. Quantities are `fractions.Fraction`, written to JSON
as `"3/4"`. A float would turn ⅓ cup into 0.333 and tripling it into 0.999 cups; a fraction
scales and converts exactly and is rounded only when shown.

`parse_ingredient` reads a printed line into that shape. It is a strict reader, not a guesser:

- `1½ lb baby bok choy, halved (or broccoli florets)` becomes 3/2, `lb`, "baby bok choy",
  note "or broccoli florets; halved".
- `4 garlic cloves, minced` is a count: quantity 4, no unit.
- `1½ tsp kosher salt, ¾ tsp pepper, divided` holds two amounts, so it is kept **as written**
  with no quantity. Scaling half of that line would be worse than scaling none of it; when
  the recipe is scaled the UI marks the line "not scaled: adjust by hand".

On the 1,723 ingredient lines of the cookbooks, 1,431 (83%) are read into an amount, 147 have
no amount to read ("Paprika"), and 145 (8%) contain amounts the reader declines to split and
are shown as written.

## Unit conversion

`present()` in `domain/recipes/ingredients.py` is the single place a line is scaled, converted
and formatted. The browser asks the server (`POST /recipes/{id}/convert`) and displays the
answer; there is no second implementation in TypeScript to drift.

- **Inside a dimension it is exact.** US volume units are defined from the US gallon (231
  cubic inches = 3.785411784 L), so 1 cup is exactly 48 tsp and 1 tsp exactly 4.92892159375 ml;
  1 lb is exactly 453.59237 g.
- **Volume to weight needs a density**, and a cup of flour does not weigh what a cup of honey
  does. `DENSITIES` lists grams per cup for about 70 common ingredients (USDA household
  measures). The ingredient's name must *end* with the entry ("all-purpose flour" yes, "flour
  tortillas" no), and each entry lists words that cancel it ("cooked" rice, butter "lettuce").
  For anything else, grams are simply not offered. A result that used a density is flagged
  and shown as "about 250 g".
- **Salt has no density on purpose.** A cup of Diamond Crystal kosher salt weighs about 135 g
  and a cup of Morton about 240 g; recipes rarely say which.
- **Display rounding is separate from the stored amount.** US amounts snap to a measuring-set
  fraction when one is within 3% (otherwise a decimal: 250 ml is "1.06 cups", not a made-up
  fraction); grams and millilitres round to sensible steps.
- The "US" and "Metric" switches pick the natural unit by size (3 tsp becomes 1 Tbsp, 6 cups
  becomes 1½ quarts) and never cross between volume and weight on their own; the per-line
  unit menu is where "grams" appears, only for ingredients with a density.

What it does not do: pluralise names after scaling ("2 lime"), convert pan sizes, or change
cooking times (the UI says times do not scale).

## The pitch agent

A separate agent (`llm/recipe_agent.py`), not a mode of the chat loop:

- Its answer is **data**. The output type is `PitchSheet` (a promo plus 1 to 5 pitches), so
  each pitch can be checked in code. The chat loop returns free text.
- Its tools are `search_cookbook` and `search_web` and nothing else. It cannot write to a
  calendar or read arbitrary pages, so web text has nothing to act on.
- It does not depend on `CHAT_ENGINE`.

`check_sheet` runs on every answer, before anyone sees it. A failure goes back to the model
as a retry (three attempts), then the turn ends with an error and no card:

| Check | What it proves | What it does not |
|---|---|---|
| A cookbook or web pitch names a reference (`C2`, `W1`) that a search returned this turn | The model cannot pitch a cookbook recipe that does not exist; the card shows the stored recipe, which the model never retyped | That the dish is a good fit |
| A new recipe validates: ≥2 ingredients, ≥2 steps, each amount readable by `parse_quantity`, each unit from the fixed list | The recipe can be shown, scaled and converted like any other | That it tastes good or is safe: nobody has cooked it, and the UI says so |
| No ingredient on the avoid list appears in the dish's ingredient lines | The obvious is caught ("peanuts" finds "peanut butter"), before the model sees candidates and again on its answer | What an ingredient *contains* (egg in mayonnaise). It is a word match, not an allergy guarantee, and the form says so |
| No repeats, no more dishes than asked, no new recipes when they are switched off | The request's limits hold | |

The voice: with a wrestler theme selected the persona rules from `personas.py` are used; with
none, a house character ("The Ring Chef"). Either way the rules say the voice never touches
titles, amounts or steps.

Cost, measured once on 2026-11-26 with `gpt-6-astra` and the Macho Man persona: $0.19 for one
pitch of three dishes (12,467 input tokens over four model requests, 1,264 output). Most of
the input is the persona prompt repeated on each request. `RECIPE_PITCH_MODEL` selects a
cheaper model for pitches. Each pitch is recorded as a turn trace with `source="recipes"`, so
it counts toward the spend alerts.

## Pictures

The production frontend sends `img-src 'self' data: blob:` (`infra/docker/security-headers.conf`),
so that model output can never make the browser load an address on another site. This feature
does not change that policy. Both kinds of picture are stored in our database, served by the
API to requests that carry the `Authorization` header, and shown as `blob:` addresses. The
token is never in an image URL.

**Dish pictures** are generated (`adapters/outbound/recipes/dish_pictures.py`) when a recipe is
kept, once per recipe:

- The prompt is built in code from the recipe's title and its first eight ingredient names
  (reduced to plain words and cut to length) plus a fixed style paragraph. It asks for no
  people, text or logos.
- Measured cost: $0.014 for a 1024×1024 JPEG at `medium` quality on `gpt-image-2.5-flare`
  (about 230 KB, 15 seconds). The cost of each picture is stored with it.
- A per-user cap (`RECIPE_IMAGES_PER_DAY`, default 20, 0 = off) is checked in code immediately
  before the paid call. Over the cap, the recipe is still kept and shows a poster card; "try
  the picture again" asks for it later.

**Ingredient photos** come from English Wikipedia (`ingredient_photos.py`):

- Which article is fetched is a fixed list in code (`domain/recipes/photo_keys.py`, 214
  entries). An ingredient name from a model or a web page is only ever *looked up in* that
  list; it is never sent anywhere.
- Only the article's free lead image is requested, and the file's own licence must be public
  domain, CC0, CC BY or CC BY-SA. Author, licence and a link to the file page are stored and
  shown under "Ingredient photo credits". On 2026-11-26, 204 of the 214 entries had a usable
  photo (about 20 KB each); the rest show a lettered tile.
- Wikimedia refuses automated clients that do not give a contact, and rate-limits crawlers.
  `RECIPE_PHOTO_CONTACT` (a URL or email) goes in the User-Agent; without it no lookups are
  made. Requests are batched: all of a recipe's new ingredients cost two API calls plus one
  small download each, one at a time, and each ingredient is fetched once for all users.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `RECIPE_PITCH_MODEL` | unset (uses `DEFAULT_MODEL`) | Model for pitches |
| `RECIPE_IMAGE_MODEL` | `gpt-image-2.5-flare` | Image model for dish pictures |
| `RECIPE_IMAGE_QUALITY` | `medium` | `low`, `medium` or `high`; cost rises steeply |
| `RECIPE_IMAGES_PER_DAY` | `20` | Dish pictures per user per 24 hours; `0` turns generation off |
| `RECIPE_PHOTO_CONTACT` | unset | Contact for Wikimedia's User-Agent rule; unset = no ingredient photos |

## Data

Three new tables, created at startup like the others (`persistence/recipe_models.py`):
`recipes` (one row per recipe per owner; `data` holds the validated `Recipe`), `recipe_images`
(one generated picture per recipe) and `ingredient_images` (shared, keyed by the fixed list).
Every recipe query filters on the caller's user id; another user's recipe is a 404.

## Tests

- `tests/unit/recipes/`: units and conversion, the ingredient reader, cookbook import, search,
  the web reader (including hostile markup), photo list and licence filter, the image prompt,
  and the pitch agent against a scripted model (made-up reference, avoid list, bad amounts).
- `tests/e2e/api/test_recipes_api.py`: the routes end to end with two users: import, find,
  convert, keep, reopen, delete, the picture cap, pitch, web offers, photo credits, and that
  one user's recipes and pictures are invisible to another.

## Not done

- No eval suite for pitch quality, and only one live pitch has been run.
- The avoid list is a word match on ingredient lines; it does not know what foods contain.
- Recipes are not written to the knowledge graph, so chat does not know what you kept.
- Sharing a cookbook with another account is not built; the library belongs to its importer.
- Names are not re-pluralised after scaling.
