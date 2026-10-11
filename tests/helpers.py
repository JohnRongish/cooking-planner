"""Small builders so tests stay readable."""

from __future__ import annotations

import datetime as dt
from typing import Any

from planner.core.models import Event, Ingredient, KitchenProfile, Recipe


def kitchen(**inv: Any) -> KitchenProfile:
    """kitchen(burner=4, oven=2, max_cooks=3, pot=[(2, 40)])"""
    max_cooks = inv.pop("max_cooks", None)
    items = []
    for t, v in inv.items():
        if isinstance(v, list):
            items.extend({"type": t, "count": c, "capacity": cap} for c, cap in v)
        else:
            items.append({"type": t, "count": v})
    return KitchenProfile.model_validate(
        {
            "id": "k",
            "name": "Test kitchen",
            "equipment_inventory": items,
            "max_cooks": max_cooks,
            "supports_tags": ["bulk"],
        }
    )


def step(sid: str, dur: int, **kw: Any) -> dict[str, Any]:
    return {"id": sid, "title": sid.replace("_", " ").title(), "duration_min": dur, **kw}


def recipe(rid: str = "r", steps: list[dict[str, Any]] | None = None, **kw: Any) -> Recipe:
    data: dict[str, Any] = {
        "id": rid,
        "name": rid.title(),
        "base_servings": kw.pop("base_servings", 10),
        "steps": steps or [],
        **kw,
    }
    return Recipe.model_validate(data)


def event(meals: list[dict[str, Any]], days: int = 3, **kw: Any) -> Event:
    return Event.model_validate(
        {
            "id": "e",
            "name": "Test event",
            "kitchen_profile_id": "k",
            "start_date": dt.date(2025, 6, 6),  # a Friday
            "days": days,
            "meals": meals,
            **kw,
        }
    )


def meal(
    day: int = 0,
    label: str = "dinner",
    time: str = "18:00",
    recipes: list[str] | None = None,
    headcount: int = 10,
    **kw: Any,
) -> dict[str, Any]:
    return {
        "day": day,
        "label": label,
        "serve_time": time,
        "recipe_ids": recipes or ["r"],
        "headcount": headcount,
        **kw,
    }


def ingredient(iid: str, **kw: Any) -> Ingredient:
    return Ingredient.model_validate({"id": iid, "name": iid.title(), **kw})
