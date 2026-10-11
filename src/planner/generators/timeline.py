"""Timeline: interleaved prep/cook schedule by day, plus a per-station view."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from planner.core import units as u
from planner.core.plan import Plan
from planner.core.scheduler import ScheduledStep
from planner.generators import base


@dataclass(frozen=True)
class TimelineRow:
    start: str
    end: str
    start_t: str  # time of day, for tables already grouped by day
    end_t: str
    day: int
    title: str
    recipe: str
    meal: str
    batch: str
    duration: int
    active: int
    equipment: str
    stations: str
    conflict: bool
    flags: tuple[str, ...]
    instructions: str
    serve: str


@dataclass(frozen=True)
class TimelineDay:
    label: str
    rows: tuple[TimelineRow, ...]


@dataclass(frozen=True)
class StationDay:
    label: str
    rows: tuple[TimelineRow, ...]


@dataclass(frozen=True)
class Station:
    name: str
    days: tuple[StationDay, ...]


@dataclass
class TimelineData:
    days: list[TimelineDay] = field(default_factory=list)
    stations: list[Station] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    footer: str = (
        "Food-safety hints are informational only and are not a guarantee. Hot food "
        "should stay at or above {hot} F, cold food at or below {cold} F, and cooked "
        "food should not sit out of temperature longer than {limit} hours."
    )


def _equipment_text(s: ScheduledStep) -> str:
    parts = []
    for d in s.instance.demands:
        text = d.type.replace("_", " ")
        if d.count > 1:
            text = f"{d.count} x {text}"
        if d.min_capacity > 0:
            text += f" (>= {u.format_amount(d.min_capacity)})"
        parts.append(text)
    return ", ".join(parts)


def _row(plan: Plan, s: ScheduledStep) -> TimelineRow:
    i = s.instance
    meal = plan.meals[i.meal_index]
    batch = f"batch {i.batch} of {i.n_batches}" if i.batch is not None else ""
    return TimelineRow(
        start=plan.clock.describe(s.start),
        end=plan.clock.describe(s.end),
        start_t=plan.clock.tod(s.start),
        end_t=(
            plan.clock.tod(s.end)
            if plan.clock.day_of(s.end) == plan.clock.day_of(s.start)
            else plan.clock.describe(s.end)
        ),
        day=plan.clock.day_of(s.start),
        title=i.title,
        recipe=i.recipe_name,
        meal=meal.title,
        batch=batch,
        duration=i.duration,
        active=i.active,
        equipment=_equipment_text(s),
        stations=", ".join(s.stations),
        conflict=s.has_conflict,
        flags=s.conflicts,
        instructions=i.instructions,
        serve=plan.clock.tod(i.serve_minute),
    )


def _day_label(plan: Plan, day: int) -> str:
    base_label = plan.clock.day_label(day)
    return base_label if day >= 0 else f"{base_label} (before the event)"


def build_timeline(plan: Plan) -> TimelineData:
    s = plan.settings
    data = TimelineData(
        footer=(
            "Food-safety hints are informational only, not a guarantee. Keep hot food at or "
            f"above {s.hot_hold_f} F and cold food at or below {s.cold_hold_f} F; do not leave "
            f"cooked food out of temperature longer than {s.out_of_temp_min // 60} hours "
            f"({s.out_of_temp_min} min)."
        )
    )
    steps = [x for x in plan.schedule.steps if x.instance.duration > 0 or x.instance.demands]
    by_day: dict[int, list[TimelineRow]] = {}
    by_station: dict[str, dict[int, list[TimelineRow]]] = {}
    for st in steps:
        row = _row(plan, st)
        by_day.setdefault(row.day, []).append(row)
        names = st.stations or ("Hands only (no equipment)",)
        for name in names:
            by_station.setdefault(name, {}).setdefault(row.day, []).append(row)
    for day in sorted(by_day):
        data.days.append(TimelineDay(_day_label(plan, day), tuple(by_day[day])))
    order = _station_order(plan)
    for name in sorted(by_station, key=lambda n: (order.get(n, 10**6), n)):
        data.stations.append(
            Station(
                name,
                tuple(
                    StationDay(_day_label(plan, d), tuple(rows))
                    for d, rows in sorted(by_station[name].items())
                ),
            )
        )
    data.conflicts = [w.message for w in plan.all_warnings if w.level in ("conflict", "error")]
    data.warnings = [w.message for w in plan.all_warnings if w.level == "warning"]
    return data


def _station_order(plan: Plan) -> dict[str, int]:
    out: dict[str, int] = {}
    n = 0
    for item in plan.kitchen.equipment_inventory:
        for idx in range(item.count):
            label = f"{item.type.replace('_', ' ').title()} {idx + 1}"
            out.setdefault(label, n)
            n += 1
    return out


def timeline_csv(data: TimelineData) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(
        [
            "day",
            "start",
            "end",
            "meal",
            "recipe",
            "step",
            "batch",
            "minutes",
            "hands_on_minutes",
            "stations",
            "conflict",
        ]
    )
    for d in data.days:
        for r in d.rows:
            w.writerow(
                [
                    d.label,
                    r.start,
                    r.end,
                    r.meal,
                    r.recipe,
                    r.title,
                    r.batch,
                    r.duration,
                    r.active,
                    r.stations or r.equipment,
                    "YES" if r.conflict else "",
                ]
            )
    return buf.getvalue()


class TimelineGenerator:
    id = "timeline"
    title = "Timeline"
    description = "When to prep, start and add each thing, by day and by station."
    order = 20
    template_dir: Path | None = None

    def generate(self, plan: Plan, options: base.GenOptions) -> base.GeneratorResult:
        data = build_timeline(plan)
        return base.GeneratorResult(
            data, "timeline.html", csv=lambda: timeline_csv(data), csv_filename="timeline.csv"
        )


base.register(TimelineGenerator())
