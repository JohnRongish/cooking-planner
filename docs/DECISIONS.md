# Decisions

Decisions D1-D34 are in `docs/SPEC.md` section 5 (approved). Decisions made
while building are appended here with the milestone that introduced them.

| # | Milestone | Decision |
|---|-----------|----------|
| D35 | M2 | Storage tables keep a few scalar/indexed columns (id, name, tags text, ...) plus a `data` JSON column holding the full pydantic model. Export/import never depends on the DB layout, and new fields need no migration. |
| D36 | M1 | `capacity_hint` on a step's equipment means the capacity (same unit as the profile's `capacity` for that equipment type, litres for pots/pans, sheet pans for ovens) needed at `base_servings`; it scales linearly with servings per batch. |
| D37 | M3 | `earliest_offset` / `latest_offset` are minutes before serve time, measured at the **end** of the step: end must lie in `[serve - earliest_offset, serve - latest_offset]`. Defaults: `earliest_offset=None` (bounded only by the 72 h lookback), `latest_offset=0`. |
| D38 | M3 | A step's hands-on time is modelled as its first `active_min` minutes; cooks are only consumed during that span. Equipment is held for the full duration. A step with `active_min > 0` must *start* and *end* inside working hours (it may span the night between, e.g. an overnight braise); fully passive steps ignore working hours. |
| D39 | M3 | Equipment with capacities is checked with a Hall-style condition (for each capacity threshold, concurrent demands needing at least that capacity must not exceed the units that have it). Exact for nested capacity requirements. |
| D40 | M3 | New step field `cooked: bool` marks steps whose output is cooked food, used for the out-of-temperature-time safety hint. New step field `cooks: int | None` (default 1 when `active_min > 0`). |
| D41 | M4 | Pack rounding score = `leftover / need + packs / 20` (exact Fractions); ties go to fewer packs, then larger packs first. At most 4 pack sizes per ingredient are searched. |
| D42 | M4 | Generators carry their own templates; the registry exposes template directories so the web layer needs no edits when a generator is added. |
| D43 | M3 | `Step.per_batch` (optional bool) overrides batch-copy inference; `can_parallelize_batches=False` chains batch copies of that step in sequence. |
