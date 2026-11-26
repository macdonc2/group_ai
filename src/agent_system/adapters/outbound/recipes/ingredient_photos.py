"""Fetch a freely licensed photo of an ingredient from Wikipedia / Wikimedia Commons.

What is fetched is fixed in code: the article title comes from `domain/recipes/photo_keys.py`,
and the only hosts contacted are en.wikipedia.org (the API) and Wikimedia's own image hosts
(`IMAGE_HOSTS`, for the picture). No address from a model, a user or a web page is ever requested.

Licence handling, since these are other people's photographs:

* Requests are batched: all the ingredients of a recipe cost two API calls, not two each.
* Only the article's *free* lead image is asked for (`pilicense=free`), and its licence is
  then read from the file's own metadata and must be on the allow list below (public domain,
  CC0, CC BY, CC BY-SA). Anything else is recorded as "no photo".
* The author, the licence and a link to the file's page are stored with the picture and
  shown in the app as the photo credit, which is what those licences ask for.

The picture is stored in our database and served from our own API, so the browser never
talks to Wikimedia and the app's image policy (`img-src 'self'`) stays as strict as it was.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from agent_system.domain.recipes.photo_keys import PHOTO_PAGES

logger = logging.getLogger(__name__)

API = "https://en.wikipedia.org/w/api.php"
IMAGE_HOSTS = frozenset({"thumb.wikimedia.org", "upload.wikimedia.org"})   # where Wikimedia serves pictures
CLIENT_NAME = "agent-system-recipes/1.0"
THUMB_WIDTH = 240
MAX_BYTES = 400_000
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_FREE_LICENSE = re.compile(r"^(?:cc0\b.*|public domain.*|pd\b.*|cc[ -]by(?:[ -]sa)?(?:[ -]\d(?:\.\d)?.*)?)$", re.IGNORECASE)


@dataclass(frozen=True)
class IngredientPhoto:
    content: bytes
    content_type: str
    title: str
    author: str | None
    license_name: str
    license_url: str | None
    source_url: str


def is_free_license(name: str | None) -> bool:
    """True for the licences we accept: public domain, CC0, CC BY and CC BY-SA (any version).
    NonCommercial and NoDerivatives variants, "fair use" and anything unrecognised are refused."""
    text = (name or "").strip()
    if not text or re.search(r"\b(?:nc|nd)\b|non-?free|fair use", text, re.IGNORECASE):
        return False
    return bool(_FREE_LICENSE.match(text))


def _plain(value: Any, limit: int) -> str:
    text = re.sub(r"<[^>]{0,2000}>", "", html.unescape(str(value or "")))
    return " ".join(text.split())[:limit]


def _meta(info: dict[str, Any], key: str, limit: int = 300) -> str:
    return _plain((info.get("extmetadata") or {}).get(key, {}).get("value"), limit)


def user_agent(contact: str) -> str:
    """Wikimedia's robot policy asks every automated client to name itself and give a way to
    reach its operator (a URL or an email address); requests without one are refused."""
    return f"{CLIENT_NAME} ({contact.strip()[:200]}) python-httpx"


def _chunks(items: list[str], size: int = 50) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


async def _query(client: httpx.AsyncClient, **params: str) -> dict[str, Any]:
    response = await client.get(API, params={"action": "query", "format": "json", "formatversion": "2", **params})
    response.raise_for_status()
    return response.json().get("query") or {}


def _same(title: str) -> str:
    return title.replace("_", " ").strip()


async def fetch_photos(keys: list[str], *, contact: str,
                       client: httpx.AsyncClient | None = None) -> dict[str, IngredientPhoto | None]:
    """Photos for entries of the fixed list: `{key: photo}` or `{key: None}` when the article has
    no usable free picture. A key is left out of the result when its picture could not be
    downloaded this time, so the caller remembers only definite answers.

    `contact` is the operator's URL or email for the User-Agent (setting `RECIPE_PHOTO_CONTACT`).
    Any number of ingredients costs two API calls per fifty, plus one small download per
    picture, made one after another: Wikimedia answers 429 to anything that looks like a crawl.
    Raises `httpx.HTTPError` when the API itself cannot be reached or refuses.
    """
    pages = {key: PHOTO_PAGES[key] for key in dict.fromkeys(keys) if key in PHOTO_PAGES}
    if not pages:
        return {}
    own = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": user_agent(contact)},
                                         follow_redirects=False)
    try:
        # 1. Each article's free lead image (the API follows redirects and tells us it did).
        file_of: dict[str, str] = {}
        for titles in _chunks(sorted(set(pages.values()))):
            found = await _query(client, prop="pageimages", piprop="name", pilicense="free", redirects="1",
                                 titles="|".join(titles))
            moved = {_same(step["from"]): _same(step["to"])
                     for step in [*found.get("normalized", []), *found.get("redirects", [])]}
            image = {_same(page.get("title", "")): page.get("pageimage") for page in found.get("pages", [])}
            for title in titles:
                final = _same(title)
                for _ in range(3):
                    final = moved.get(final, final)
                if image.get(final):
                    file_of[title] = image[final]

        # 2. Each file's licence, author and thumbnail address.
        info_of: dict[str, dict[str, Any]] = {}
        for names in _chunks(sorted(set(file_of.values()))):
            detail = await _query(client, prop="imageinfo", iiprop="url|extmetadata|mime", iiurlwidth=str(THUMB_WIDTH),
                                  titles="|".join(f"File:{name}" for name in names))
            for page in detail.get("pages", []):
                name = _same(page.get("title", "")).removeprefix("File:")
                info_of[name] = ((page.get("imageinfo") or [{}])[0])

        # 3. The pictures themselves, one at a time.
        result: dict[str, IngredientPhoto | None] = {}
        fetched: dict[str, IngredientPhoto | None] = {}
        for key, title in pages.items():
            file_name = file_of.get(title)
            info = info_of.get(_same(file_name)) if file_name else None
            if not file_name or not info:
                result[key] = None
                continue
            if file_name not in fetched:
                try:
                    fetched[file_name] = await _download(client, file_name, info)
                except httpx.HTTPError as exc:
                    logger.info("ingredient photo %s not downloaded: %s", key, type(exc).__name__)
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                        break                                  # told to slow down: stop, keep what we have
                    continue
            result[key] = fetched[file_name]
        return result
    finally:
        if own:
            await client.aclose()


async def _download(client: httpx.AsyncClient, file_name: str, info: dict[str, Any]) -> IngredientPhoto | None:
    """One picture with its credit, or None when its licence or address is not acceptable."""
    license_name = _meta(info, "LicenseShortName", 80)
    if not is_free_license(license_name) or (info.get("extmetadata") or {}).get("NonFree"):
        logger.info("ingredient photo %s skipped: licence %r", file_name, license_name)
        return None
    thumb = urlparse(str(info.get("thumburl") or ""))
    if thumb.scheme != "https" or thumb.hostname not in IMAGE_HOSTS:
        return None
    picture = await client.get(thumb.geturl())
    picture.raise_for_status()
    content_type = picture.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_TYPES or not 0 < len(picture.content) <= MAX_BYTES:
        return None
    license_url = _meta(info, "LicenseUrl", 600)
    return IngredientPhoto(
        content=picture.content, content_type=content_type,
        title=_plain(file_name, 300).replace("_", " "),
        author=_meta(info, "Artist") or _meta(info, "Credit") or None,
        license_name=license_name,
        license_url=license_url if license_url.startswith("https://") else None,
        source_url=str(info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/File:{file_name}")[:600],
    )
