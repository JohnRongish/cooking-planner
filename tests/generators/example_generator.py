"""A throwaway generator that lives entirely under tests/.

It proves the contract in docs/ADDING_A_GENERATOR.md: dropping a module like this next
to the built-ins (or anywhere that gets imported) is all it takes to get a new tab.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from planner.core.plan import Plan
from planner.generators import base


@dataclass
class HeadcountData:
    rows: list[tuple[str, int]]
    total: int


class HeadcountGenerator:
    id = "headcount"
    title = "Head counts"
    description = "People per meal (test example)."
    order = 99
    template_dir: Path | None = Path(__file__).parent / "templates"

    def generate(self, plan: Plan, options: base.GenOptions) -> base.GeneratorResult:
        rows = [(m.title, m.meal.headcount) for m in plan.meals]
        data = HeadcountData(rows, sum(n for _, n in rows))
        return base.GeneratorResult(
            data,
            "headcount.html",
            csv=lambda: "meal,people\n" + "".join(f"{a},{b}\n" for a, b in rows),
            csv_filename="headcount.csv",
        )


def register_example() -> HeadcountGenerator:
    gen = HeadcountGenerator()
    base.register(gen)
    return gen
