"""Expand a scaled recipe into schedulable step instances (a dependency graph).

Steps that run per batch are copied once per batch (``key#b1`` ... ``key#bN``).
Shared steps appear once and wait for every batch copy they depend on.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from planner.core.models import Hold, Recipe, Step
from planner.core.scaling import scale_minutes


@dataclass(frozen=True)
class Demand:
    """One kind of equipment a step occupies for its whole duration."""

    type: str
    count: int
    min_capacity: Fraction  # 0 when the step has no capacity requirement


@dataclass(frozen=True)
class StepInstance:
    key: str
    meal_index: int
    position: int  # index of the recipe within the meal
    recipe_id: str
    recipe_name: str
    step_id: str
    title: str
    instructions: str
    batch: int | None  # 1-based, None if the recipe is not split
    n_batches: int
    duration: int
    active: int
    cooks: int
    demands: tuple[Demand, ...]
    deps: tuple[str, ...]
    serve_minute: int
    meal_day: int
    earliest_offset: int | None
    latest_offset: int
    day_offset: int | None
    hold: Hold | None
    cooked: bool

    @property
    def sort_key(self) -> tuple[int, int, str, str, int]:
        return (self.meal_index, self.position, self.recipe_id, self.step_id, self.batch or 0)


class GraphError(ValueError):
    pass


def _key(prefix: str, step_id: str, batch: int | None) -> str:
    return f"{prefix}:{step_id}" + (f"#b{batch}" if batch is not None else "")


def _cooks(step: Step, active: int) -> int:
    if step.cooks is not None:
        return step.cooks
    return 1 if active > 0 else 0


def expand_recipe(
    recipe: Recipe,
    *,
    servings: Fraction,
    batch_counts: Mapping[str, int],
    meal_index: int,
    position: int,
    serve_minute: int,
    meal_day: int,
) -> list[StepInstance]:
    """Build step instances for one planned recipe of ``servings`` servings.

    ``batch_counts`` maps each per-batch step id to its number of copies (see
    ``BatchPlan.step_batches``); other steps appear once.
    """
    prefix = f"m{meal_index}p{position}:{recipe.id}"
    by_id = {s.id: s for s in recipe.steps}

    def n_of(step: Step) -> int:
        return batch_counts.get(step.id, 1) if step.is_per_batch else 1

    out: list[StepInstance] = []
    for step in recipe.steps:
        n = n_of(step)
        scale = (servings / n) / recipe.base_servings
        duration = scale_minutes(step.duration_min, step.time_scaling, scale)
        active = min(duration, scale_minutes(step.active, step.time_scaling, scale))
        demands = tuple(
            Demand(
                e.type,
                e.count,
                (e.capacity_hint * scale) if e.capacity_hint is not None else Fraction(0),
            )
            for e in step.equipment
        )
        copies: list[int | None] = list(range(1, n + 1)) if n > 1 else [None]
        for batch in copies:
            deps: list[str] = []
            for d in step.depends_on:
                n_d = n_of(by_id[d])
                if n_d == 1:
                    deps.append(_key(prefix, d, None))
                elif batch is not None and n_d == n:
                    deps.append(_key(prefix, d, batch))
                else:
                    deps.extend(_key(prefix, d, b) for b in range(1, n_d + 1))
            if batch is not None and batch > 1 and not step.can_parallelize_batches:
                deps.append(_key(prefix, step.id, batch - 1))
            out.append(
                StepInstance(
                    key=_key(prefix, step.id, batch),
                    meal_index=meal_index,
                    position=position,
                    recipe_id=recipe.id,
                    recipe_name=recipe.name,
                    step_id=step.id,
                    title=step.title,
                    instructions=step.instructions,
                    batch=batch,
                    n_batches=n,
                    duration=duration,
                    active=active,
                    cooks=_cooks(step, active),
                    demands=demands,
                    deps=tuple(sorted(set(deps))),
                    serve_minute=serve_minute,
                    meal_day=meal_day,
                    earliest_offset=step.earliest_offset,
                    latest_offset=step.latest_offset,
                    day_offset=step.day_offset,
                    hold=step.hold,
                    cooked=step.cooked,
                )
            )
    return out


def validate_graph(instances: list[StepInstance]) -> None:
    """Raise ``GraphError`` on dangling dependencies or cycles."""
    keys = {i.key for i in instances}
    if len(keys) != len(instances):
        raise GraphError("duplicate step keys")
    indeg = {i.key: len(i.deps) for i in instances}
    children: dict[str, list[str]] = {k: [] for k in keys}
    for i in instances:
        for d in i.deps:
            if d not in keys:
                raise GraphError(f"{i.key} depends on missing {d}")
            children[d].append(i.key)
    ready = [k for k, n in indeg.items() if n == 0]
    seen = 0
    while ready:
        cur = ready.pop()
        seen += 1
        for c in children[cur]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
    if seen != len(instances):
        raise GraphError("dependency cycle")
