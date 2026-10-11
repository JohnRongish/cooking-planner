"""Repositories: one generic, typed-by-kind store over the four tables."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar, cast

from sqlalchemy import delete
from sqlmodel import Session, SQLModel, col, select

from planner.core.models import Event, Ingredient, KitchenProfile, Recipe
from planner.storage.tables import EventRow, IngredientRow, KitchenRow, RecipeRow

M = TypeVar("M", Ingredient, Recipe, KitchenProfile, Event)

KINDS: dict[str, tuple[type[Any], type[Any]]] = {
    "ingredients": (Ingredient, IngredientRow),
    "recipes": (Recipe, RecipeRow),
    "kitchens": (KitchenProfile, KitchenRow),
    "events": (Event, EventRow),
}


def _row_for(model: Ingredient | Recipe | KitchenProfile | Event) -> SQLModel:
    data = model.model_dump(mode="json")
    if isinstance(model, Ingredient):
        return IngredientRow(
            id=model.id, name=model.name, store_section=model.store_section, data=data
        )
    if isinstance(model, Recipe):
        tags = "|" + "|".join(model.tags) + "|" if model.tags else ""
        return RecipeRow(id=model.id, name=model.name, tags=tags, data=data)
    if isinstance(model, KitchenProfile):
        return KitchenRow(id=model.id, name=model.name, data=data)
    return EventRow(
        id=model.id, name=model.name, start_date=model.start_date.isoformat(), data=data
    )


class Repository:
    def __init__(self, session: Session) -> None:
        self.s = session

    # generic ---------------------------------------------------------------
    def all_of(self, kind: str) -> list[Any]:
        model, row = KINDS[kind]
        rows = self.s.exec(select(row).order_by(col(row.name), col(row.id))).all()
        return [model.model_validate(r.data) for r in rows]

    def get(self, kind: str, id_: str) -> Any | None:
        model, row = KINDS[kind]
        r = self.s.get(row, id_)
        return model.model_validate(r.data) if r else None

    def exists(self, kind: str, id_: str) -> bool:
        return self.s.get(KINDS[kind][1], id_) is not None

    def upsert(self, m: Ingredient | Recipe | KitchenProfile | Event, commit: bool = True) -> None:
        row = _row_for(m)
        self.s.merge(row)
        if commit:
            self.s.commit()

    def delete(self, kind: str, id_: str) -> bool:
        r = self.s.get(KINDS[kind][1], id_)
        if r is None:
            return False
        self.s.delete(r)
        self.s.commit()
        return True

    def wipe(self, commit: bool = True) -> None:
        for _, row in KINDS.values():
            self.s.exec(delete(row))
        if commit:
            self.s.commit()

    def count(self, kind: str) -> int:
        return len(self.s.exec(select(KINDS[kind][1].id)).all())

    # typed helpers ---------------------------------------------------------
    def ingredients(self) -> list[Ingredient]:
        return cast(list[Ingredient], self.all_of("ingredients"))

    def recipes(self, tag: str | None = None, q: str | None = None) -> list[Recipe]:
        stmt = select(RecipeRow).order_by(col(RecipeRow.name), col(RecipeRow.id))
        if tag:
            stmt = stmt.where(col(RecipeRow.tags).like(f"%|{tag}|%"))
        if q:
            stmt = stmt.where(col(RecipeRow.name).like(f"%{q}%"))
        return [Recipe.model_validate(r.data) for r in self.s.exec(stmt).all()]

    def kitchens(self) -> list[KitchenProfile]:
        return cast(list[KitchenProfile], self.all_of("kitchens"))

    def events(self) -> list[Event]:
        return cast(list[Event], self.all_of("events"))

    def recipe_tags(self) -> list[str]:
        tags: set[str] = set()
        for t in self.s.exec(select(RecipeRow.tags)).all():
            tags.update(x for x in t.split("|") if x)
        return sorted(tags)

    def recipes_using_ingredient(self, ingredient_id: str) -> list[Recipe]:
        return [
            r
            for r in self.recipes()
            if any(i.ingredient_id == ingredient_id for i in r.ingredients)
        ]

    def events_using_recipe(self, recipe_id: str) -> list[Event]:
        return [e for e in self.events() if any(recipe_id in m.recipe_ids for m in e.meals)]

    def events_using_kitchen(self, kitchen_id: str) -> list[Event]:
        return [e for e in self.events() if e.kitchen_profile_id == kitchen_id]

    def catalog(self) -> tuple[dict[str, Ingredient], dict[str, Recipe], dict[str, KitchenProfile]]:
        return (
            {i.id: i for i in self.ingredients()},
            {r.id: r for r in self.recipes()},
            {k.id: k for k in self.kitchens()},
        )


def sorted_ids(models: Sequence[Any]) -> list[Any]:
    return sorted(models, key=lambda m: m.id)
