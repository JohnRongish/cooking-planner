# Changelog

All notable changes. Format: Keep a Changelog; versions follow semver once tagged.

## [Unreleased]
### Added
- M0: project scaffolding (pyproject, ruff, mypy, pytest, CI workflow).
- M1: exact units and conversion (US customary + metric, density), scaling modes, batch splitting.
- M3: step graph, deterministic backward scheduler with conflict warnings, plan builder, food-safety hints.
- M2: pydantic models, SQLite storage with Alembic, YAML/JSON import and export.
- M4: generator registry with auto-discovery, shopping list (pack rounding, pantry, CSV), timeline (by day and station), recipe sheets, stubs, docs/ADDING_A_GENERATOR.md.
- M6: seed data (55 ingredients, 13 recipes, 3 kitchens, 2 demo events), `planner` CLI (export/import/seed/migrate/plan/serve), print CSS, acceptance tests.
- Per-step batch counts, cooks clamped to the kitchen's max_cooks.
