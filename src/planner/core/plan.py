"""Event -> Plan: the single resolved object every generator reads.

Pipeline: resolve -> scale -> batch split -> expand step graph -> schedule -> Plan.
Pure functions, no I/O, deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal

from planner.core.graph import StepInstance, expand_recipe
from planner.core.models import Event, Ingredient, KitchenProfile, Meal, Recipe, RecipeIngredient
from planner.core.scaling import BatchPlan, plan_batches, scale_amount, scale_factor
from planner.core.scheduler import PlanWarning, Schedule, ScheduledStep, schedule
from planner.core.settings import PlanSettings
from planner.core.timefmt import MIN_PER_DAY, Clock


@dataclass(frozen=True)
class ScaledLine:
    """One scaled recipe ingredient. ``needed`` is in the recipe's own unit."""

    ingredient_id: str
    unit: str
    needed: Fraction  # total across all batches
    per_batch: Fraction
    base: RecipeIngredient

    @property
    def prep_note(self) -> str:
        return self.base.prep_note


@dataclass(frozen=True)
class PlannedRecipe:
    meal_index: int
    position: int
    recipe: Recipe
    role: Literal["main", "variant"]
    diets: tuple[str, ...]  # diets served by this variant (empty for the main dish)
    people: int
    servings: Fraction  # people * portion_factor
    factor: Fraction  # servings / base_servings
    batch: BatchPlan
    lines: tuple[ScaledLine, ...]

    @property
    def key_prefix(self) -> str:
        return f"m{self.meal_index}p{self.position}:{self.recipe.id}"


@dataclass(frozen=True)
class PlannedMeal:
    index: int
    meal: Meal
    serve_minute: int
    title: str  # e.g. "Saturday dinner"
    recipes: tuple[PlannedRecipe, ...]
    unserved: dict[str, int]


@dataclass
class Plan:
    event: Event
    kitchen: KitchenProfile
    settings: PlanSettings
    clock: Clock
    ingredients: Mapping[str, Ingredient]
    recipes: Mapping[str, Recipe]
    meals: list[PlannedMeal]
    schedule: Schedule
    warnings: list[PlanWarning] = field(default_factory=list)

    @property
    def all_warnings(self) -> list[PlanWarning]:
        return self.warnings + self.schedule.warnings

    @property
    def conflicts(self) -> list[PlanWarning]:
        return [w for w in self.all_warnings if w.level in ("conflict", "error")]

    def steps_for(self, pr: PlannedRecipe) -> list[ScheduledStep]:
        return [
            s
            for s in self.schedule.steps
            if s.instance.meal_index == pr.meal_index and s.instance.position == pr.position
        ]

    def planned_recipes(self) -> list[PlannedRecipe]:
        return [pr for m in self.meals for pr in m.recipes]


def validate_event(
    event: Event,
    recipes: Mapping[str, Recipe],
    ingredients: Mapping[str, Ingredient],
    kitchen: KitchenProfile | None,
) -> list[PlanWarning]:
    """Live validation used by the event builder and by ``build_plan``."""
    out: list[PlanWarning] = []
    clock = Clock(event.start_date)
    if kitchen is None:
        out.append(
            PlanWarning(
                "error", "no_kitchen", f"Kitchen profile {event.kitchen_profile_id!r} not found"
            )
        )
    for mi, meal in enumerate(event.meals):
        title = f"{clock.day_name(meal.day)} {meal.label}"
        for rid in meal.recipe_ids:
            r = recipes.get(rid)
            if r is None:
                out.append(
                    PlanWarning("error", "unknown_recipe", f"{title}: unknown recipe {rid!r}", mi)
                )
                continue
            if kitchen is not None:
                missing = [t for t in r.only_for if t not in kitchen.supports_tags]
                if missing and kitchen.supports_tags:
                    out.append(
                        PlanWarning(
                            "warning",
                            "profile_mismatch",
                            f"{title}: {r.name!r} is tagged {missing[0]}-only but kitchen "
                            f"profile {kitchen.name!r} does not support {missing[0]}",
                            mi,
                        )
                    )
            for ri in r.ingredients:
                if ri.ingredient_id not in ingredients:
                    out.append(
                        PlanWarning(
                            "warning",
                            "unknown_ingredient",
                            f"{r.name}: ingredient {ri.ingredient_id!r} is not in the catalog",
                            mi,
                        )
                    )
        total_split = sum(meal.diet_splits.values())
        if total_split > meal.headcount:
            out.append(
                PlanWarning(
                    "warning",
                    "splits_exceed_headcount",
                    f"{title}: diet splits ({total_split}) exceed headcount ({meal.headcount})",
                    mi,
                )
            )
    unique: list[PlanWarning] = []
    done: set[tuple[str, str]] = set()
    for w in out:
        if (w.code, w.message) not in done:
            done.add((w.code, w.message))
            unique.append(w)
    return unique


def _lines(recipe: Recipe, factor: Fraction, n_batches: int) -> tuple[ScaledLine, ...]:
    return tuple(
        ScaledLine(
            ri.ingredient_id,
            ri.unit,
            scale_amount(ri, factor, n_batches),
            scale_amount(ri, factor, n_batches) / n_batches,
            ri,
        )
        for ri in recipe.ingredients
    )


def _plan_recipe(
    recipe: Recipe,
    *,
    meal_index: int,
    position: int,
    role: Literal["main", "variant"],
    diets: tuple[str, ...],
    people: int,
    portion_factor: Fraction,
    caps: Mapping[str, Fraction | None],
) -> PlannedRecipe:
    servings = Fraction(people) * portion_factor
    factor = scale_factor(people, portion_factor, recipe.base_servings)
    batch = plan_batches(recipe, servings, caps)
    return PlannedRecipe(
        meal_index,
        position,
        recipe,
        role,
        diets,
        people,
        servings,
        factor,
        batch,
        _lines(recipe, factor, batch.n_batches),
    )


def build_plan(
    event: Event,
    *,
    recipes: Mapping[str, Recipe],
    ingredients: Mapping[str, Ingredient],
    kitchen: KitchenProfile,
    settings: PlanSettings | None = None,
) -> Plan:
    settings = settings or PlanSettings()
    clock = Clock(event.start_date)
    warnings = validate_event(event, recipes, ingredients, kitchen)
    caps: dict[str, Fraction | None] = {
        item.type: kitchen.max_capacity(item.type) for item in kitchen.equipment_inventory
    }

    meals: list[PlannedMeal] = []
    instances: list[StepInstance] = []
    labels: dict[int, str] = {}
    for mi, meal in enumerate(event.meals):
        serve_minute = meal.day * MIN_PER_DAY + meal.serve_minute_of_day
        title = f"{clock.day_name(meal.day)} {meal.label}"
        labels[mi] = title
        planned: list[PlannedRecipe] = []
        unserved: dict[str, int] = {}
        pos = 0
        for rid in meal.recipe_ids:
            recipe = recipes.get(rid)
            if recipe is None:
                continue
            base_people = meal.headcount
            variant_people: dict[str, tuple[int, list[str]]] = {}
            for diet in sorted(meal.diet_splits):
                count = meal.diet_splits[diet]
                if count <= 0 or diet in recipe.diets:
                    continue
                vid = recipe.variants.get(diet)
                if vid is not None and vid in recipes:
                    n, ds = variant_people.get(vid, (0, []))
                    variant_people[vid] = (n + count, ds + [diet])
                else:
                    unserved[diet] = unserved.get(diet, 0) + count
                    why = f"variant {vid!r} not found" if vid else f"{recipe.name!r} has no variant"
                    warnings.append(
                        PlanWarning(
                            "warning",
                            "diet_unserved",
                            f"{title}: {count} x {diet} cannot eat {recipe.name!r} ({why})",
                            mi,
                        )
                    )
                base_people -= count
            base_people = max(0, base_people)
            if base_people > 0:
                planned.append(
                    _plan_recipe(
                        recipe,
                        meal_index=mi,
                        position=pos,
                        role="main",
                        diets=(),
                        people=base_people,
                        portion_factor=meal.portion_factor,
                        caps=caps,
                    )
                )
                pos += 1
            for vid in sorted(variant_people):
                n, ds = variant_people[vid]
                planned.append(
                    _plan_recipe(
                        recipes[vid],
                        meal_index=mi,
                        position=pos,
                        role="variant",
                        diets=tuple(sorted(ds)),
                        people=n,
                        portion_factor=meal.portion_factor,
                        caps=caps,
                    )
                )
                pos += 1
        for pr in planned:
            instances.extend(
                expand_recipe(
                    pr.recipe,
                    servings=pr.servings,
                    batch_counts=pr.batch.step_batches,
                    meal_index=mi,
                    position=pr.position,
                    serve_minute=serve_minute,
                    meal_day=meal.day,
                )
            )
        meals.append(PlannedMeal(mi, meal, serve_minute, title, tuple(planned), unserved))

    sched = schedule(instances, kitchen, settings, clock, labels)
    sched.warnings.extend(safety_warnings(sched, settings, clock, labels))
    return Plan(event, kitchen, settings, clock, ingredients, recipes, meals, sched, warnings)


def safety_warnings(
    sched: Schedule, settings: PlanSettings, clock: Clock, labels: Mapping[int, str]
) -> list[PlanWarning]:
    """Informational food-safety hints. Warnings only, never guarantees."""
    out: list[PlanWarning] = []
    next_start: dict[str, int] = {}
    for s in sched.steps:
        for d in s.instance.deps:
            next_start[d] = min(next_start.get(d, s.start), s.start)
    limit = settings.out_of_temp_min
    for s in sched.steps:
        i = s.instance
        who = f"{labels.get(i.meal_index, '')}: {i.recipe_name} - {i.title}".lstrip(": ")
        h = i.hold
        if h is not None:
            if h.min_temp_f is not None and h.min_temp_f < settings.hot_hold_f:
                out.append(
                    PlanWarning(
                        "warning",
                        "hot_hold_low",
                        f"{who}: hot hold at {h.min_temp_f} F is below {settings.hot_hold_f} F",
                        i.meal_index,
                    )
                )
            if h.max_temp_f is not None and h.max_temp_f > settings.cold_hold_f:
                out.append(
                    PlanWarning(
                        "warning",
                        "cold_hold_high",
                        f"{who}: cold hold at {h.max_temp_f} F is above {settings.cold_hold_f} F",
                        i.meal_index,
                    )
                )
            if h.min_temp_f is None and h.max_temp_f is None and ((h.max_minutes or 0) > limit):
                out.append(
                    PlanWarning(
                        "warning",
                        "hold_too_long",
                        f"{who}: held {h.max_minutes} min with no temperature control "
                        f"(limit {limit} min)",
                        i.meal_index,
                    )
                )
            if h.max_minutes is not None and i.duration > h.max_minutes:
                out.append(
                    PlanWarning(
                        "warning",
                        "hold_exceeded",
                        f"{who}: scheduled hold of {i.duration} min exceeds "
                        f"max {h.max_minutes} min",
                        i.meal_index,
                    )
                )
        if i.cooked:
            nxt = next_start.get(i.key, i.serve_minute)
            gap = nxt - s.end
            allowed = limit
            if h is not None and h.max_minutes is not None:
                allowed = h.max_minutes
            controlled = h is not None and (h.min_temp_f is not None or h.max_temp_f is not None)
            if gap > allowed and not (controlled and h is not None and h.max_minutes is None):
                out.append(
                    PlanWarning(
                        "warning",
                        "out_of_temp",
                        f"{who}: cooked food waits {gap} min before it is used or served "
                        f"({clock.describe(s.end)} to {clock.describe(nxt)}); keep it at or above "
                        f"{settings.hot_hold_f} F or at or below {settings.cold_hold_f} F, "
                        f"or limit to {allowed} min",
                        i.meal_index,
                    )
                )
    seen: set[str] = set()
    unique: list[PlanWarning] = []
    for w in out:  # batch copies of a step produce identical hints
        if w.message not in seen:
            seen.add(w.message)
            unique.append(w)
    return unique
