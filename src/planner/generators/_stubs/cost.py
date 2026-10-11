"""Cost estimate (stub, not registered).

Multiply each shopping-list line by a price. Suggested: store prices in
`Ingredient.extras['price_per_pack']` (keyed by pack label) and read
`planner.generators.shopping.build_shopping(plan)` for the pack counts, so cost follows
exactly what is bought.
"""

from __future__ import annotations

from pathlib import Path

from planner.core.plan import Plan
from planner.generators import base


class CostStub:
    id = "cost"
    title = "Cost estimate"
    description = "Cost estimate (not implemented yet)."
    order = 100
    template_dir: Path | None = None

    def generate(self, plan: Plan, options: base.GenOptions) -> base.GeneratorResult:
        raise NotImplementedError("stub: see the module docstring")


# base.register(CostStub())  # uncomment when implemented and moved to planner/generators/
