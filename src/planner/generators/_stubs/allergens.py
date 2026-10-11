"""Allergen matrix (stub, not registered).

Rows are dishes, columns are allergens and diet flags. Read `ingredient.allergens` and
`ingredient.diet_flags` for each `PlannedRecipe.lines` entry in
`plan.planned_recipes()`. Variants already appear as separate planned recipes.
"""

from __future__ import annotations

from pathlib import Path

from planner.core.plan import Plan
from planner.generators import base


class AllergensStub:
    id = "allergens"
    title = "Allergen matrix"
    description = "Allergen matrix (not implemented yet)."
    order = 100
    template_dir: Path | None = None

    def generate(self, plan: Plan, options: base.GenOptions) -> base.GeneratorResult:
        raise NotImplementedError("stub: see the module docstring")


# base.register(AllergensStub())  # uncomment when implemented and moved to planner/generators/
