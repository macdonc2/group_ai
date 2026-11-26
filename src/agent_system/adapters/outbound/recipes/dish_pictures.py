"""Generate the picture of a dish with an image model.

Two things are decided in code, not by a model:

* **The prompt.** It is assembled here from validated fields of the recipe (its title and
  its main ingredient names) and a fixed style paragraph. No model-written free text and no
  web text beyond those short, length-limited fields reaches the image model.
* **Where the picture lives.** The bytes come back in the API response and are stored in
  our database. The browser is given an address on this app, never an address at a third
  party, so the frontend's image policy does not need to trust anyone new.

Each picture costs money (see `estimate_cost`), so the caller applies a per-user daily cap
before calling `generate`.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any

from agent_system.domain.recipes.models import Recipe

# USD per million tokens for the GPT-Image 2.5 / 2.6 Flare models (OpenAI pricing page, November 2026).
IMAGE_OUTPUT_USD_PER_M = 30.0
TEXT_INPUT_USD_PER_M = 5.0
SIZE = "1024x1024"
MAX_BYTES = 6_000_000

STYLE = (
    "Appetizing studio food photograph of the finished dish, plated and ready to serve, shot from a three-quarter "
    "angle. Styled like a 1980s pro-wrestling pay-per-view poster: the plate sits on a canvas ring mat under hard "
    "arena spotlights with light haze, red, white and blue ring ropes blurred behind it, hot-pink and electric-blue "
    "rim light, a gold championship-belt gleam on the rim of the plate, saturated glossy colours, slight film "
    "grain. The food is the star and fills most of the frame. No people, no faces, no hands, no text, no letters, "
    "no logos, no watermarks."
)


@dataclass(frozen=True)
class DishPicture:
    content: bytes
    content_type: str
    prompt: str
    model: str
    cost_usd: float | None


def _plain(text: str, limit: int) -> str:
    """Letters, digits and light punctuation only, on one line: a title is data, not a prompt."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s,.'&()/-]", " ", text)).strip()[:limit]


def build_prompt(recipe: Recipe) -> str:
    """The image prompt for a recipe. Deterministic: the same recipe always gives the same prompt."""
    names = list(dict.fromkeys(_plain(item.name, 40) for item in recipe.ingredients if item.measured))
    main = ", ".join(name for name in names[:8] if name)
    dish = f"The dish: {_plain(recipe.title, 120)}."
    if main:
        dish += f" Made with: {main}."
    return f"{dish} {STYLE}"


def estimate_cost(usage: Any) -> float | None:
    """Cost in USD from the token counts the API returned, or None if it returned none."""
    if usage is None:
        return None
    output = getattr(usage, "output_tokens", None)
    if output is None:
        return None
    text_in = getattr(getattr(usage, "input_tokens_details", None), "text_tokens", None)
    if text_in is None:
        text_in = getattr(usage, "input_tokens", 0) or 0
    return round(output * IMAGE_OUTPUT_USD_PER_M / 1e6 + text_in * TEXT_INPUT_USD_PER_M / 1e6, 5)


async def generate(recipe: Recipe, *, api_key: str, model: str, quality: str) -> DishPicture:
    """One picture of `recipe`. Raises on any API failure; the caller records it on the recipe."""
    from openai import AsyncOpenAI

    prompt = build_prompt(recipe)
    client = AsyncOpenAI(api_key=api_key, timeout=180.0, max_retries=1)
    try:
        result = await client.images.generate(model=model, prompt=prompt, size=SIZE, quality=quality, n=1,
                                              output_format="jpeg", output_compression=82)
    finally:
        await client.close()
    encoded = result.data[0].b64_json if result.data else None
    if not encoded:
        raise RuntimeError("the image model returned no picture")
    content = base64.b64decode(encoded)
    if not content.startswith(b"\xff\xd8") or len(content) > MAX_BYTES:
        raise RuntimeError("the image model returned something that is not a JPEG of a sane size")
    return DishPicture(content=content, content_type="image/jpeg", prompt=prompt, model=model,
                       cost_usd=estimate_cost(getattr(result, "usage", None)))
