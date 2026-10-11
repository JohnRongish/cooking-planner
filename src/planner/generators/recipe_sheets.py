"""Recipe sheets: each recipe scaled to its head count, with batch splits spelled out."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from planner.core import units as u
from planner.core.plan import Plan, PlannedRecipe, ScaledLine
from planner.generators import base

_METRIC = {"g", "kg", "ml", "l"}


@dataclass(frozen=True)
class SheetIngredient:
    name: str
    amount: str
    per_batch: str
    prep_note: str
    note: str  # e.g. "does not scale"
    allergens: tuple[str, ...]


@dataclass(frozen=True)
class SheetStep:
    number: int
    title: str
    instructions: str
    minutes: str
    when: str
    equipment: str
    batch_note: str
    hold: str


@dataclass(frozen=True)
class Sheet:
    title: str
    meal: str
    serve: str
    people: int
    servings: str
    portion_basis: str
    diets: str
    batch_statement: str
    batch_reasons: str
    ingredients: tuple[SheetIngredient, ...]
    steps: tuple[SheetStep, ...]
    scaling_notes: str
    description: str
    source: str
    tags: tuple[str, ...]
    allergens: tuple[str, ...]
    equipment: tuple[str, ...]


@dataclass
class RecipeSheetsData:
    sheets: list[Sheet] = field(default_factory=list)


def _amount(plan: Plan, amount: object, unit: str) -> str:
    from fractions import Fraction

    assert isinstance(amount, Fraction)
    base_amt, family = u.to_base(amount, unit)
    if unit == "pinch" or u.is_count(family):
        return u.format_quantity(amount, unit)
    system = "metric" if unit in _METRIC else plan.settings.units
    h_amt, h_unit = u.humanize(base_amt, family, system)
    return u.format_quantity(h_amt, h_unit)


def _ingredient_row(plan: Plan, pr: PlannedRecipe, ln: ScaledLine) -> SheetIngredient:
    ing = plan.ingredients.get(ln.ingredient_id)
    n = pr.batch.n_batches
    note = ""
    if ln.base.scaling == "fixed":
        note = "does not scale" + (" (per batch)" if n > 1 else "")
    elif ln.base.scaling == "stepped":
        note = "whole units"
    return SheetIngredient(
        name=ing.name if ing else ln.ingredient_id,
        amount=_amount(plan, ln.needed, ln.unit),
        per_batch=_amount(plan, ln.per_batch, ln.unit) if n > 1 else "",
        prep_note=ln.prep_note,
        note=note,
        allergens=tuple(ing.allergens) if ing else (),
    )


def _sheet(plan: Plan, pr: PlannedRecipe) -> Sheet:
    meal = plan.meals[pr.meal_index]
    sched = plan.steps_for(pr)
    by_step: dict[str, list[int]] = {}
    ends: dict[str, int] = {}
    for s in sched:
        by_step.setdefault(s.instance.step_id, []).append(s.start)
        ends[s.instance.step_id] = max(ends.get(s.instance.step_id, s.end), s.end)
    n = pr.batch.n_batches
    steps: list[SheetStep] = []
    for idx, st in enumerate(pr.recipe.steps, start=1):
        starts = by_step.get(st.id, [])
        when = ""
        if starts:
            first, last_end = min(starts), ends[st.id]
            when = f"{plan.clock.describe(first)} to {plan.clock.tod(last_end)}"
        inst = next((s.instance for s in sched if s.instance.step_id == st.id), None)
        batch_note = ""
        if n > 1 and st.is_per_batch:
            batch_note = f"Do this for each of the {n} batches"
            if not st.can_parallelize_batches:
                batch_note += ", one after another"
        hold = ""
        if st.hold is not None:
            bits = []
            if st.hold.min_temp_f is not None:
                bits.append(f"at {st.hold.min_temp_f} F or above")
            if st.hold.max_temp_f is not None:
                bits.append(f"at {st.hold.max_temp_f} F or below")
            if st.hold.max_minutes is not None:
                bits.append(f"max {st.hold.max_minutes} min")
            hold = "Hold " + ", ".join(bits)
        steps.append(
            SheetStep(
                number=idx,
                title=st.title,
                instructions=st.instructions,
                minutes=(
                    f"{inst.duration} min"
                    + (
                        f" ({inst.active} hands-on)"
                        if inst and inst.active != inst.duration
                        else ""
                    )
                    if inst
                    else ""
                ),
                when=when,
                equipment=", ".join(
                    (f"{e.count} x " if e.count > 1 else "") + e.type.replace("_", " ")
                    for e in st.equipment
                ),
                batch_note=batch_note,
                hold=hold,
            )
        )
    if n > 1:
        statement = f"Make {n} batches of ~{u.format_amount(pr.batch.servings_per_batch)} servings"
    else:
        statement = "Make 1 batch"
    allergens = sorted(
        {
            a
            for ln in pr.lines
            for a in (
                plan.ingredients[ln.ingredient_id].allergens
                if ln.ingredient_id in plan.ingredients
                else []
            )
        }
    )
    return Sheet(
        title=pr.recipe.name,
        meal=meal.title,
        serve=plan.clock.describe(meal.serve_minute),
        people=pr.people,
        servings=u.format_amount(pr.servings),
        portion_basis=pr.recipe.portion_basis,
        diets=", ".join(pr.diets),
        batch_statement=statement,
        batch_reasons="; ".join(pr.batch.reasons),
        ingredients=tuple(_ingredient_row(plan, pr, ln) for ln in pr.lines),
        steps=tuple(steps),
        scaling_notes=pr.recipe.scaling_notes,
        description=pr.recipe.description,
        source=pr.recipe.source,
        tags=tuple(pr.recipe.tags),
        allergens=tuple(allergens),
        equipment=tuple(e.replace("_", " ") for e in pr.recipe.equipment_required),
    )


def build_recipe_sheets(plan: Plan) -> RecipeSheetsData:
    return RecipeSheetsData([_sheet(plan, pr) for pr in plan.planned_recipes()])


class RecipeSheetsGenerator:
    id = "recipes"
    title = "Recipe sheets"
    description = "Every recipe scaled to its head count, with batch splits spelled out."
    order = 30
    template_dir: Path | None = None

    def generate(self, plan: Plan, options: base.GenOptions) -> base.GeneratorResult:
        return base.GeneratorResult(build_recipe_sheets(plan), "recipe_sheets.html")


base.register(RecipeSheetsGenerator())
