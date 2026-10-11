"""Domain models. Pure pydantic, no database or web imports.

Quantities are ``Fraction``s. They accept ints, decimals and strings such as
``"1 1/2"`` on input and serialise to a number (when exact) or an ``"a/b"`` string.
"""

from __future__ import annotations

import datetime as dt
import re
from fractions import Fraction
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    PlainValidator,
    field_validator,
    model_validator,
)

from planner.core.units import normalize_unit, parse_number

SCHEMA_VERSION = 1


def _validate_qty(value: Any) -> Fraction:
    try:
        return parse_number(value)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def _serialize_qty(x: Fraction) -> int | float | str:
    if x.denominator == 1:
        return x.numerator
    as_float = float(x)
    if Fraction(repr(as_float)) == x:
        return as_float
    return f"{x.numerator}/{x.denominator}"


Qty = Annotated[
    Fraction,
    PlainValidator(_validate_qty),
    PlainSerializer(_serialize_qty, return_type=int | float | str),
]

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def parse_hhmm(text: str) -> int:
    """``"17:30"`` -> minutes after midnight."""
    m = _HHMM.match(text.strip())
    if not m:
        raise ValueError(f"time must be HH:MM, got {text!r}")
    return int(m.group(1)) * 60 + int(m.group(2))


def format_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "item"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_slug(v: str) -> str:
    if not _SLUG.match(v):
        raise ValueError(f"id must be a lowercase slug (a-z, 0-9, - _ .), got {v!r}")
    return v


def _equip_type(v: str) -> str:
    return re.sub(r"[\s-]+", "_", v.strip().lower())


# ---------------------------------------------------------------------------
# Ingredient


class PackSize(_Model):
    label: str
    size: Qty
    unit: str

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        return normalize_unit(v)

    @field_validator("size")
    @classmethod
    def _size(cls, v: Fraction) -> Fraction:
        if v <= 0:
            raise ValueError("pack size must be positive")
        return v


class Ingredient(_Model):
    id: str
    name: str
    store_section: str = "other"
    density_g_per_ml: Qty | None = None
    purchase_packs: list[PackSize] = Field(default_factory=list)
    trim_yield: Qty | None = None
    allergens: list[str] = Field(default_factory=list)
    diet_flags: list[str] = Field(default_factory=list)
    shelf_stable: bool = False
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return _check_slug(v)

    @field_validator("density_g_per_ml")
    @classmethod
    def _density(cls, v: Fraction | None) -> Fraction | None:
        if v is not None and v <= 0:
            raise ValueError("density must be positive")
        return v

    @field_validator("trim_yield")
    @classmethod
    def _trim(cls, v: Fraction | None) -> Fraction | None:
        if v is not None and not (0 < v <= 1):
            raise ValueError("trim_yield must be in (0, 1]")
        return v


# ---------------------------------------------------------------------------
# Recipe

ScalingMode = Literal["linear", "fixed", "stepped"]
TimeScaling = Literal["none", "sqrt", "linear"]


class RecipeIngredient(_Model):
    ingredient_id: str
    quantity: Qty
    unit: str
    prep_note: str = ""
    scaling: ScalingMode = "linear"
    step_size: Qty = Fraction(1)  # used by "stepped": round up to a multiple of this

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        return normalize_unit(v)

    @field_validator("quantity")
    @classmethod
    def _qty(cls, v: Fraction) -> Fraction:
        if v < 0:
            raise ValueError("quantity cannot be negative")
        return v

    @field_validator("step_size")
    @classmethod
    def _step(cls, v: Fraction) -> Fraction:
        if v <= 0:
            raise ValueError("step_size must be positive")
        return v


class EquipmentReq(_Model):
    type: str
    count: int = Field(default=1, ge=1)
    capacity_hint: Qty | None = None  # capacity needed at base_servings (see DECISIONS D36)

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        return _equip_type(v)


class Hold(_Model):
    min_temp_f: Qty | None = None
    max_temp_f: Qty | None = None
    max_minutes: int | None = Field(default=None, ge=0)


class Step(_Model):
    id: str
    title: str
    instructions: str = ""
    duration_min: int = Field(default=0, ge=0)
    active_min: int | None = Field(default=None, ge=0)
    time_scaling: TimeScaling = "none"
    depends_on: list[str] = Field(default_factory=list)
    # minutes before serve time, measured at the END of the step (DECISIONS D37)
    earliest_offset: int | None = Field(default=None, ge=0)
    latest_offset: int = Field(default=0, ge=0)
    day_offset: int | None = Field(default=None, le=0)
    equipment: list[EquipmentReq] = Field(default_factory=list)
    hold: Hold | None = None
    can_parallelize_batches: bool = True
    per_batch: bool | None = None
    cooks: int | None = Field(default=None, ge=0)
    cooked: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return _check_slug(v)

    @model_validator(mode="after")
    def _check(self) -> Step:
        if self.active_min is not None and self.active_min > self.duration_min:
            raise ValueError(f"step {self.id}: active_min cannot exceed duration_min")
        if self.earliest_offset is not None and self.earliest_offset < self.latest_offset:
            raise ValueError(f"step {self.id}: earliest_offset must be >= latest_offset")
        return self

    @property
    def active(self) -> int:
        return self.duration_min if self.active_min is None else self.active_min

    @property
    def is_per_batch(self) -> bool:
        if self.per_batch is not None:
            return self.per_batch
        return any(e.capacity_hint is not None for e in self.equipment)


class Recipe(_Model):
    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    base_servings: Qty
    portion_basis: str = ""
    ingredients: list[RecipeIngredient] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    max_batch_servings: Qty | None = None
    scaling_notes: str = ""
    source: str = ""
    # diet label -> recipe id of a substitute that serves people on that diet
    variants: dict[str, str] = Field(default_factory=dict)
    # diet labels this recipe already satisfies (e.g. ["vegetarian"])
    diets: list[str] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return _check_slug(v)

    @model_validator(mode="before")
    @classmethod
    def _drop_derived(cls, data: Any) -> Any:
        if isinstance(data, dict) and "equipment_required" in data:
            data = {k: v for k, v in data.items() if k != "equipment_required"}
        return data

    @field_validator("base_servings")
    @classmethod
    def _base(cls, v: Fraction) -> Fraction:
        if v <= 0:
            raise ValueError("base_servings must be positive")
        return v

    @field_validator("max_batch_servings")
    @classmethod
    def _maxb(cls, v: Fraction | None) -> Fraction | None:
        if v is not None and v <= 0:
            raise ValueError("max_batch_servings must be positive")
        return v

    @model_validator(mode="after")
    def _check_steps(self) -> Recipe:
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate step ids: {dup}")
        known = set(ids)
        for s in self.steps:
            for d in s.depends_on:
                if d not in known:
                    raise ValueError(f"step {s.id} depends on unknown step {d!r}")
                if d == s.id:
                    raise ValueError(f"step {s.id} depends on itself")
        # cycle detection (Kahn)
        indeg = {s.id: len(set(s.depends_on)) for s in self.steps}
        children: dict[str, list[str]] = {s.id: [] for s in self.steps}
        for s in self.steps:
            for d in set(s.depends_on):
                children[d].append(s.id)
        ready = [i for i, n in indeg.items() if n == 0]
        seen = 0
        while ready:
            cur = ready.pop()
            seen += 1
            for c in children[cur]:
                indeg[c] -= 1
                if indeg[c] == 0:
                    ready.append(c)
        if seen != len(self.steps):
            raise ValueError("steps contain a dependency cycle")
        return self

    @property
    def equipment_required(self) -> list[str]:
        return sorted({e.type for s in self.steps for e in s.equipment})

    @property
    def only_for(self) -> list[str]:
        """Profile tags this recipe is restricted to (``backpacking-only`` -> ``backpacking``)."""
        return sorted(t[: -len("-only")] for t in self.tags if t.endswith("-only"))


# ---------------------------------------------------------------------------
# Kitchen


class EquipmentItem(_Model):
    type: str
    count: int = Field(default=1, ge=0)
    capacity: Qty | None = None
    label: str = ""

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        return _equip_type(v)


class KitchenProfile(_Model):
    id: str
    name: str
    description: str = ""
    equipment_inventory: list[EquipmentItem] = Field(default_factory=list)
    max_cooks: int | None = Field(default=None, ge=1)
    supports_tags: list[str] = Field(default_factory=list)
    work_start: str = "06:00"
    work_end: str = "22:00"
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return _check_slug(v)

    @model_validator(mode="after")
    def _hours(self) -> KitchenProfile:
        if parse_hhmm(self.work_start) >= parse_hhmm(self.work_end):
            raise ValueError("work_start must be before work_end")
        return self

    @property
    def work_start_min(self) -> int:
        return parse_hhmm(self.work_start)

    @property
    def work_end_min(self) -> int:
        return parse_hhmm(self.work_end)

    def units_of(self, equip_type: str) -> list[Fraction | None]:
        """One entry per physical unit of ``equip_type``, holding its capacity."""
        out: list[Fraction | None] = []
        for item in self.equipment_inventory:
            if item.type == equip_type:
                out.extend([item.capacity] * item.count)
        return out

    def max_capacity(self, equip_type: str) -> Fraction | None:
        caps = [c for c in self.units_of(equip_type) if c is not None]
        return max(caps) if caps else None


# ---------------------------------------------------------------------------
# Event


class PantryItem(_Model):
    ingredient_id: str
    quantity: Qty
    unit: str

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        return normalize_unit(v)


class Meal(_Model):
    day: int = Field(ge=0)
    label: str
    serve_time: str
    recipe_ids: list[str] = Field(default_factory=list)
    headcount: int = Field(gt=0)
    diet_splits: dict[str, int] = Field(default_factory=dict)
    portion_factor: Qty = Fraction(1)

    @field_validator("serve_time")
    @classmethod
    def _time(cls, v: str) -> str:
        return format_hhmm(parse_hhmm(v))

    @field_validator("portion_factor")
    @classmethod
    def _pf(cls, v: Fraction) -> Fraction:
        if v <= 0:
            raise ValueError("portion_factor must be positive")
        return v

    @field_validator("diet_splits")
    @classmethod
    def _splits(cls, v: dict[str, int]) -> dict[str, int]:
        if any(n < 0 for n in v.values()):
            raise ValueError("diet split counts cannot be negative")
        return v

    @property
    def serve_minute_of_day(self) -> int:
        return parse_hhmm(self.serve_time)


class Event(_Model):
    id: str
    name: str
    kitchen_profile_id: str
    start_date: dt.date
    days: int = Field(default=1, ge=1)
    meals: list[Meal] = Field(default_factory=list)
    pantry_on_hand: list[PantryItem] = Field(default_factory=list)
    notes: str = ""
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return _check_slug(v)

    @model_validator(mode="after")
    def _days(self) -> Event:
        for m in self.meals:
            if m.day >= self.days:
                raise ValueError(
                    f"meal {m.label!r} is on day {m.day} but event has {self.days} days"
                )
        return self


KINDS: dict[str, type[_Model]] = {
    "ingredients": Ingredient,
    "recipes": Recipe,
    "kitchens": KitchenProfile,
    "events": Event,
}
