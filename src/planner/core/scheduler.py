"""Deterministic backward, resource-constrained list scheduler. See docs/SCHEDULER.md."""

from __future__ import annotations

import heapq
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal

from planner.core.graph import StepInstance, validate_graph
from planner.core.models import KitchenProfile
from planner.core.settings import PlanSettings
from planner.core.timefmt import MIN_PER_DAY, Clock

COOK = "cook"
INF = None  # capacity of a unit with no stated capacity: fits anything


@dataclass(frozen=True)
class PlanWarning:
    level: Literal["error", "conflict", "warning", "info"]
    code: str
    message: str
    meal_index: int | None = None


@dataclass(frozen=True)
class ScheduledStep:
    instance: StepInstance
    start: int
    end: int
    conflicts: tuple[str, ...] = ()
    stations: tuple[str, ...] = ()

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflicts)


@dataclass
class Schedule:
    steps: list[ScheduledStep] = field(default_factory=list)
    warnings: list[PlanWarning] = field(default_factory=list)

    @property
    def conflicts(self) -> list[PlanWarning]:
        return [w for w in self.warnings if w.level == "conflict"]


@dataclass(frozen=True)
class _Booking:
    start: int
    end: int
    count: int
    min_cap: Fraction
    key: str


class _Resource:
    """Booked intervals for one equipment type (or the pool of cooks)."""

    def __init__(self, name: str, caps: list[Fraction | None]) -> None:
        self.name = name
        self.caps = caps
        self.bookings: list[_Booking] = []

    def avail(self, threshold: Fraction) -> int:
        return sum(1 for c in self.caps if c is None or c >= threshold)

    def _check_set(self, active: list[_Booking]) -> tuple[Fraction, int, int] | None:
        """Hall condition: first violated (threshold, needed, available) or None."""
        thresholds = sorted({b.min_cap for b in active} | {Fraction(0)})
        for t in thresholds:
            need = sum(b.count for b in active if b.min_cap >= t)
            have = self.avail(t)
            if need > have:
                return t, need, have
        return None

    def first_violation(
        self, start: int, end: int, count: int, min_cap: Fraction, extra: _Booking | None = None
    ) -> tuple[Fraction, int, int, int] | None:
        """Would booking [start, end) violate capacity? Returns (threshold, need, have, at)."""
        if end <= start or count <= 0:
            return None
        new = _Booking(start, end, count, min_cap, "")
        overlapping = [b for b in self.bookings if b.start < end and b.end > start]
        points = sorted({start} | {b.start for b in overlapping if start < b.start < end})
        for p in points:
            active = [b for b in overlapping if b.start <= p < b.end] + [new]
            v = self._check_set(active)
            if v is not None:
                return v[0], v[1], v[2], p
        return None

    def book(self, start: int, end: int, count: int, min_cap: Fraction, key: str) -> None:
        if end > start and count > 0:
            self.bookings.append(_Booking(start, end, count, min_cap, key))

    def oversubscribed(self) -> list[tuple[int, int, int, int, list[str]]]:
        """Segments (start, end, need, have, step keys) where bookings exceed capacity."""
        if not self.bookings:
            return []
        cuts = sorted({b.start for b in self.bookings} | {b.end for b in self.bookings})
        segs: list[tuple[int, int, int, int, list[str]]] = []
        for a, b in zip(cuts, cuts[1:], strict=False):
            active = [x for x in self.bookings if x.start <= a < x.end]
            if not active:
                continue
            v = self._check_set(active)
            if v is not None:
                keys = sorted({x.key for x in active})
                if (
                    segs
                    and segs[-1][1] == a
                    and segs[-1][2:4] == (v[1], v[2])
                    and (segs[-1][4] == keys)
                ):
                    s = segs[-1]
                    segs[-1] = (s[0], b, s[2], s[3], s[4])
                else:
                    segs.append((a, b, v[1], v[2], keys))
        return segs


def _floor(x: int, grid: int) -> int:
    return (x // grid) * grid


def _pretty(t: str) -> str:
    return t.replace("_", " ")


def _plural(t: str, n: int) -> str:
    name = _pretty(t)
    return name if n == 1 else (name + "s" if not name.endswith("s") else name)


def schedule(
    instances: Sequence[StepInstance],
    kitchen: KitchenProfile,
    settings: PlanSettings,
    clock: Clock,
    meal_labels: dict[int, str] | None = None,
) -> Schedule:
    """Place every instance. Never raises for impossible plans; it reports conflicts."""
    inst = list(instances)
    validate_graph(inst)
    labels = meal_labels or {}
    by_key = {i.key: i for i in inst}
    grid = settings.grid_min
    ws, we = kitchen.work_start_min, kitchen.work_end_min

    resources: dict[str, _Resource] = {}
    for t in sorted({d.type for i in inst for d in i.demands}):
        resources[t] = _Resource(t, list(kitchen.units_of(t)))
    cook_res = _Resource(COOK, [INF] * kitchen.max_cooks) if kitchen.max_cooks is not None else None

    dependents: dict[str, list[str]] = {i.key: [] for i in inst}
    for i in inst:
        for dep in i.deps:
            dependents[dep].append(i.key)

    # longest chain of work leading up to each step (critical path), memoised
    path_len: dict[str, int] = {}

    def plen(k: str) -> int:
        if k not in path_len:
            node = by_key[k]
            path_len[k] = node.duration + max((plen(dep) for dep in node.deps), default=0)
        return path_len[k]

    latest_end: dict[str, int] = {i.key: i.serve_minute - i.latest_offset for i in inst}
    remaining = {k: len(v) for k, v in dependents.items()}

    def prio(k: str) -> tuple[int, int, int, int, str, str, int]:
        i = by_key[k]
        return (
            -latest_end[k],
            -plen(k),
            i.meal_index,
            i.position,
            i.recipe_id,
            i.step_id,
            i.batch or 0,
        )

    heap: list[tuple[tuple[int, int, int, int, str, str, int], str]] = []
    for i in inst:
        if remaining[i.key] == 0:
            heapq.heappush(heap, (prio(i.key), i.key))

    placed: dict[str, tuple[int, int]] = {}
    conflict_msgs: dict[str, list[str]] = {}
    warnings: list[PlanWarning] = []

    def label(i: StepInstance) -> str:
        who = labels.get(i.meal_index)
        return f"{who}: {i.recipe_name} - {i.title}" if who else f"{i.recipe_name} - {i.title}"

    def hours_jump(i: StepInstance, s: int) -> int | None:
        """If [s, s+dur) breaks working-hours/day rules return an earlier start, else None."""
        dur, act = i.duration, i.active
        e = s + dur
        ds, de = s // MIN_PER_DAY, e // MIN_PER_DAY
        s_tod, e_tod = s - ds * MIN_PER_DAY, e - de * MIN_PER_DAY
        if i.day_offset is not None:
            day = i.meal_day + i.day_offset
            if ds < day:
                return None  # too early for its required day; day_ok() rejects it
            if ds > day or de > day:
                cand = day * MIN_PER_DAY + we - dur
                return cand if cand < s else None
            if act > 0:
                if s_tod + act > we:
                    return day * MIN_PER_DAY + we - act
                if e_tod > we:
                    return day * MIN_PER_DAY + we - dur
            return None
        if act == 0:
            return None
        if s_tod < ws:
            return (ds - 1) * MIN_PER_DAY + we - act
        if s_tod + act > we:
            return ds * MIN_PER_DAY + we - act
        if e_tod > we:
            return de * MIN_PER_DAY + we - dur
        if e_tod < ws:
            return (de - 1) * MIN_PER_DAY + we - dur
        return None

    def day_ok(i: StepInstance, s: int) -> bool:
        if i.day_offset is None:
            return True
        day = i.meal_day + i.day_offset
        e = s + i.duration
        if not (s // MIN_PER_DAY == day and e // MIN_PER_DAY == day):
            return False
        return not (i.active > 0 and (s % MIN_PER_DAY < ws or e % MIN_PER_DAY > we))

    def resource_violation(i: StepInstance, s: int) -> tuple[str, Fraction, int, int, int] | None:
        for d in i.demands:
            res = resources[d.type]
            v = res.first_violation(s, s + i.duration, d.count, d.min_capacity)
            if v is not None:
                return d.type, v[0], v[1], v[2], v[3]
        if cook_res is not None and i.cooks > 0 and i.active > 0:
            v = cook_res.first_violation(s, s + i.active, i.cooks, Fraction(0))
            if v is not None:
                return COOK, v[0], v[1], v[2], v[3]
        return None

    def static_impossible(i: StepInstance) -> str | None:
        for d in i.demands:
            res = resources[d.type]
            have = res.avail(d.min_capacity)
            if d.count > have:
                if not res.caps:
                    return f"{_pretty(d.type)} is not in this kitchen"
                if d.min_capacity > 0 and res.avail(Fraction(0)) >= d.count:
                    return (
                        f"needs a {_pretty(d.type)} of capacity {float(d.min_capacity):.3g} but "
                        f"the largest is smaller"
                    )
                return f"needs {d.count} {_plural(d.type, d.count)} but only {have} exist"
        if cook_res is not None and i.cooks > len(cook_res.caps):
            return f"needs {i.cooks} cooks but max_cooks is {len(cook_res.caps)}"
        return None

    while heap:
        _, k = heapq.heappop(heap)
        i = by_key[k]
        end_cap = latest_end[k]
        s0 = _floor(end_cap - i.duration, grid)
        lower_end = (
            i.serve_minute - i.earliest_offset
            if i.earliest_offset is not None
            else i.serve_minute - settings.max_lookback_min
        )
        reason: str | None = static_impossible(i)
        is_static = reason is not None
        chosen: int | None = None
        if reason is None:
            s = s0
            first_blocker: str | None = None
            guard = 0
            while s + i.duration >= lower_end and guard < 100000:
                guard += 1
                j = hours_jump(i, s)
                if j is not None:
                    if first_blocker is None:
                        first_blocker = "working hours"
                    s = _floor(j, grid)
                    continue
                if not day_ok(i, s):
                    if first_blocker is None:
                        first_blocker = "its required day"
                    break
                rv = resource_violation(i, s)
                if rv is None:
                    chosen = s
                    break
                if first_blocker is None:
                    first_blocker = _pretty(rv[0])
                s -= grid
            if chosen is None:
                reason = (
                    f"no free slot for {_pretty(first_blocker or 'resources')} inside its window"
                    if first_blocker
                    else "no slot inside its allowed window"
                )
        if chosen is None:
            # fall back to the preferred slot (nudged into working hours) and flag it
            s = s0
            for _ in range(1000):
                j = hours_jump(i, s)
                if j is None:
                    break
                s = _floor(j, grid)
            else:  # pragma: no cover - defensive
                s = s0
            chosen = s if s + i.duration <= end_cap else s0
            if is_static:
                # reported through the oversubscription pass below
                conflict_msgs.setdefault(k, [])
            else:
                conflict_msgs.setdefault(k, []).append(
                    f"{label(i)} could not be placed legally: {reason}. "
                    f"Placed at {clock.range(chosen, chosen + i.duration)}."
                )
        e = chosen + i.duration
        for d in i.demands:
            resources[d.type].book(chosen, e, d.count, d.min_capacity, k)
        if cook_res is not None and i.cooks > 0 and i.active > 0:
            cook_res.book(chosen, chosen + i.active, i.cooks, Fraction(0), k)
        placed[k] = (chosen, e)
        for d_key in i.deps:
            latest_end[d_key] = min(latest_end[d_key], chosen)
            remaining[d_key] -= 1
            if remaining[d_key] == 0:
                heapq.heappush(heap, (prio(d_key), d_key))

    # --- result assembly
    flags: dict[str, list[str]] = {k: list(v) for k, v in conflict_msgs.items() if v}
    for k in sorted(conflict_msgs):
        i = by_key[k]
        for m in conflict_msgs[k]:
            warnings.append(PlanWarning("conflict", "step_unplaceable", m, i.meal_index))

    all_res = [resources[t] for t in sorted(resources)] + ([cook_res] if cook_res else [])
    for res in all_res:
        for a, b, need, have, keys in res.oversubscribed():
            names = ", ".join(sorted({by_key[x].title for x in keys}))[:160]
            meals = sorted({by_key[x].meal_index for x in keys})
            who = " / ".join(labels.get(m, f"meal {m + 1}") for m in meals)
            what = "cooks" if res.name == COOK else _plural(res.name, need)
            for x in keys:
                flags.setdefault(x, []).append(
                    f"{what} oversubscribed {clock.range(a, b)} (need {need}, have {have})"
                )
            warnings.append(
                PlanWarning(
                    "conflict",
                    "oversubscribed",
                    f"{who} needs {need} {what} from {clock.range(a, b)} "
                    f"but only {have} exist ({names}).",
                    meals[0] if meals else None,
                )
            )
    stations = _assign_stations(inst, placed, resources, kitchen)
    steps = [
        ScheduledStep(by_key[k], s, e, tuple(flags.get(k, ())), tuple(stations.get(k, ())))
        for k, (s, e) in placed.items()
    ]
    steps.sort(key=lambda x: (x.start, x.end, x.instance.sort_key))
    return Schedule(steps, warnings)


def _assign_stations(
    inst: list[StepInstance],
    placed: dict[str, tuple[int, int]],
    resources: dict[str, _Resource],
    kitchen: KitchenProfile,
) -> dict[str, list[str]]:
    """Give each equipment demand a named physical unit (best fit, deterministic)."""
    out: dict[str, list[str]] = {}
    by_key = {i.key: i for i in inst}
    for t, res in resources.items():
        free_at = [-(10**9)] * len(res.caps)
        items = sorted(
            (
                (placed[b.key][0], -b.min_cap, b.key, d)
                for b in res.bookings
                for d in by_key[b.key].demands
                if d.type == t
            ),
            key=lambda x: (x[0], x[1], x[2]),
        )
        seen: set[tuple[str, str]] = set()
        for start, _, key, d in items:
            if (key, t) in seen:
                continue
            seen.add((key, t))
            end = placed[key][1]
            names: list[str] = []
            for _n in range(d.count):
                best: int | None = None
                for idx, cap in enumerate(res.caps):
                    if free_at[idx] > start:
                        continue
                    if cap is not None and cap < d.min_capacity:
                        continue
                    if best is None:
                        best = idx
                        continue
                    bc = res.caps[best]
                    # prefer the smallest unit that fits (None = unlimited sorts last)
                    if cap is not None and (bc is None or cap < bc):
                        best = idx
                if best is None:
                    names.append(f"{_pretty(t).title()} (over capacity)")
                else:
                    free_at[best] = end
                    names.append(_unit_name(t, best, res.caps[best]))
            out.setdefault(key, []).extend(names)
    return out


def _unit_name(t: str, idx: int, cap: Fraction | None) -> str:
    base = f"{_pretty(t).title()} {idx + 1}"
    return f"{base} ({float(cap):.3g})" if cap is not None else base
