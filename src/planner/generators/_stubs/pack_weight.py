"""Pack weight and calories (stub, not registered).

For backpacking: grams per person per day. Sum `PlannedRecipe.lines` in grams
(`planner.core.units.convert_to_family`), divide by people, and read calories from
`Ingredient.extras['kcal_per_100g']`.
"""

from __future__ import annotations

from pathlib import Path

from planner.core.plan import Plan
from planner.generators import base


class PackWeightStub:
    id = "pack_weight"
    title = "Pack weight and calories"
    description = "Pack weight and calories (not implemented yet)."
    order = 100
    template_dir: Path | None = None

    def generate(self, plan: Plan, options: base.GenOptions) -> base.GeneratorResult:
        raise NotImplementedError("stub: see the module docstring")


# base.register(PackWeightStub())  # uncomment when implemented and moved to planner/generators/
