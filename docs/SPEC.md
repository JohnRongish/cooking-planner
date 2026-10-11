# Event Kitchen Planner: Specification (draft for approval)

Status: DRAFT v0.1. Awaiting user approval before PLAN.md or any code.

## 1. Purpose

A self-hosted web app for a head cook. They pick meals from a shared recipe
repository, set a head count per meal, and get three printable outputs:

1. **Shopping list**: merged across all meals, scaled, rounded up to
   purchasable pack sizes, grouped by store section, CSV export.
2. **Timeline**: prep/start/add times interleaved across all meals, working
   backward from each serve time, respecting equipment and cooks. Per-day
   chronological view plus per-station view.
3. **Recipe sheets**: each recipe scaled to head count, batch splits spelled out.

Planning only. Everything is printed before the event. Print-styled HTML is the
primary output; PDF is a convenience.

## 2. Architecture

```
src/planner/
  core/        pure Python, no DB, no web. mypy --strict. >=90% coverage.
    units.py models.py scaling.py graph.py scheduler.py plan.py
  generators/  one module per output; each registers itself
    base.py shopping.py timeline.py recipe_sheets.py _stubs/
  storage/     SQLModel tables, repositories, YAML/JSON import/export, Alembic
  web/         FastAPI routes, Jinja2 templates, static, print CSS
  cli.py       planner export | import | plan <event.yaml> | serve
tests/ core/ generators/ web/ fixtures/
docs/  SPEC.md PLAN.md DECISIONS.md SCHEDULER.md ADDING_A_GENERATOR.md
```

Pipeline: `Event -> resolve -> scale -> batch split -> expand step graph ->
schedule -> Plan -> generators -> HTML/PDF/CSV`.

`core` imports nothing from `storage`, `web`, or `generators`. `Plan` is the
single resolved object every generator reads. Generators never touch the DB.

### Generator contract
```python
class Generator(Protocol):
    id: str            # url slug, e.g. "shopping"
    title: str
    def generate(self, plan: Plan, options: GenOptions) -> GeneratorResult: ...

@dataclass
class GeneratorResult:
    data: dict | dataclass     # what the template renders
    template: str              # template name (generator ships its own)
    csv: Callable[[], str] | None = None
```
Registration: each module in `generators/` calls `register(MyGenerator())` at
import. `generators/__init__` imports every non-underscore module via
`pkgutil.iter_modules`, so dropping in a file is enough. The web UI iterates the
registry for tabs, print views, and downloads. Templates are looked up in a
`templates/` folder next to each generator, so a new generator touches only
`generators/` (and its test). Proven by a throwaway generator in the tests.

## 3. Stack
Python 3.12+, FastAPI, SQLModel/SQLAlchemy, SQLite, Alembic, Jinja2, HTMX
(vendored single JS file, no Node), WeasyPrint for PDF, pytest, ruff, mypy.
Quantities use `fractions.Fraction`. No floats for amounts, ever.
Density, trim_yield, temperatures stored as `Fraction`/`Decimal` too (YAML as
strings or numbers, parsed via `Fraction(str(x))`).

## 4. Data model
Exactly as in the build prompt (Ingredient, Recipe, Step, KitchenProfile, Event,
Meal), implemented as frozen pydantic v2 models in `core/models.py`; SQLModel
tables in `storage` store them as normalized rows with JSON columns for nested
lists (steps, packs, equipment) and `extras`. Every exported file carries
`schema_version` (starts at 1). `extras: dict` on Ingredient and Recipe (and
Event, KitchenProfile for symmetry).

## 5. Decisions on ambiguities (also logged in DECISIONS.md)

| # | Topic | Decision |
|---|-------|----------|
| D1 | Python version | Target 3.12+. Docker uses 3.12-slim. (Sandbox has 3.13; both tested in CI matrix? No: CI uses 3.12 only, to keep it simple.) |
| D2 | Pydantic | Core models are pydantic v2 (validation + YAML round trip). Not dataclasses. |
| D3 | Step IDs / refs | Step ids are unique within a recipe; `depends_on` is within-recipe only. Cross-recipe deps are not supported in v1. |
| D4 | Anchors | Every step is scheduled relative to its **meal's serve time**. `earliest_offset`/`latest_offset` (minutes before serve end of step) bound the window; `day_offset` forces the step onto day (serve_day + offset, offset <= 0) with time chosen by the scheduler within that day. |
| D5 | Time scaling | `duration = base * f(scale)` where scale = scaled_servings_per_batch / base_servings; sqrt -> sqrt(scale) (rounded up to whole minute, using integer isqrt on a Fraction ceiling so it stays deterministic), linear -> scale, none -> 1. Applies to `duration_min` and `active_min`. Minimum 1 minute rounding granularity: schedule on a 5-minute grid. |
| D6 | Batching | `n_batches = ceil(servings / max_batch_servings)`, also bumped up until each batch fits the largest suitable equipment capacity in the profile (capacity_hint vs inventory capacity, units normalized to litres). Batches are equal size. Only steps flagged as per-batch are copied; see D7. |
| D7 | Which steps get copied | Steps that use equipment with a `capacity_hint` or are marked `can_parallelize_batches` are per-batch. Others (e.g. "chop onions", "serve") are shared. Step copies get ids `<step>#b1..bN`; shared steps depending on per-batch steps wait for all copies. Additional per-step flag `per_batch: bool | None` overrides inference. |
| D8 | Parallel batches | Batch copies compete for equipment like any step. If the profile has two big pots, two batches run in parallel; otherwise they serialize. Nothing special. |
| D9 | Scheduling grid | 5-minute grid, deterministic. |
| D10 | Scheduler | Greedy resource-constrained list scheduler working backward from serve time (details in SCHEDULER.md): order by (latest finish desc, critical path length desc, meal order, recipe id, step id), place each step at the latest slot that fits resources and window, slide earlier on conflict. If no slot exists inside its window, place it at its preferred time anyway, mark it conflicted, and emit a prominent warning. |
| D11 | Resources | Constraints: each equipment type's count (burners, ovens, pots, pans, prep tables...) and `max_cooks`. A step consumes 1 cook while it is **active** (`active_min`), but holds equipment for its full `duration_min`. Capacity is checked as count of units, not a bin-packing of sheet pans. Oven "sheet-pan capacity" is a per-oven attribute used for batch splitting only (pans per oven), not for placement. |
| D12 | Day boundaries | No working at night: kitchen working hours default 06:00 to 22:00, configurable in the profile (`extras` or a first-class `work_hours` field, to be decided in PLAN). Steps are not placed outside it unless unavoidable (then warned). Passive steps (rising, overnight chilling) may span the gap. |
| D13 | Diet splits | `diet_splits` maps a diet label to a count. Each recipe may declare `variants: {diet_label: recipe_id}` (a substitute recipe) . For a split, that many servings come from the variant recipe and the base recipe is scaled to headcount minus the sum of split counts (splits assumed disjoint, validated; if overlapping, warn and treat as disjoint). If a recipe has no variant for a split present in the meal, a warning is raised and the split people are listed as "unserved" on the shopping list header and recipe sheet. Recipes get `variants` and `diets` fields (small addition to the prompt's model). |
| D14 | Shopping math | See section 6. Greedy documented in code and docs. |
| D15 | Units | Volume: tsp, tbsp, fl oz, cup, pt, qt, gal, ml, l. Mass: oz, lb, g, kg. Count: each, pinch, plus ingredient-specific named count units (e.g. clove, can) where the pack list defines them. Internal canonical units: ml, g, each. US units use exact US customary definitions (1 cup = 236.588236 ml: stored as the exact fraction 473176473/2000000 per US pint... defined exactly in `units.py`). Round trip tests use these exact fractions. |
| D16 | Unit mismatch | Volume<->mass requires `density_g_per_ml`; missing density raises a visible warning and the two quantities are listed as separate lines. Count<->volume/mass is never converted (warn). |
| D17 | Display | Quantities display as friendly fractions (1/4, 1/3, 1/2, 2/3, 3/4, 1/8) for cooking units and as decimals (1 decimal place, rounded **up** for purchase) for weights above 1 lb / 500 g. Recipe sheets pick a human unit (e.g. 3 qt not 2838 ml). Stored value is always exact. |
| D18 | Stepped scaling | `stepped` carries `step_size` (default 1, e.g. whole eggs, cans). Scaled quantity rounds **up** to a multiple of `step_size`, per batch for per-batch recipes. |
| D19 | Fixed scaling | `fixed` ingredients do not scale with headcount but are multiplied per batch (each batch gets its own bay leaf). |
| D20 | Trim yield | Purchase quantity = recipe quantity / trim_yield. "Needed in recipe" and "to purchase" are both shown. |
| D21 | Pantry | `pantry_on_hand` is subtracted from the **purchase** quantity after unit conversion, floor at zero. |
| D22 | Rounding to packs | Greedy: for each ingredient pick the pack combo covering the need with minimum leftover, ties broken by fewer packs, then larger pack first. Exact search over at most 3 pack sizes (bounded enumeration) instead of pure greedy, since that is trivially cheap and avoids bad answers; documented. Ingredients with no packs are shown as exact quantity with a "no pack data" note. |
| D23 | Events spanning days | `start_date` + per-meal `day` index (0-based). Prep may be on day -1 (before first meal) via `day_offset`. Timeline starts at the earliest placed step. |
| D24 | Kitchen profile warnings | A recipe tag `backpacking-only`/`requires: [tag]` mismatch with the profile's `supports_tags` is a non-blocking validation warning in the event builder and in the plan. |
| D25 | Food-safety | Configurable thresholds (`hot_hold_f` 135, `cold_hold_f` 41, `out_of_temp_hours` 4). Warns when a `hold` step's `max_minutes` exceeds the limit, or the gap between a cooked item's finish and the serve time exceeds the limit without a hold/cold step. Footer: "Hints only; not a guarantee of food safety." |
| D26 | Determinism | No dict/set iteration order dependence; all sorts have explicit total-order keys; no wall-clock or random in core. |
| D27 | Persistence | SQLite via SQLModel; Alembic migrations run at app start (and `planner migrate`). Tests use in-memory/tmp SQLite. |
| D28 | Auth | If `PLANNER_PASSWORD` set: single shared password via HTTP session cookie login form (signed with a key derived from the password). `/healthz` is always open. No accounts. |
| D29 | PDF | WeasyPrint renders the same print HTML. Page size from `PLANNER_PAGE_SIZE` (Letter default, A4) via CSS `@page`. PDF is verified inside the built image in CI. |
| D30 | Editing UI | Plain forms plus HTMX partials for add/remove rows (ingredients, steps, equipment). Server round-trips; no client state. |
| D31 | Import/export | One YAML (or JSON) file per entity set: `ingredients.yaml`, `recipes.yaml`, `kitchens.yaml`, `events.yaml`, or a single bundle. `planner export <dir>` and `planner import <dir|file>` (import upserts by id; `--replace` wipes first). The web UI offers the same. Ids are stable slugs. |
| D32 | Equipment types | Free strings normalized to lowercase slugs (`burner`, `oven`, `pot`, `pan`, `prep_table`, `fridge`). Capacities are numbers in litres or sheet-pan counts and are only used for batch splitting. |
| D33 | arm64 | Added to the Docker build matrix only if CI time with QEMU stays reasonable (decide once measured); amd64 is mandatory. |
| D34 | Git branch / PRs | Work on `claude/wizardly-goodall-hk50q7`. No PR is opened unless you ask. |

## 6. Core behavior

### Scaling
`factor = headcount * portion_factor / base_servings` (exact Fraction).
Per ingredient by scaling mode (D18/D19), then trim yield for purchase (D20).
Keep `needed_in_recipe` and `to_purchase` as separate fields on every line.

### Shopping list
1. Gather scaled lines from all meals/recipes/batches/variants.
2. Normalize each to canonical unit family of that ingredient (mass if any
   mass quantity and density known, else the first family seen); mixed with no
   density => separate lines + warning (D16).
3. Sum per ingredient, apply trim yield, subtract pantry.
4. Round up to packs (D22). Per line: needed, pack choice and count, leftover.
5. Group by `store_section` (fixed section order, configurable list); print
   layout with checkboxes; CSV export.

### Timeline
Per-day chronological list (time, step, recipe, meal, cook-minutes, equipment)
and a per-station view (one lane per equipment unit: oven 1, burner 3...,
prep table). Conflicts banner at top of every printed page of the timeline.
Station assignment of a step to a specific unit is done after scheduling by
first-fit in a deterministic order.

### Recipe sheets
One page per recipe-per-meal (or per recipe with the meal list), scaled
ingredients with friendly units, batch statement ("Make 3 batches of ~40
servings"), steps with batch notes, scaling notes, allergens summary, and the
planned time slots from the timeline.

## 7. Web UI (v1)
Recipes (list, tag filter, search, create/edit, duplicate, import/export),
Ingredients (catalog editor with packs and density), Kitchens (editor),
Events (builder with live validation, meals, splits, pantry), Plan page (tabs
from registry; print view and download PDF/CSV). Optional shared password.
Utilitarian styling; print CSS is the priority (page breaks per recipe/day,
checkboxes, running header/footer, footer disclaimer).

## 8. Seed data
~10 recipes: chili, breakfast burritos, pasta marinara + meatballs, sheet-pan
vegetables, cornbread, sandwich bar (no-cook), oatmeal, couscous with
dehydrated veg, PB tortilla wraps, and one dedicated batch-split recipe (a
big-pot soup/stew with `max_batch_servings` 50: 3 batches at 120, 1 at 8).
Ingredient catalog with real-ish densities and pack sizes, three kitchen
profiles (Backpacking 1 stove/1 pot, Camp kitchen 2 ovens/6 burners/large
pots, Home), and a demo event: 120 people, Fri dinner to Sun lunch, 7 meals.
Seeded on first start only if the DB is empty and `PLANNER_SEED=1` (default on
for the demo image? Default **off**; `planner seed` command and a button in UI).

## 9. Docker, CI, deployment
As specified in the prompt. Multi-stage `python:3.12-slim`, non-root user,
`VOLUME /data`, env vars `PLANNER_DATA_DIR`, `PLANNER_PASSWORD`,
`PLANNER_PAGE_SIZE`, `PORT`, `PLANNER_BASE_URL`; alembic upgrade at startup;
`HEALTHCHECK` on `/healthz`; Pango/Cairo libs for WeasyPrint. `ci.yml`
(ruff, mypy, pytest with core coverage gate) and `docker.yml` (needs CI to
pass; buildx + GHA cache; tags latest/short-sha/semver; owner/repo derived from
`github.repository`). README with quick start, compose, TrueNAS SCALE, GHCR
visibility/token notes, backup/update.

## 10. Acceptance criteria
As listed in the prompt section 11; each maps to a named test or CI step in
PLAN.md.

## 11. Non-goals (v1)
User accounts/permissions; offline/PWA; mobile-first UI; live on-site tracking;
cost/nutrition (stubs only); optimal scheduling (greedy only); grocery-store
integrations; recipe import from URLs; cross-recipe step dependencies;
bin-packing of sheet pans; unit-level (not count-level) equipment capacity
modelling beyond batch sizing; multi-user concurrency control; i18n; metric-
only mode (metric units are accepted and shown, but US units are the default
display system, with a `PLANNER_UNITS=metric` display option deferred).

## 12. Open questions for you
1. **Display units**: default US customary (cups, lb), with metric accepted on input. OK?
2. **Seeding**: demo data loaded by an explicit `planner seed` / UI button, not automatically. OK?
3. **Diet splits** (D13): substitute recipes via `variants` on the base recipe, disjoint counts. OK, or do you want a different model?
4. **Working hours** (D12): 06:00-22:00 default per kitchen profile. OK?
5. **arm64**: build only if CI time stays reasonable (D33). OK?
