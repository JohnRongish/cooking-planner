"""Equipment list (stub, not registered).

List what the plan needs: the maximum concurrent use of each equipment type across
`plan.schedule.steps` (see `step.instance.demands`), compared with
`plan.kitchen.equipment_inventory`.
"""

from __future__ import annotations

from pathlib import Path

from planner.core.plan import Plan
from planner.generators import base


class EquipmentStub:
    id = "equipment"
    title = "Equipment list"
    description = "Equipment list (not implemented yet)."
    order = 100
    template_dir: Path | None = None

    def generate(self, plan: Plan, options: base.GenOptions) -> base.GeneratorResult:
        raise NotImplementedError("stub: see the module docstring")


# base.register(EquipmentStub())  # uncomment when implemented and moved to planner/generators/
