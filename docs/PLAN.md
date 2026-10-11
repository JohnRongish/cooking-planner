# Build Plan

Status: DRAFT for approval. No code is written until this is approved.

Each milestone is independently testable, ends green on `ruff`, `mypy`, and
`pytest`, and is committed in small steps. `CHANGELOG.md` gets an entry per
milestone. Decisions made along the way go in `docs/DECISIONS.md`.

## M0. Scaffolding
- `pyproject.toml` (src layout, deps, ruff, mypy strict on `planner.core`,
  pytest + coverage config with `core` gate at 90%), `.gitignore`, `.dockerignore`.
- Empty package skeleton per SPEC section 2, `CHANGELOG.md`, `docs/DECISIONS.md`
  (seeded from SPEC section 5), minimal `ci.yml` (ruff, mypy, pytest).
- **Done when:** `pytest`, `ruff check`, `mypy` all pass on an empty skeleton and CI file is valid.

## M1. Units, scaling, batch splitting (pure core)
- `core/units.py`: unit table with exact Fractions, parsing ("1 1/2 cup", "3/4 tsp"),
  conversion within and across families (density), mismatch warnings, friendly display.
- `core/scaling.py`: factor math, linear/fixed/stepped, trim yield, batch count and
  equal-batch sizing against `max_batch_servings` and equipment capacity.
- Tests: table-driven cases; property-style tests (hypothesis) for conversion round
  trips, scaling linearity, and "1/3 cup x 37" exactness; batch edge cases (8 vs 120).
- **Done when:** core coverage for these modules >= 95%, no floats in amount paths.

## M2. Models, storage, import/export
- `core/models.py`: pydantic models for Ingredient, Recipe, Step, KitchenProfile,
  Event, Meal (with `schema_version`, `extras`, `variants`).
- `storage/`: SQLModel tables, repositories, Alembic initial migration, session setup.
- Import/export of YAML and JSON (single bundle and per-entity files), `schema_version`
  checks, upsert vs `--replace`.
- Tests: model validation, repository CRUD on tmp SQLite, YAML/JSON round trip
  (export -> wipe -> import -> equal), migration applies on a fresh DB.
- **Done when:** round-trip test passes for a fixture set covering every field type.

## M3. Step graph and scheduler
- `core/graph.py`: expand scaled/batched recipes into a step DAG (batch copies per D7,
  cycle and missing-dependency detection).
- `core/scheduler.py`: deterministic backward greedy list scheduler on a 5-minute grid,
  equipment and `max_cooks` constraints, windows/day offsets, working hours, conflict
  warnings (never fails), food-safety hints with configurable thresholds.
- `core/plan.py`: Event -> Plan (resolve, diet splits, scale, batch, graph, schedule, warnings).
- `docs/SCHEDULER.md`: algorithm, tie-breaks, limitations.
- Tests: hand-built small cases, oversubscription -> visible warning, make-ahead windows,
  every step before serve time, determinism (run twice, compare), 120 vs 8 servings batches.
- **Done when:** core overall coverage >= 90%.

## M4. Generators
- `generators/base.py` (protocol, registry, auto-discovery), `shopping.py` (merge, pantry,
  pack rounding, sections, CSV), `timeline.py` (per-day + per-station), `recipe_sheets.py`,
  each with its own template, plus `_stubs/` (cost, allergens, equipment, pack_weight).
- `docs/ADDING_A_GENERATOR.md`; a throwaway example generator in the tests proves the
  registry needs no edits elsewhere.
- Tests: hand-checked shopping lines (>= 3), pantry subtraction, CSV output, timeline
  snapshots, registry discovery.
- **Done when:** all three generators run on a fixture plan with no errors.

## M5. Web UI and print CSS
- FastAPI app, Jinja2 layout, HTMX (vendored), `/healthz`, optional password login.
- Pages: recipes (list/filter/search/edit/duplicate), ingredients, kitchens, events
  (builder + live validation), plan page (tabs from registry, print view, PDF/CSV download),
  import/export.
- Print CSS: Letter default / A4 via env, page breaks per recipe/day, checkboxes, footer
  disclaimer. WeasyPrint PDF route.
- Tests: FastAPI TestClient for every page and download, auth on/off, generator tab appears
  automatically when a generator is registered, PDF returns `%PDF`.
- **Done when:** all routes covered by tests and a manual screenshot pass of print views looks right.

## M6. Seed data and demo event
- ~10 recipes (bulk + backpacking + batch-split), ingredient catalog with densities and
  packs, 3 kitchen profiles, 120-person 7-meal demo event as YAML under `src/planner/seed/`.
- `planner seed`, `planner plan <event.yaml>`, UI seed button.
- Acceptance tests: demo event on Camp kitchen produces all outputs, no unhandled errors,
  no silent oversubscription, deterministic; batch recipe = 3 batches at 120, 1 at 8;
  same recipe under Backpacking for 6 people; export -> wipe -> import -> identical plan.
- **Done when:** every acceptance criterion in SPEC 10 that is not Docker/CI passes.

## M7. Docker, CI, docs
- Multi-stage Dockerfile (non-root, `/data` volume, env config, auto-migrate, HEALTHCHECK,
  WeasyPrint libs), entrypoint script.
- `ci.yml` (ruff, mypy, pytest + coverage gate), `docker.yml` (gated on CI, buildx, GHA cache,
  GHCR tags latest/sha/semver, owner/repo from context, container smoke test: start on empty
  `/data`, hit `/healthz`, fetch a PDF). arm64 added if build time is acceptable.
- README: quick start, compose, TrueNAS SCALE steps, GHCR visibility/token, update, backup.
- **Done when:** `docker build` and the container smoke test pass locally if Docker is
  available in this environment, otherwise verified by CI.

## Risks / notes
- Docker may be unavailable in this sandbox; if so, M7 is verified through GitHub Actions
  and I will say so plainly rather than claim local verification.
- WeasyPrint needs system libs (Pango); I will check they are installable here for tests,
  else PDF tests are skipped locally and run in CI/Docker.
- The "Publish to GHCR on push to main" criterion can only be confirmed once the branch is
  merged to `main` (you decide when; I will not open a PR unless asked).
