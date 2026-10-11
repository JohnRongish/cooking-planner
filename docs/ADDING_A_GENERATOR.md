# Adding a generator

An output (cost estimate, allergen matrix, equipment list, pack weight...) is **one
module in `src/planner/generators/`** plus a template. No route, menu, or core edits.

## 1. The contract

```python
class Generator(Protocol):
    id: str                    # url slug, unique ("allergens")
    title: str                 # tab title
    description: str
    order: int                 # tab order; built-ins use 10, 20, 30
    template_dir: Path | None  # None = use generators/templates/

    def generate(self, plan: Plan, options: GenOptions) -> GeneratorResult: ...

@dataclass
class GeneratorResult:
    data: Any                  # whatever the template needs
    template: str              # template file name
    csv: Callable[[], str] | None = None   # optional CSV download
    csv_filename: str = "export.csv"
```

A generator reads a `planner.core.plan.Plan` and nothing else. It never touches the
database or the web layer. `Plan` exposes the event, kitchen, catalog, every
`PlannedRecipe` (scaled lines, batch plan), and the schedule.

## 2. Write the module

```python
# src/planner/generators/headcount.py
from dataclasses import dataclass
from pathlib import Path
from planner.core.plan import Plan
from planner.generators import base

@dataclass
class HeadcountData:
    rows: list[tuple[str, int]]

class HeadcountGenerator:
    id = "headcount"
    title = "Head counts"
    description = "People per meal."
    order = 40
    template_dir: Path | None = None

    def generate(self, plan: Plan, options: base.GenOptions) -> base.GeneratorResult:
        data = HeadcountData([(m.title, m.meal.headcount) for m in plan.meals])
        return base.GeneratorResult(data, "headcount.html")

base.register(HeadcountGenerator())      # <- the whole registration
```

## 3. Write the template

`src/planner/generators/templates/headcount.html` renders a **fragment** with `data`
and `plan` in scope. Use the shared print classes: `.gen`, `.avoid-break`,
`.page-break-before`, `.box` (checkbox), `.warn`. Filters: `amount`, `qty`.

```html
<section class="gen"><h2>Head counts</h2>
<table>{% for name, n in data.rows %}<tr><td>{{ name }}</td><td>{{ n }}</td></tr>{% endfor %}</table>
</section>
```

A generator may instead ship its own folder: set `template_dir = Path(__file__).parent / "templates"`.

## 4. That's it

`generators.base.discover()` imports every public module in the package at startup
(names starting with `_` are skipped), so the module registers itself. The web UI
builds its tabs, print views, PDF and CSV links from the registry. Duplicate ids raise
`DuplicateGenerator`.

`tests/generators/test_registry.py` proves this with a throwaway generator that lives
only under `tests/`: registering it makes it appear in the web UI and render, with no
edit to any file outside `generators/` and the test.

## Shopping list rounding (reference)

For each ingredient the shopping generator converts every need to the unit family of
its first purchase pack (through `density_g_per_ml` when volume meets weight; no
density means a separate line and a warning), applies `trim_yield`, subtracts the
pantry, then evaluates combinations of up to four pack sizes. The score is
`leftover / need + packs / 20`; ties go to fewer packs, then larger packs. The bound of
the search keeps it instant for realistic catalogs.
