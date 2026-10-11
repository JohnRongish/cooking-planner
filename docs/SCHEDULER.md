# Scheduler (v1)

`planner.core.scheduler.schedule()` places every step of every meal in one
timeline. It is a **greedy, resource-constrained list scheduler that works
backward from serve time**. It is deterministic: same input, same output.

## Inputs
* `StepInstance`s from `core/graph.py` (one per step, copied per batch for
  per-batch steps), each already scaled: duration, active minutes, equipment
  demands (type, count, minimum capacity), dependencies, serve minute, window.
* The `KitchenProfile` (equipment units and their capacities, `max_cooks`,
  working hours) and `PlanSettings` (5-minute grid, 72 h default lookback).

Time is integer minutes since 00:00 of the event's first day (`Clock` formats it).

## Algorithm
1. Each step gets a *latest end*: `serve - latest_offset`. Steps nobody depends
   on are *ready*; the rest wait until all their dependents are placed.
2. Pop the ready step with the **latest end** (ties: longest chain of work leading
   up to it, then meal order, recipe position, recipe id, step id, batch number).
   This mirrors forward list scheduling, run on the reversed graph.
3. Try the latest start on the 5-minute grid with `start + duration <= latest end`.
   Walk earlier until all of these hold:
   * **Window**: `end >= serve - earliest_offset` (or the lookback if unset).
   * **Day**: with `day_offset`, start and end are on `meal day + offset`.
   * **Working hours**: a step with hands-on time must *start* and *end* inside the
     kitchen's working hours (default 06:00-22:00); it may span the night in
     between (an overnight braise). Fully passive steps ignore working hours.
     When a candidate breaks the rule the scheduler jumps to the latest legal start.
   * **Equipment**: for each demanded type, the concurrent demand fits the units
     available. Capacity-aware: a step needing a 30 L pot only counts pots that big
     (a Hall-style check per capacity threshold, exact for nested requirements).
   * **Cooks**: during the first `active_min` minutes the step uses `cooks`
     (default 1) of `max_cooks`.
4. Book the slot, then lower each prerequisite's latest end to this step's start.
5. If **no legal slot exists** the step is placed at its preferred slot (nudged into
   working hours) and flagged. It still occupies the resources it uses, so the
   oversubscription is visible and later steps schedule around reality.
6. After placement, a pass finds every time range where a resource is
   oversubscribed and emits a `conflict` warning, for example
   *"Saturday dinner needs 5 burners from Sat 4:00 PM-5:00 PM but only 4 exist (...)"*.
   Steps involved carry the same flag. Steps that could not be placed within their
   window get their own warning. Nothing raises for an impossible plan.
7. Equipment units are named afterwards (best fit, smallest unit that fits,
   deterministic): `Burner 3`, `Pot 1 (40)`. This feeds the per-station view.

## Batches
A recipe that needs more than `max_batch_servings`, or whose per-batch equipment
`capacity_hint` exceeds the biggest unit in the kitchen, is split into N equal
batches (`core/scaling.plan_batches`). Steps that use sized equipment (or set
`per_batch: true`) are copied N times. Shared steps (chopping, serving) appear
once and wait for every copy they depend on. Batch copies run in parallel only
when the kitchen has the equipment; the scheduler simply cannot overlap them
otherwise. `can_parallelize_batches: false` chains the copies in order.

## Food-safety hints
After scheduling, `plan.safety_warnings` flags hold steps with temperatures on
the wrong side of the configurable thresholds (default hot >= 135 F, cold <= 41 F),
holds longer than allowed, and cooked food (`cooked: true`) that waits longer than
the out-of-temperature limit (default 240 min) before the next step or serving.
These are hints, not guarantees; the printed output says so.

## Determinism
All ordering uses explicit total-order keys; there is no randomness, wall-clock
use, or reliance on dict/set iteration order for decisions.

## Limitations
* Greedy: it does not search for the global optimum and can strand slack.
* A step's hands-on time is modelled as its **first** `active_min` minutes.
* Cooks are fungible; there is no skill matching or walking time.
* Equipment is counted per unit; sheet-pan or pot *packing* inside one unit is not
  modelled beyond `capacity_hint` for batch sizing.
* Dependencies are within one recipe. There are no cross-recipe dependencies.
* Backward scheduling is just-in-time, so food-safety gaps appear mainly when
  resources force a step earlier; the safety pass reports them.
* A step cannot start more than the lookback (72 h by default) before serving
  unless `earliest_offset` says otherwise.
