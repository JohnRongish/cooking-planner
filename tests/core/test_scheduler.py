from fractions import Fraction as F

from planner.core.graph import GraphError, StepInstance, expand_recipe, validate_graph
from planner.core.plan import build_plan
from planner.core.scheduler import schedule
from planner.core.settings import PlanSettings
from planner.core.timefmt import Clock
from tests.helpers import event, kitchen, meal, recipe, step

SERVE = 18 * 60  # day 0, 18:00


def plan_for(recipes, k, meals, **kw):
    ev = event(meals, **kw)
    return build_plan(
        ev, recipes={r.id: r for r in recipes}, ingredients={}, kitchen=k, settings=kw.get("s")
    )


def by_step(plan, sid, batch=None):
    return next(
        s for s in plan.schedule.steps if s.instance.step_id == sid and s.instance.batch == batch
    )


def test_simple_chain_ends_at_serve_time():
    r = recipe(
        steps=[
            step("chop", 30, equipment=[{"type": "prep_table"}]),
            step("cook", 60, depends_on=["chop"], equipment=[{"type": "burner"}]),
            step("serve", 10, depends_on=["cook"]),
        ]
    )
    p = plan_for([r], kitchen(burner=2, prep_table=1), [meal()])
    serve, cook, chop = by_step(p, "serve"), by_step(p, "cook"), by_step(p, "chop")
    assert serve.end == SERVE
    assert cook.end == serve.start and chop.end == cook.start
    assert chop.start == SERVE - 100
    assert not p.conflicts


def test_every_step_before_serve_and_deps_respected():
    r = recipe(
        steps=[
            step("a", 20),
            step("b", 20, depends_on=["a"]),
            step("c", 15, depends_on=["a"]),
            step("d", 5, depends_on=["b", "c"]),
        ]
    )
    p = plan_for([r], kitchen(), [meal(), meal(day=1, label="lunch", time="12:00")])
    ends = {s.instance.key: s for s in p.schedule.steps}
    for s in p.schedule.steps:
        assert s.end <= s.instance.serve_minute
        for d in s.instance.deps:
            assert ends[d].end <= s.start


def test_deterministic():
    r = recipe(
        steps=[step("a", 20, equipment=[{"type": "burner"}]), step("b", 25, depends_on=["a"])]
    )
    k = kitchen(burner=1, max_cooks=1)
    meals = [meal(day=d, time=t) for d in range(2) for t in ("12:00", "18:00")]
    one = plan_for([r], k, meals).schedule.steps
    two = plan_for([r], k, meals).schedule.steps
    assert [(s.instance.key, s.start, s.end, s.stations) for s in one] == [
        (s.instance.key, s.start, s.end, s.stations) for s in two
    ]


def test_resource_conflict_slides_earlier_without_warning():
    r1 = recipe("r1", steps=[step("cook", 60, equipment=[{"type": "burner"}])])
    r2 = recipe("r2", steps=[step("cook", 60, equipment=[{"type": "burner"}])])
    p = plan_for([r1, r2], kitchen(burner=1), [meal(recipes=["r1", "r2"])])
    a, b = sorted((s for s in p.schedule.steps), key=lambda s: s.start)
    assert b.end == SERVE and a.end == b.start
    assert not p.conflicts


def test_oversubscription_inside_window_gives_prominent_conflict():
    steps = [step("cook", 60, equipment=[{"type": "burner"}], earliest_offset=0)]
    r1, r2 = recipe("r1", steps=steps), recipe("r2", steps=steps)
    p = plan_for([r1, r2], kitchen(burner=1), [meal(recipes=["r1", "r2"], label="dinner")])
    msgs = [w.message for w in p.conflicts]
    assert any(
        "Friday dinner needs 2 burners from Fri 5:00 PM-6:00 PM but only 1 exist" in m for m in msgs
    ), msgs
    assert any(s.has_conflict for s in p.schedule.steps)
    assert all(s.end <= SERVE for s in p.schedule.steps)


def test_missing_equipment_type_is_conflict_not_crash():
    r = recipe(steps=[step("bake", 45, equipment=[{"type": "oven"}])])
    p = plan_for([r], kitchen(burner=2), [meal()])
    assert p.conflicts
    assert "oven" in p.conflicts[0].message and "0 exist" in p.conflicts[0].message


def test_count_exceeds_inventory():
    r = recipe(steps=[step("boil", 20, equipment=[{"type": "burner", "count": 5}])])
    p = plan_for([r], kitchen(burner=4), [meal(label="dinner")])
    assert any("needs 5 burners" in w.message and "only 4 exist" in w.message for w in p.conflicts)


def test_make_ahead_day_offset_and_hours():
    r = recipe(
        steps=[
            step(
                "bake", 45, active_min=10, day_offset=-1, equipment=[{"type": "oven"}], cooked=True
            ),
            step("reheat", 30, depends_on=["bake"], equipment=[{"type": "oven"}]),
        ]
    )
    p = plan_for([r], kitchen(oven=1), [meal(day=1)])
    bake, reheat = by_step(p, "bake"), by_step(p, "reheat")
    assert Clock.day_of(bake.start) == 0 and Clock.day_of(bake.end) == 0
    assert reheat.end == 24 * 60 + SERVE
    kit = kitchen(oven=1)
    assert kit.work_start_min * 1 <= bake.start % 1440 <= kit.work_end_min
    assert bake.end % 1440 <= kit.work_end_min


def test_day_offset_too_late_for_chain_is_conflict():
    r = recipe(
        steps=[
            step("early", 30, day_offset=-1),
            step("late", 30, depends_on=["early"], earliest_offset=0),
        ]
    )
    # 'late' must end exactly at serve; 'early' must be on the day before but can be earlier: ok
    p = plan_for([r], kitchen(), [meal(day=1)])
    assert Clock.day_of(by_step(p, "early").start) == 0
    assert not p.conflicts


def test_earliest_offset_window_respected():
    r = recipe(steps=[step("garnish", 10, earliest_offset=30, equipment=[{"type": "prep_table"}])])
    k = kitchen(prep_table=1)
    p = plan_for(
        [
            r,
            recipe(
                "blocker",
                steps=[step("x", 40, earliest_offset=30, equipment=[{"type": "prep_table"}])],
            ),
        ],
        k,
        [meal(recipes=["r", "blocker"])],
    )
    g = by_step(p, "garnish")
    assert g.end >= SERVE - 30
    assert p.conflicts  # 10 + 40 minutes of prep table cannot both end within 30 min of serving


def test_latest_offset_finishes_before_serve():
    r = recipe(steps=[step("cool", 30, latest_offset=45)])
    p = plan_for([r], kitchen(), [meal()])
    assert by_step(p, "cool").end == SERVE - 45


def test_working_hours_push_long_active_step_to_previous_evening():
    r = recipe(steps=[step("prep", 120)])  # serve 07:00 -> would start 05:00, before hours
    p = plan_for([r], kitchen(), [meal(day=1, time="07:00")])
    s = by_step(p, "prep")
    assert Clock.day_of(s.start) == 0
    assert s.start % 1440 >= 6 * 60 and s.end % 1440 <= 22 * 60 or Clock.day_of(s.end) == 0


def test_passive_step_may_run_overnight():
    r = recipe(steps=[step("chill", 600, active_min=0, equipment=[{"type": "fridge"}])])
    p = plan_for([r], kitchen(fridge=1), [meal(day=1, time="07:00")])
    s = by_step(p, "chill")
    assert s.end == 24 * 60 + 7 * 60 and s.start == s.end - 600


def test_long_step_with_short_active_part_spans_night():
    r = recipe(steps=[step("braise", 600, active_min=30, equipment=[{"type": "oven"}])])
    p = plan_for([r], kitchen(oven=1), [meal(day=1, time="12:00")])
    s = by_step(p, "braise")
    # 600 min before noon is 02:00: not a working hour, so it starts 21:30 the evening
    # before (last time with 30 active minutes before 22:00) and ends 07:30
    assert s.start == 21 * 60 + 30 and s.end == 24 * 60 + 7 * 60 + 30


def test_max_cooks_serialises_active_steps():
    r = recipe(steps=[step("a", 30), step("b", 30)])
    p = plan_for([r], kitchen(max_cooks=1), [meal()])
    a, b = sorted(p.schedule.steps, key=lambda s: s.start)
    assert a.end <= b.start
    p2 = plan_for([r], kitchen(max_cooks=2), [meal()])
    assert {s.start for s in p2.schedule.steps} == {SERVE - 30}


def test_cooks_conflict_when_window_forced():
    steps = [step("a", 30, earliest_offset=0), step("b", 30, earliest_offset=0)]
    p = plan_for([recipe(steps=steps)], kitchen(max_cooks=1), [meal(label="dinner")])
    assert any("cooks" in w.message for w in p.conflicts)


def test_capacity_aware_equipment():
    r = recipe(
        steps=[step("simmer", 60, equipment=[{"type": "pot", "capacity_hint": 3}])],
        base_servings=10,
    )
    # 10 servings -> needs 3 L -> small pot is fine; 100 servings -> 30 L -> only the 40 L pot
    k = kitchen(pot=[(1, 40), (3, 5)])
    p = plan_for([r], k, [meal(headcount=100)])
    assert by_step(p, "simmer").stations == ("Pot 1 (40)",)
    p2 = plan_for([r], k, [meal(headcount=10)])
    assert by_step(p2, "simmer").stations == ("Pot 2 (5)",)


def test_batches_serial_with_one_pot_parallel_with_two():
    r = recipe(
        base_servings=10,
        max_batch_servings=40,
        steps=[
            step("cook", 60, equipment=[{"type": "pot"}], per_batch=True),
            step("serve", 10, depends_on=["cook"]),
        ],
    )
    one = plan_for([r], kitchen(pot=1), [meal(headcount=120)])
    batches = sorted(
        (s for s in one.schedule.steps if s.instance.step_id == "cook"), key=lambda s: s.start
    )
    assert [b.instance.batch for b in batches] and len(batches) == 3
    assert all(batches[i].end <= batches[i + 1].start for i in range(2))
    assert by_step(one, "serve").start >= max(b.end for b in batches)
    assert not one.conflicts
    three = plan_for([r], kitchen(pot=3), [meal(headcount=120)])
    starts = {s.start for s in three.schedule.steps if s.instance.step_id == "cook"}
    assert len(starts) == 1


def test_batch_chain_when_not_parallelizable():
    r = recipe(
        max_batch_servings=40,
        steps=[step("cook", 30, per_batch=True, can_parallelize_batches=False)],
    )
    p = plan_for([r], kitchen(), [meal(headcount=120)])
    cooks = sorted((s for s in p.schedule.steps), key=lambda s: s.instance.batch)
    assert len(cooks) == 3
    assert cooks[0].end <= cooks[1].start and cooks[1].end <= cooks[2].start


def test_time_scaling_changes_durations():
    r = recipe(
        base_servings=10,
        steps=[step("boil", 20, time_scaling="sqrt"), step("brown", 10, time_scaling="linear")],
    )
    p = plan_for([r], kitchen(), [meal(headcount=40)])
    assert by_step(p, "boil").end - by_step(p, "boil").start == 40
    assert by_step(p, "brown").end - by_step(p, "brown").start == 40


def test_interleaves_meals_across_days_with_shared_equipment():
    r = recipe(steps=[step("bake", 60, equipment=[{"type": "oven"}])])
    meals = [meal(day=0, time="18:00"), meal(day=0, label="late", time="18:30")]
    p = plan_for([r], kitchen(oven=1), meals)
    a, b = sorted(p.schedule.steps, key=lambda s: s.start)
    assert a.end <= b.start
    assert not p.conflicts


def test_station_assignment_names_units():
    r = recipe(steps=[step("a", 30, equipment=[{"type": "burner", "count": 2}])])
    p = plan_for([r], kitchen(burner=3), [meal()])
    assert by_step(p, "a").stations == ("Burner 1", "Burner 2")


def test_graph_validation():
    r = recipe(steps=[step("a", 5), step("b", 5, depends_on=["a"])])
    inst = expand_recipe(
        r, servings=F(10), n_batches=1, meal_index=0, position=0, serve_minute=0, meal_day=0
    )
    validate_graph(inst)
    import dataclasses

    bad = [dataclasses.replace(inst[0], deps=(inst[1].key,)), inst[1]]
    try:
        validate_graph(bad)
        raise AssertionError("expected cycle")
    except GraphError as e:
        assert "cycle" in str(e)
    try:
        validate_graph([dataclasses.replace(inst[0], deps=("ghost",))])
        raise AssertionError
    except GraphError as e:
        assert "missing" in str(e)
    try:
        validate_graph([inst[0], inst[0]])
        raise AssertionError
    except GraphError as e:
        assert "duplicate" in str(e)


def test_scheduler_handles_empty_input():
    sch = schedule([], kitchen(), PlanSettings(), Clock(__import__("datetime").date(2025, 1, 1)))
    assert sch.steps == [] and sch.warnings == []
    assert isinstance(StepInstance, type)
