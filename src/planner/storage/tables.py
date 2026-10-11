"""SQLModel tables. Scalars are indexed columns; the full model lives in ``data`` (JSON).

See docs/DECISIONS.md D35: the DB layout never matters to import/export.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class IngredientRow(SQLModel, table=True):
    __tablename__ = "ingredient"
    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    store_section: str = ""
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class RecipeRow(SQLModel, table=True):
    __tablename__ = "recipe"
    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    tags: str = ""  # "|a|b|" so LIKE '%|a|%' matches whole tags
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class KitchenRow(SQLModel, table=True):
    __tablename__ = "kitchen"
    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class EventRow(SQLModel, table=True):
    __tablename__ = "event"
    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    start_date: str = ""
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
