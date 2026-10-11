"""Pure helpers that turn HTML form fields into model data and back.

Kept free of FastAPI so they can be unit tested. Forms post rows as ``<prefix>_<field>_<idx>``
with a ``<prefix>_idx`` list naming the row ids; this keeps checkboxes aligned with their rows
when HTMX adds or removes rows.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Protocol

from planner.core.models import (
    Event,
    Ingredient,
    KitchenProfile,
    Recipe,
    slugify,
)
from planner.core.units import format_amount


class FormData(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...
    def getlist(self, key: str) -> list[Any]: ...


class FormError(ValueError):
    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


def _s(form: FormData, key: str) -> str:
    v = form.get(key, "")
    return str(v).strip() if v is not None else ""


def split_csv(text: str) -> list[str]:
    return [t.strip() for t in re.split(r"[,\n]", text) if t.strip()]


def parse_pairs(text: str) -> dict[str, str]:
    """``"vegetarian=chili-veg, nut_free=pb-alt"`` (commas or newlines) -> dict."""
    out: dict[str, str] = {}
    for tok in split_csv(text):
        if "=" not in tok:
            raise FormError([f"expected key=value, got {tok!r}"])
        k, v = tok.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def format_pairs(d: Mapping[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in d.items())


def parse_equipment(text: str) -> list[dict[str, Any]]:
    """``"burner, pot@40, oven*2@3"`` -> ``[{type: burner}, {type: pot, capacity_hint: 40}, ...]``."""
    out: list[dict[str, Any]] = []
    for tok in split_csv(text):
        m = re.match(r"^([A-Za-z][\w -]*?)\s*(?:\*\s*(\d+))?\s*(?:@\s*([\d./ ]+))?$", tok)
        if not m:
            raise FormError(
                [f"cannot read equipment {tok!r} (use type, type*count, type@capacity)"]
            )
        item: dict[str, Any] = {"type": m.group(1).strip()}
        if m.group(2):
            item["count"] = int(m.group(2))
        if m.group(3):
            item["capacity_hint"] = m.group(3).strip()
        out.append(item)
    return out


def format_equipment(items: list[Any]) -> str:
    parts = []
    for e in items:
        s = e.type
        if e.count != 1:
            s += f"*{e.count}"
        if e.capacity_hint is not None:
            s += f"@{format_amount(e.capacity_hint)}"
        parts.append(s)
    return ", ".join(parts)


def _int(text: str, what: str, errors: list[str]) -> int | None:
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        errors.append(f"{what}: {text!r} is not a whole number")
        return None


def _rows(
    form: FormData, prefix: str, fields: list[str], checks: list[str]
) -> list[dict[str, Any]]:
    rows = []
    for idx in form.getlist(f"{prefix}_idx"):
        row: dict[str, Any] = {"idx": idx}
        for f in fields:
            row[f] = _s(form, f"{prefix}_{f}_{idx}")
        for c in checks:
            row[c] = form.get(f"{prefix}_{c}_{idx}") is not None
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Recipe

ING_FIELDS = ["ingredient_id", "quantity", "unit", "prep_note", "scaling", "step_size"]
STEP_FIELDS = [
    "id", "title", "instructions", "duration_min", "active_min", "time_scaling", "depends_on",
    "equipment", "earliest_offset", "latest_offset", "day_offset", "hold_min", "hold_max",
    "hold_minutes", "cooks", "per_batch",
]  # fmt: skip


def recipe_form_state(form: FormData) -> dict[str, Any]:
    state: dict[str, Any] = {
        k: _s(form, k)
        for k in ["id", "name", "description", "tags", "base_servings", "portion_basis",
                  "max_batch_servings", "scaling_notes", "source", "diets", "variants"]
    }  # fmt: skip
    state["ingredients"] = _rows(form, "ing", ING_FIELDS, [])
    state["steps"] = _rows(form, "st", STEP_FIELDS, ["cooked", "can_parallelize"])
    return state


def recipe_to_form(r: Recipe | None) -> dict[str, Any]:
    if r is None:
        return {
            "id": "", "name": "", "description": "", "tags": "", "base_servings": "10",
            "portion_basis": "", "max_batch_servings": "", "scaling_notes": "", "source": "",
            "diets": "", "variants": "", "ingredients": [], "steps": [],
        }  # fmt: skip
    return {
        "id": r.id, "name": r.name, "description": r.description, "tags": ", ".join(r.tags),
        "base_servings": format_amount(r.base_servings), "portion_basis": r.portion_basis,
        "max_batch_servings": (
            format_amount(r.max_batch_servings) if r.max_batch_servings is not None else ""
        ),
        "scaling_notes": r.scaling_notes, "source": r.source, "diets": ", ".join(r.diets),
        "variants": format_pairs(r.variants),
        "ingredients": [
            {
                "idx": str(n), "ingredient_id": i.ingredient_id, "quantity": format_amount(i.quantity),
                "unit": i.unit, "prep_note": i.prep_note, "scaling": i.scaling,
                "step_size": format_amount(i.step_size) if i.scaling == "stepped" else "",
            }
            for n, i in enumerate(r.ingredients)
        ],
        "steps": [
            {
                "idx": str(n), "id": s.id, "title": s.title, "instructions": s.instructions,
                "duration_min": str(s.duration_min),
                "active_min": "" if s.active_min is None else str(s.active_min),
                "time_scaling": s.time_scaling, "depends_on": ", ".join(s.depends_on),
                "equipment": format_equipment(s.equipment),
                "earliest_offset": "" if s.earliest_offset is None else str(s.earliest_offset),
                "latest_offset": str(s.latest_offset) if s.latest_offset else "",
                "day_offset": "" if s.day_offset is None else str(s.day_offset),
                "hold_min": "" if not s.hold or s.hold.min_temp_f is None
                else format_amount(s.hold.min_temp_f),
                "hold_max": "" if not s.hold or s.hold.max_temp_f is None
                else format_amount(s.hold.max_temp_f),
                "hold_minutes": "" if not s.hold or s.hold.max_minutes is None
                else str(s.hold.max_minutes),
                "cooks": "" if s.cooks is None else str(s.cooks),
                "per_batch": "" if s.per_batch is None else ("yes" if s.per_batch else "no"),
                "cooked": s.cooked, "can_parallelize": s.can_parallelize_batches,
            }
            for n, s in enumerate(r.steps)
        ],
    }  # fmt: skip


def recipe_data_from_state(state: dict[str, Any], existing: Recipe | None = None) -> dict[str, Any]:
    errors: list[str] = []
    data: dict[str, Any] = {
        "id": state["id"] or slugify(state["name"]),
        "name": state["name"],
        "description": state["description"],
        "tags": split_csv(state["tags"]),
        "base_servings": state["base_servings"],
        "portion_basis": state["portion_basis"],
        "scaling_notes": state["scaling_notes"],
        "source": state["source"],
        "diets": split_csv(state["diets"]),
        "extras": dict(existing.extras) if existing else {},
    }
    if state["max_batch_servings"]:
        data["max_batch_servings"] = state["max_batch_servings"]
    try:
        data["variants"] = parse_pairs(state["variants"])
    except FormError as exc:
        errors.extend(exc.messages)
    ings = []
    for row in state["ingredients"]:
        if not row["ingredient_id"] and not row["quantity"]:
            continue
        item: dict[str, Any] = {
            "ingredient_id": row["ingredient_id"], "quantity": row["quantity"] or "0",
            "unit": row["unit"] or "each", "prep_note": row["prep_note"],
            "scaling": row["scaling"] or "linear",
        }  # fmt: skip
        if row["step_size"]:
            item["step_size"] = row["step_size"]
        ings.append(item)
    data["ingredients"] = ings
    steps = []
    for row in state["steps"]:
        if not row["title"] and not row["id"]:
            continue
        step: dict[str, Any] = {
            "id": row["id"] or slugify(row["title"]),
            "title": row["title"] or row["id"],
            "instructions": row["instructions"],
            "duration_min": _int(row["duration_min"], f"step {row['title']!r} duration", errors)
            or 0,
            "time_scaling": row["time_scaling"] or "none",
            "depends_on": split_csv(row["depends_on"]),
            "cooked": row["cooked"],
            "can_parallelize_batches": row["can_parallelize"],
        }
        for src, dst in [("active_min", "active_min"), ("earliest_offset", "earliest_offset"),
                         ("day_offset", "day_offset"), ("cooks", "cooks")]:  # fmt: skip
            v = _int(row[src], f"step {row['title']!r} {src}", errors)
            if v is not None:
                step[dst] = v
        latest = _int(row["latest_offset"], f"step {row['title']!r} latest_offset", errors)
        if latest is not None:
            step["latest_offset"] = latest
        try:
            step["equipment"] = parse_equipment(row["equipment"])
        except FormError as exc:
            errors.extend(exc.messages)
        hold: dict[str, Any] = {}
        if row["hold_min"]:
            hold["min_temp_f"] = row["hold_min"]
        if row["hold_max"]:
            hold["max_temp_f"] = row["hold_max"]
        hm = _int(row["hold_minutes"], f"step {row['title']!r} hold minutes", errors)
        if hm is not None:
            hold["max_minutes"] = hm
        if hold:
            step["hold"] = hold
        if row["per_batch"] in ("yes", "no"):
            step["per_batch"] = row["per_batch"] == "yes"
        steps.append(step)
    data["steps"] = steps
    if errors:
        raise FormError(errors)
    return data


def format_validation_error(exc: Any) -> list[str]:
    out = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e["loc"])
        out.append(f"{loc}: {e['msg']}" if loc else e["msg"])
    return out


# ---------------------------------------------------------------------------
# Ingredient


def ingredient_form_state(form: FormData) -> dict[str, Any]:
    state: dict[str, Any] = {
        k: _s(form, k)
        for k in ["id", "name", "store_section", "density_g_per_ml", "trim_yield", "allergens",
                  "diet_flags"]
    }  # fmt: skip
    state["shelf_stable"] = form.get("shelf_stable") is not None
    state["packs"] = _rows(form, "pk", ["label", "size", "unit"], [])
    return state


def ingredient_to_form(i: Ingredient | None) -> dict[str, Any]:
    if i is None:
        return {"id": "", "name": "", "store_section": "other", "density_g_per_ml": "",
                "trim_yield": "", "allergens": "", "diet_flags": "", "shelf_stable": False,
                "packs": []}  # fmt: skip
    return {
        "id": i.id, "name": i.name, "store_section": i.store_section,
        "density_g_per_ml": "" if i.density_g_per_ml is None else format_amount(i.density_g_per_ml),
        "trim_yield": "" if i.trim_yield is None else format_amount(i.trim_yield),
        "allergens": ", ".join(i.allergens), "diet_flags": ", ".join(i.diet_flags),
        "shelf_stable": i.shelf_stable,
        "packs": [
            {"idx": str(n), "label": p.label, "size": format_amount(p.size), "unit": p.unit}
            for n, p in enumerate(i.purchase_packs)
        ],
    }  # fmt: skip


def ingredient_data_from_state(
    state: dict[str, Any], existing: Ingredient | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": state["id"] or slugify(state["name"]),
        "name": state["name"],
        "store_section": state["store_section"] or "other",
        "allergens": split_csv(state["allergens"]),
        "diet_flags": split_csv(state["diet_flags"]),
        "shelf_stable": state["shelf_stable"],
        "extras": dict(existing.extras) if existing else {},
        "purchase_packs": [
            {
                "label": p["label"] or f"{p['size']} {p['unit']}",
                "size": p["size"],
                "unit": p["unit"],
            }
            for p in state["packs"]
            if p["size"]
        ],
    }
    if state["density_g_per_ml"]:
        data["density_g_per_ml"] = state["density_g_per_ml"]
    if state["trim_yield"]:
        data["trim_yield"] = state["trim_yield"]
    return data


# ---------------------------------------------------------------------------
# Kitchen


def kitchen_form_state(form: FormData) -> dict[str, Any]:
    state: dict[str, Any] = {
        k: _s(form, k)
        for k in ["id", "name", "description", "max_cooks", "supports_tags", "work_start", "work_end"]
    }  # fmt: skip
    state["equipment"] = _rows(form, "eq", ["type", "count", "capacity", "label"], [])
    return state


def kitchen_to_form(k: KitchenProfile | None) -> dict[str, Any]:
    if k is None:
        return {"id": "", "name": "", "description": "", "max_cooks": "", "supports_tags": "",
                "work_start": "06:00", "work_end": "22:00", "equipment": []}  # fmt: skip
    return {
        "id": k.id, "name": k.name, "description": k.description,
        "max_cooks": "" if k.max_cooks is None else str(k.max_cooks),
        "supports_tags": ", ".join(k.supports_tags),
        "work_start": k.work_start, "work_end": k.work_end,
        "equipment": [
            {"idx": str(n), "type": e.type, "count": str(e.count),
             "capacity": "" if e.capacity is None else format_amount(e.capacity), "label": e.label}
            for n, e in enumerate(k.equipment_inventory)
        ],
    }  # fmt: skip


def kitchen_data_from_state(
    state: dict[str, Any], existing: KitchenProfile | None = None
) -> dict[str, Any]:
    errors: list[str] = []
    items = []
    for row in state["equipment"]:
        if not row["type"]:
            continue
        item: dict[str, Any] = {"type": row["type"], "label": row["label"]}
        n = _int(row["count"], f"{row['type']} count", errors)
        item["count"] = 1 if n is None else n
        if row["capacity"]:
            item["capacity"] = row["capacity"]
        items.append(item)
    data: dict[str, Any] = {
        "id": state["id"] or slugify(state["name"]),
        "name": state["name"],
        "description": state["description"],
        "equipment_inventory": items,
        "supports_tags": split_csv(state["supports_tags"]),
        "work_start": state["work_start"] or "06:00",
        "work_end": state["work_end"] or "22:00",
        "extras": dict(existing.extras) if existing else {},
    }
    mc = _int(state["max_cooks"], "max cooks", errors)
    if mc is not None:
        data["max_cooks"] = mc
    if errors:
        raise FormError(errors)
    return data


# ---------------------------------------------------------------------------
# Event


def event_form_state(form: FormData) -> dict[str, Any]:
    state: dict[str, Any] = {
        k: _s(form, k) for k in ["id", "name", "kitchen_profile_id", "start_date", "days", "notes"]
    }
    meals = []
    for idx in form.getlist("ml_idx"):
        row: dict[str, Any] = {"idx": idx}
        for f in ["day", "label", "serve_time", "headcount", "portion_factor", "splits"]:
            row[f] = _s(form, f"ml_{f}_{idx}")
        row["recipe_ids"] = [str(x) for x in form.getlist(f"ml_recipes_{idx}") if str(x)]
        meals.append(row)
    state["meals"] = meals
    state["pantry"] = _rows(form, "pa", ["ingredient_id", "quantity", "unit"], [])
    return state


def event_to_form(e: Event | None, default_kitchen: str = "") -> dict[str, Any]:
    if e is None:
        import datetime as dt

        return {"id": "", "name": "", "kitchen_profile_id": default_kitchen,
                "start_date": dt.date.today().isoformat(), "days": "2", "notes": "",
                "meals": [], "pantry": []}  # fmt: skip
    return {
        "id": e.id, "name": e.name, "kitchen_profile_id": e.kitchen_profile_id,
        "start_date": e.start_date.isoformat(), "days": str(e.days), "notes": e.notes,
        "meals": [
            {
                "idx": str(n), "day": str(m.day), "label": m.label, "serve_time": m.serve_time,
                "headcount": str(m.headcount), "portion_factor": format_amount(m.portion_factor),
                "splits": format_pairs(m.diet_splits), "recipe_ids": list(m.recipe_ids),
            }
            for n, m in enumerate(e.meals)
        ],
        "pantry": [
            {"idx": str(n), "ingredient_id": p.ingredient_id, "quantity": format_amount(p.quantity),
             "unit": p.unit}
            for n, p in enumerate(e.pantry_on_hand)
        ],
    }  # fmt: skip


def event_data_from_state(state: dict[str, Any], existing: Event | None = None) -> dict[str, Any]:
    errors: list[str] = []
    meals = []
    for row in state["meals"]:
        if not row["label"] and not row["headcount"]:
            continue
        try:
            splits = {k: int(v) for k, v in parse_pairs(row["splits"]).items()}
        except (FormError, ValueError):
            errors.append(
                f"meal {row['label']!r}: diet splits must look like vegetarian=12, nut_free=5"
            )
            splits = {}
        meals.append({
            "day": row["day"] or "0", "label": row["label"], "serve_time": row["serve_time"],
            "recipe_ids": row["recipe_ids"], "headcount": row["headcount"] or "0",
            "portion_factor": row["portion_factor"] or "1", "diet_splits": splits,
        })  # fmt: skip
    data: dict[str, Any] = {
        "id": state["id"] or slugify(state["name"]),
        "name": state["name"],
        "kitchen_profile_id": state["kitchen_profile_id"],
        "start_date": state["start_date"],
        "days": state["days"] or "1",
        "notes": state["notes"],
        "meals": meals,
        "pantry_on_hand": [
            {
                "ingredient_id": p["ingredient_id"],
                "quantity": p["quantity"],
                "unit": p["unit"] or "each",
            }
            for p in state["pantry"]
            if p["ingredient_id"] and p["quantity"]
        ],
        "extras": dict(existing.extras) if existing else {},
    }
    if errors:
        raise FormError(errors)
    return data
