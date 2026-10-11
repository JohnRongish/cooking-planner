"""Recipe scaling, portion factors, batch splitting. Exact arithmetic only."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction

from planner.core.models import Recipe, RecipeIngredient, TimeScaling


def scale_factor(
    headcount: int | Fraction, portion_factor: Fraction, base_servings: Fraction
) -> Fraction:
    """``headcount * portion_factor / base_servings``."""
    return Fraction(headcount) * portion_factor / base_servings


def scale_amount(ri: RecipeIngredient, factor: Fraction, n_batches: int = 1) -> Fraction:
    """Total recipe amount (in ``ri.unit``) for the whole run across all batches.

    * ``linear``: ``quantity * factor``
    * ``fixed``: does not scale with head count, but every batch gets its own
      (a bay leaf per pot): ``quantity * n_batches``
    * ``stepped``: scales in chunks; each batch rounds *up* to a multiple of
      ``step_size`` (whole eggs, whole cans).
    """
    if ri.scaling == "fixed":
        return ri.quantity * n_batches
    if ri.scaling == "stepped":
        per_batch = ri.quantity * factor / n_batches
        chunks = math.ceil(per_batch / ri.step_size)
        return Fraction(chunks) * ri.step_size * n_batches
    return ri.quantity * factor


def purchase_quantity(needed: Fraction, trim_yield: Fraction | None) -> Fraction:
    """Amount to buy so that, after trimming, ``needed`` remains."""
    if trim_yield is None:
        return needed
    return needed / trim_yield


def _ceil_sqrt(x: Fraction) -> int:
    n = math.ceil(x)
    m = math.isqrt(n)
    return m + 1 if m * m < n else m


def scale_minutes(minutes: int, mode: TimeScaling, scale: Fraction) -> int:
    """Scale a duration. ``scale`` is servings per batch / base servings.

    Always rounds up to a whole minute; a non-zero duration never drops below 1.
    """
    if minutes == 0 or mode == "none":
        return minutes
    if mode == "linear":
        out = math.ceil(minutes * scale)
    else:  # sqrt
        out = _ceil_sqrt(Fraction(minutes) ** 2 * scale)
    return max(1, out)


@dataclass(frozen=True)
class BatchPlan:
    """How a recipe is split.

    ``n_batches`` is the recipe-level headline ("Make 3 batches"): the largest count any
    step needs. ``step_batches`` holds the count for each per-batch step, so a sauce that
    fits one pot is not copied just because the meatballs need four oven loads.
    """

    n_batches: int
    servings_per_batch: Fraction
    reasons: list[str] = field(default_factory=list)
    step_batches: Mapping[str, int] = field(default_factory=dict)

    @property
    def is_split(self) -> bool:
        return self.n_batches > 1

    def batches_for(self, step_id: str) -> int:
        return self.step_batches.get(step_id, 1)


def plan_batches(
    recipe: Recipe,
    servings: Fraction,
    max_capacity_by_type: Mapping[str, Fraction | None] | None = None,
) -> BatchPlan:
    """Split into equal batches, per step.

    A per-batch step needs at least ``ceil(servings / max_batch_servings)`` copies, and
    enough copies that its ``capacity_hint`` (scaled to the batch) fits the largest unit of
    that equipment type in the kitchen.
    """
    reasons: list[str] = []
    cap_total = max(1, math.ceil(servings))
    n_max = 1
    if recipe.max_batch_servings is not None and servings > recipe.max_batch_servings:
        n_max = min(cap_total, math.ceil(servings / recipe.max_batch_servings))
        reasons.append(f"max {recipe.max_batch_servings} servings per batch")
    caps = max_capacity_by_type or {}
    step_batches: dict[str, int] = {}
    noted: set[str] = set()
    for step in recipe.steps:
        if not step.is_per_batch:
            continue
        n = n_max
        for eq in step.equipment:
            cap = caps.get(eq.type)
            if eq.capacity_hint is None or cap is None or cap <= 0:
                continue
            need = eq.capacity_hint * servings / recipe.base_servings
            n_eq = min(cap_total, math.ceil(need / cap))
            if n_eq > n:
                n = n_eq
                if eq.type not in noted:
                    noted.add(eq.type)
                    reasons.append(f"largest {eq.type.replace('_', ' ')} holds {cap}")
        step_batches[step.id] = n
    n_recipe = max([n_max, *step_batches.values()])
    return BatchPlan(n_recipe, servings / n_recipe, reasons, step_batches)
