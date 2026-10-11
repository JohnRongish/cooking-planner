from fractions import Fraction as F

from planner.core.plan import build_plan, validate_event
from planner.core.settings import PlanSettings
from planner.core.timefmt import Clock
from tests.helpers import event, ingredient, kitchen, meal, recipe, step


def ri(iid, q, unit="cup", **kw):
    return {"ingredient_id": iid, "quantity": q, "unit": unit, **kw}


def build(recipes, meals, k=None, ings=None, **kw):
    ev = event(meals, **kw)
    return build_plan(
        ev,
        recipes={r.id: r for r in recipes},
        ingredients={i.id: i for i in (ings or [])},
        kitchen=k or kitchen(burner=4, oven=2, pot=[(2, 40)]),
    )


def test_scaling_lines_and_modes():
    r = recipe(
        base_servings=4,
        ingredients=[
            ri("rice", "1/3"),
            ri("bay", 1, "each", scaling="fixed"),
            ri("egg", 2, "each", scaling="stepped"),
        ],
    )
    p = build([r], [meal(headcount=37, portion_factor="1.25")])
    pr = p.meals[0].recipes[0]
    assert pr.servings == F(37 * 5, 4) and pr.factor == F(37 * 5, 16)
    lines = {ln.ingredient_id: ln for ln in pr.lines}
    assert lines["rice"].needed == F(1, 3) * F(37 * 5, 16)
    assert lines["bay"].needed == 1
    assert lines["egg"].needed == 24  # 2 * 185/16 = 23.125 rounds up to a whole egg


def test_batch_split_120_vs_8():
    r = recipe(
        "stew",
        base_servings=8,
        max_batch_servings=50,
        ingredients=[ri("beans", 1, "lb", scaling="linear"), ri("bay", 2, "each", scaling="fixed")],
        steps=[
            step("cook", 90, equipment=[{"type": "pot", "capacity_hint": 4}]),
            step("serve", 15, depends_on=["cook"]),
        ],
    )
    big = build([r], [meal(recipes=["stew"], headcount=120)]).meals[0].recipes[0]
    assert big.batch.n_batches == 3 and big.batch.servings_per_batch == 40
    assert {ln.ingredient_id: ln.needed for ln in big.lines}["bay"] == 6
    p = build([r], [meal(recipes=["stew"], headcount=120)])
    assert sum(1 for s in p.schedule.steps if s.instance.step_id == "cook") == 3
    assert sum(1 for s in p.schedule.steps if s.instance.step_id == "serve") == 1
    small = build([r], [meal(recipes=["stew"], headcount=8)])
    assert small.meals[0].recipes[0].batch.n_batches == 1
    assert sum(1 for s in small.schedule.steps if s.instance.step_id == "cook") == 1


def test_capacity_driven_batching():
    r = recipe(
        "soup",
        base_servings=10,
        steps=[step("simmer", 60, equipment=[{"type": "pot", "capacity_hint": 5}])],
    )
    p = build([r], [meal(recipes=["soup"], headcount=100)], k=kitchen(pot=[(2, 30)]))
    assert p.meals[0].recipes[0].batch.n_batches == 2  # 50 L needed, 30 L pots
    assert not p.conflicts


def test_diet_splits_variants_and_unserved():
    chili = recipe(
        "chili",
        base_servings=10,
        diets=[],
        variants={"vegetarian": "veg-chili"},
        ingredients=[ri("beef", 1, "lb")],
        steps=[step("cook", 30)],
    )
    veg = recipe(
        "veg-chili", base_servings=10, ingredients=[ri("beans", 1, "lb")], steps=[step("cook", 30)]
    )
    p = build(
        [chili, veg],
        [meal(recipes=["chili"], headcount=50, diet_splits={"vegetarian": 10, "nut_free": 5})],
    )
    m = p.meals[0]
    roles = [(pr.recipe.id, pr.role, pr.people) for pr in m.recipes]
    assert roles == [("chili", "main", 35), ("veg-chili", "variant", 10)]
    assert m.unserved == {"nut_free": 5}
    assert any(w.code == "diet_unserved" for w in p.warnings)
    # the variant has its own steps in the schedule
    assert {s.instance.recipe_id for s in p.schedule.steps} == {"chili", "veg-chili"}


def test_recipe_that_already_satisfies_diet():
    r = recipe("salad", diets=["vegetarian"], steps=[step("toss", 10)])
    p = build([r], [meal(recipes=["salad"], headcount=20, diet_splits={"vegetarian": 8})])
    assert [(pr.role, pr.people) for pr in p.meals[0].recipes] == [("main", 20)]
    assert p.meals[0].unserved == {}


def test_validation_messages():
    r = recipe("camp-only", tags=["backpacking-only"], ingredients=[ri("ghost", 1)])
    k = kitchen(burner=2)
    ev = event([meal(recipes=["camp-only", "nope"], diet_splits={"v": 99})])
    w = validate_event(ev, {"camp-only": r}, {}, k)
    codes = {x.code for x in w}
    assert {
        "profile_mismatch",
        "unknown_recipe",
        "unknown_ingredient",
        "splits_exceed_headcount",
    } <= codes
    mismatch = next(x for x in w if x.code == "profile_mismatch")
    assert "backpacking-only" in mismatch.message
    assert validate_event(ev, {}, {}, None)[0].code == "no_kitchen"


def test_unknown_recipe_is_skipped_not_fatal():
    p = build([recipe(steps=[step("a", 5)])], [meal(recipes=["r", "missing"])])
    assert [pr.recipe.id for pr in p.meals[0].recipes] == ["r"]
    assert any(w.code == "unknown_recipe" for w in p.all_warnings)
    assert p.conflicts  # errors count as blocking


def test_planned_recipe_helpers():
    p = build([recipe(steps=[step("a", 5)])], [meal(), meal(day=1)])
    assert len(p.planned_recipes()) == 2
    pr = p.meals[0].recipes[0]
    assert pr.key_prefix == "m0p0:r"
    assert [s.instance.meal_index for s in p.steps_for(pr)] == [0]
    assert p.meals[0].title == "Friday dinner"


def test_safety_hold_and_out_of_temp():
    r = recipe(
        steps=[
            step("cook", 30, cooked=True),
            step("hold", 300, depends_on=["cook"], hold={"min_temp_f": 120, "max_minutes": 240}),
            step("cold", 60, hold={"max_temp_f": 50}),
            step("wait", 5, hold={"max_minutes": 500}),
        ]
    )
    p = build([r], [meal()])
    codes = {w.code for w in p.all_warnings}
    assert {"hot_hold_low", "cold_hold_high", "hold_too_long", "hold_exceeded"} <= codes


def test_safety_cooked_gap_warning_and_configurable():
    r = recipe(steps=[step("cook", 30, cooked=True, latest_offset=300)])
    p = build([r], [meal()])
    assert any(w.code == "out_of_temp" for w in p.all_warnings)
    ev = event([meal()])
    p2 = build_plan(
        ev,
        recipes={"r": r},
        ingredients={},
        kitchen=kitchen(),
        settings=PlanSettings(out_of_temp_min=400),
    )
    assert not any(w.code == "out_of_temp" for w in p2.all_warnings)


def test_safe_when_cooked_food_is_held_hot():
    r = recipe(
        steps=[
            step(
                "cook",
                30,
                cooked=True,
                latest_offset=300,
                hold={"min_temp_f": 140, "max_minutes": 400},
            )
        ]
    )
    p = build([r], [meal()])
    assert not any(w.code == "out_of_temp" for w in p.all_warnings)


def test_timefmt():
    import datetime as dt

    c = Clock(dt.date(2025, 6, 6))
    assert c.day_name(1) == "Saturday"
    assert c.day_label(0) == "Friday Jun 6"
    assert c.tod(0) == "12:00 AM" and c.tod(13 * 60 + 5) == "1:05 PM"
    assert c.describe(24 * 60 + 17 * 60) == "Sat 5:00 PM"
    assert c.range(17 * 60, 18 * 60) == "Fri 5:00 PM-6:00 PM"
    assert c.range(23 * 60, 25 * 60) == "Fri 11:00 PM - Sat 1:00 AM"


def test_ingredient_helper_used():
    assert ingredient("salt").name == "Salt"
