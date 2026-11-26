"""SQLAlchemy repository for the Recipes mode.

Every method that touches a recipe takes the owner's `user_id` and puts it in the WHERE
clause, so a caller cannot read, save or delete another user's recipe even with a valid id.
Ingredient photos are the one shared thing: public, freely licensed pictures keyed by a fixed
ingredient name.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_system.adapters.outbound.persistence.recipe_models import (
    IngredientImageModel,
    RecipeImageModel,
    RecipeModel,
)
from agent_system.domain.recipes.models import Recipe, RecipeSource


class SQLAlchemyRecipeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- reading ----------------------------------------------------------

    async def get(self, recipe_id: str, user_id: str) -> RecipeModel | None:
        stmt = select(RecipeModel).where(RecipeModel.id == recipe_id, RecipeModel.user_id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def library(self, user_id: str) -> list[RecipeModel]:
        """Everything the user can search: their cookbooks plus whatever they saved."""
        stmt = select(RecipeModel).where(
            RecipeModel.user_id == user_id,
            or_(RecipeModel.source == RecipeSource.COOKBOOK.value, RecipeModel.saved.is_(True)),
        )
        return list((await self._session.execute(stmt)).scalars())

    async def saved(self, user_id: str) -> list[RecipeModel]:
        stmt = (
            select(RecipeModel)
            .where(RecipeModel.user_id == user_id, RecipeModel.saved.is_(True))
            .order_by(RecipeModel.saved_at.desc(), RecipeModel.title)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def cookbook_count(self, user_id: str) -> int:
        stmt = select(func.count()).select_from(RecipeModel).where(
            RecipeModel.user_id == user_id, RecipeModel.source == RecipeSource.COOKBOOK.value)
        return int((await self._session.execute(stmt)).scalar_one())

    # ---- writing ----------------------------------------------------------

    async def upsert_cookbook(self, user_id: str, origin_key: str, book_id: str, recipe: Recipe) -> bool:
        """Add or refresh one cookbook entry. Returns True when it was new. The saved flag and
        any picture of an existing row are kept."""
        stmt = select(RecipeModel).where(
            RecipeModel.user_id == user_id, RecipeModel.source == RecipeSource.COOKBOOK.value,
            RecipeModel.origin_key == origin_key)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        data = recipe.model_dump(mode="json")
        if row is None:
            self._session.add(RecipeModel(
                id=str(uuid4()), user_id=user_id, source=RecipeSource.COOKBOOK.value, origin_key=origin_key,
                book_id=book_id, title=recipe.title, category=recipe.category, data=data, saved=False,
                image_status="none", created_at=datetime.utcnow()))
            return True
        row.book_id, row.title, row.category, row.data = book_id, recipe.title, recipe.category, data
        return False

    async def add(self, user_id: str, recipe: Recipe, *, saved: bool) -> RecipeModel:
        """Store a model-written or web recipe. A web page the user already has (kept or merely
        shown) is returned as it is instead of being stored twice; its saved flag is not touched."""
        origin = recipe.source_url[:600] if recipe.source is RecipeSource.WEB and recipe.source_url else None
        if origin is not None:
            stmt = select(RecipeModel).where(
                RecipeModel.user_id == user_id, RecipeModel.source == RecipeSource.WEB.value,
                RecipeModel.origin_key == origin)
            existing = (await self._session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                return existing
        now = datetime.utcnow()
        row = RecipeModel(
            id=str(uuid4()), user_id=user_id, source=recipe.source.value, origin_key=origin, book_id=None,
            title=recipe.title, category=recipe.category, data=recipe.model_dump(mode="json"), saved=saved,
            saved_at=now if saved else None, image_status="none", created_at=now)
        self._session.add(row)
        await self._session.flush()
        return row

    async def set_saved(self, recipe_id: str, user_id: str, saved: bool) -> RecipeModel | None:
        row = await self.get(recipe_id, user_id)
        if row is None:
            return None
        if row.saved != saved:
            row.saved, row.saved_at = saved, (datetime.utcnow() if saved else None)
            await self._session.flush()
        return row

    async def delete(self, recipe_id: str, user_id: str) -> bool:
        """Remove a recipe and its picture for good."""
        if await self.get(recipe_id, user_id) is None:
            return False
        await self._session.execute(delete(RecipeImageModel).where(RecipeImageModel.recipe_id == recipe_id))
        await self._session.execute(
            delete(RecipeModel).where(RecipeModel.id == recipe_id, RecipeModel.user_id == user_id))
        return True

    async def delete_cookbooks(self, user_id: str) -> int:
        """Remove the user's imported cookbooks (and their pictures). Saved model and web recipes stay."""
        ids = select(RecipeModel.id).where(RecipeModel.user_id == user_id,
                                           RecipeModel.source == RecipeSource.COOKBOOK.value)
        await self._session.execute(delete(RecipeImageModel).where(RecipeImageModel.recipe_id.in_(ids)))
        result = await self._session.execute(
            delete(RecipeModel).where(RecipeModel.user_id == user_id, RecipeModel.source == RecipeSource.COOKBOOK.value))
        return result.rowcount or 0

    # ---- dish pictures ----------------------------------------------------

    async def set_image_status(self, recipe_id: str, user_id: str, status: str, note: str | None = None) -> None:
        row = await self.get(recipe_id, user_id)
        if row is not None:
            row.image_status, row.image_note = status, (note or None) and note[:300]
            await self._session.flush()

    async def put_image(self, recipe_id: str, user_id: str, *, content: bytes, content_type: str, prompt: str,
                        model: str, cost_usd: float | None) -> None:
        await self._session.execute(delete(RecipeImageModel).where(RecipeImageModel.recipe_id == recipe_id))
        self._session.add(RecipeImageModel(recipe_id=recipe_id, user_id=user_id, content=content,
                                           content_type=content_type, prompt=prompt, model=model, cost_usd=cost_usd,
                                           created_at=datetime.utcnow()))
        await self._session.flush()

    async def get_image(self, recipe_id: str, user_id: str) -> RecipeImageModel | None:
        stmt = select(RecipeImageModel).where(RecipeImageModel.recipe_id == recipe_id,
                                              RecipeImageModel.user_id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def images_since(self, user_id: str, since: datetime) -> int:
        """How many dish pictures were made for this user since `since` (the daily cap)."""
        stmt = select(func.count()).select_from(RecipeImageModel).where(
            RecipeImageModel.user_id == user_id, RecipeImageModel.created_at >= since)
        return int((await self._session.execute(stmt)).scalar_one())

    # ---- ingredient photos (shared) ----------------------------------------

    async def get_ingredient_image(self, key: str) -> IngredientImageModel | None:
        return await self._session.get(IngredientImageModel, key)

    async def put_ingredient_image(self, key: str, *, status: str, content: bytes | None = None,
                                   content_type: str | None = None, title: str | None = None,
                                   author: str | None = None, license_name: str | None = None,
                                   license_url: str | None = None, source_url: str | None = None) -> IngredientImageModel:
        row = await self._session.get(IngredientImageModel, key)
        if row is None:
            row = IngredientImageModel(key=key, status=status)
            self._session.add(row)
        row.status, row.content, row.content_type = status, content, content_type
        row.title, row.author = (title or None) and title[:300], (author or None) and author[:300]
        row.license_name, row.license_url = (license_name or None) and license_name[:80], (license_url or None) and license_url[:600]
        row.source_url, row.fetched_at = (source_url or None) and source_url[:600], datetime.utcnow()
        await self._session.flush()
        return row

    async def ingredient_credits(self, keys: list[str]) -> list[IngredientImageModel]:
        if not keys:
            return []
        stmt = select(IngredientImageModel).where(IngredientImageModel.key.in_(keys),
                                                  IngredientImageModel.status == "done")
        return list((await self._session.execute(stmt)).scalars())
