"""SQLAlchemy models for the Recipes mode: recipes, dish pictures and ingredient pictures.

Imported from `persistence/__init__.py` so `Base.metadata.create_all` at startup creates the
tables; there is no migration tool in this project, so these are new tables.

One `recipes` table holds three kinds of row, all owned by one user:

* cookbook recipes that user imported (`source="cookbook"`): their private library;
* recipes a model wrote for them and recipes read from a web page, which exist only
  because the user kept them.

`saved` marks the rows on the user's own list. Taking a cookbook recipe off the list clears
the flag and keeps the recipe in the library; taking a model or web recipe off deletes it.

Pictures are stored here as bytes and served by the API. The frontend's Content-Security-Policy
allows images from this app only (`img-src 'self' data: blob:`), which is the point: no
address that a model or a web page supplied is ever loaded by the browser.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from agent_system.adapters.outbound.persistence.database import Base


class RecipeModel(Base):
    __tablename__ = "recipes"
    __table_args__ = (
        Index("ix_recipes_user_saved", "user_id", "saved"),
        # One row per cookbook entry per owner, so importing the same file twice updates in place.
        UniqueConstraint("user_id", "source", "origin_key", name="uq_recipes_user_origin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))                    # cookbook | model | web
    # Cookbook: the entry's id in the file. Web: the page address. Model: None (never deduplicated;
    # NULLs do not collide in a unique constraint).
    origin_key: Mapped[str | None] = mapped_column(String(600), nullable=True)
    book_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(40), default="other")
    data: Mapped[dict[str, Any]] = mapped_column(JSON)                 # a validated domain `Recipe`
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # none | pending | done | failed | capped | no_key
    image_status: Mapped[str] = mapped_column(String(20), default="none")
    image_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RecipeImageModel(Base):
    """The generated picture of one dish. One per recipe."""

    __tablename__ = "recipe_images"

    recipe_id: Mapped[str] = mapped_column(String(36), ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str] = mapped_column(String(40))
    prompt: Mapped[str] = mapped_column(Text)                          # built in code from the recipe
    model: Mapped[str] = mapped_column(String(64))
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class IngredientImageModel(Base):
    """A freely licensed photo of an ingredient, fetched once and shared by every user.

    The key is one of a fixed list in code (`domain/recipes/photo_keys.py`), never free
    text, so the table cannot be filled by asking for made-up ingredients. A row with
    `status="missing"` records that the lookup found nothing usable, so it is not repeated.
    """

    __tablename__ = "ingredient_images"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))                    # done | missing
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)        # the photo's file title
    author: Mapped[str | None] = mapped_column(String(300), nullable=True)
    license_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    license_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(600), nullable=True)   # the photo's page on Wikimedia Commons
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
