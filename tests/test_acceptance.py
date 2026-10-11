"""End-to-end acceptance tests on the bundled seed data (SPEC section 10)."""

from __future__ import annotations

from fractions import Fraction as F
from pathlib import Path

import pytest

from planner.cli import SEED_DIR, plan_from_bundle, seed_database
from planner.core.models import Meal
from planner.core.plan import Plan, build_plan
from planner.generators import base
from planner.generators.render import build_environment
from planner.generators.shopping import build_shopping
from planner.storage import portability as pt
from planner.web.printing import print_document

LB = F(45359237, 100000)
CUP = F(3785411784, 1_000_000) / 16
TBSP = CUP / 16


@pytest.fixture(scope="module")
def bundle() -> pt.Bundle:
    return pt.load_path(SEED_DIR)


@pytest.fixture(scope="module")
def demo(bundle: pt.Bundle) -> Plan:
    base.discover()
    return plan_from_bundle(bundle, "fall-camp-weekend")


def concurrency(plan: Plan, equip: str) -> int:
    """Independent re-computation of peak concurrent use, straight from the schedule."""
    events: list[tuple[int, int]] = []
    for s in plan.schedule.steps:
        for d in s.instance.demands:
            if d.type == equip:
                events += [(s.start, d.count), (s.end, -d.count)]
    peak = cur = 0
    for _, delta in sorted(events, key=lambda e: (e[0], e[1])):
        cur += delta
        peak = max(peak, cur)
    return peak


def test_demo_event_shape(demo: Plan):
    assert demo.event.id == "fall-camp-weekend"
    assert len(demo.meals) == 7
    assert all(m.meal.headcount == 120 for m in demo.meals)
    assert demo.kitchen.id == "camp-kitchen"
    assert [m.title for m in demo.meals][0] == "Friday dinner"
    assert [m.title for m in demo.meals][-1] == "Sunday lunch"


def test_demo_generates_all_outputs_without_errors(demo: Plan):
    env = build_environment()
    for gen_id in ("shopping", "timeline", "recipes"):
        gen = base.get(gen_id)
        assert gen is not None
        result = gen.generate(demo, base.GenOptions())
        html = print_document(demo, gen, result, "Letter", env)
        assert "<html" in html and len(html) > 5000
        if result.csv:
            assert result.csv().count("\n") > 5
    assert not demo.conflicts, [w.message for w in demo.conflicts]


def test_no_equipment_oversubscription(demo: Plan):
    for item in demo.kitchen.equipment_inventory:
        total = sum(i.count for i in demo.kitchen.equipment_inventory if i.type == item.type)
        assert concurrency(demo, item.type) <= total, item.type


def test_every_step_before_serve_and_windows_respected(demo: Plan, bundle: pt.Bundle):
    recipes = {r.id: r for r in bundle.recipes}
    steps = {s.instance.key: s for s in demo.schedule.steps}
    for s in demo.schedule.steps:
        i = s.instance
        assert s.end <= i.serve_minute - i.latest_offset
        if i.earliest_offset is not None:
            assert s.end >= i.serve_minute - i.earliest_offset
        if i.day_offset is not None:
            day = i.meal_day + i.day_offset
            assert s.start // 1440 == day and s.end // 1440 == day
        for d in i.deps:
            assert steps[d].end <= s.start
    assert recipes  # make-ahead steps exist in the seed
    assert any(s.instance.day_offset == -1 for s in demo.schedule.steps)


def test_deterministic(bundle: pt.Bundle):
    a = plan_from_bundle(bundle, "fall-camp-weekend")
    b = plan_from_bundle(bundle, "fall-camp-weekend")
    sig = lambda p: [(s.instance.key, s.start, s.end, s.stations) for s in p.schedule.steps]  # noqa: E731
    assert sig(a) == sig(b)
    assert [w.message for w in a.all_warnings] == [w.message for w in b.all_warnings]


def test_shopping_hand_checks(demo: Plan):
    data = build_shopping(demo)
    line = {ln.ingredient_id: ln for ln in data.lines}

    # 1. Sandwich bar at 120 x 1.25 portions = 150 servings: 20 slices per 10 -> 300 slices
    #    = exactly 15 loaves of 20 slices.
    bread = line["sandwich-bread"]
    assert bread.needed_base == 300
    assert [(label, n) for label, n, _ in bread.packs.counts] == [("loaf (20 slices)", 15)]
    assert bread.packs.leftover == 0

    # 2. Deli turkey: 1.5 lb per 10 -> 22.5 lb, covered by 2 x 10 lb + 1 x 3 lb (leftover 1/2 lb).
    turkey = line["deli-turkey"]
    assert turkey.needed_base == F(45, 2) * LB
    assert dict((label, n) for label, n, _ in turkey.packs.counts) == {
        "10 lb log": 2,
        "3 lb log": 1,
    }
    assert turkey.packs.leftover == F(1, 2) * LB

    # 3. Eggs: burritos 240 (3 batches of 80) + cornbread 2 x 20 + meatballs 4 batches x 9 = 316,
    #    two 15-dozen cases.
    eggs = line["eggs"]
    assert eggs.needed_base == 316
    assert dict((label, n) for label, n, _ in eggs.packs.counts) == {"15 dozen case": 2}

    # 4. Ground beef: chili 108 people (32.4 lb) + meatballs 108 people (32.4 lb) = 64.8 lb;
    #    6 x 10 lb + 1 x 5 lb = 65 lb.
    beef = line["ground-beef"]
    assert beef.needed_base == F(648, 10) * LB
    assert dict((label, n) for label, n, _ in beef.packs.counts) == {
        "10 lb chub": 6,
        "5 lb chub": 1,
    }

    # 5. Sugar merges cups (cornbread, 2 meals x 5 cups) with tablespoons (marinara, 12 tbsp)
    #    through density 0.85 g/ml, and the 4 lb pantry stock is subtracted.
    sugar = line["sugar"]
    need = (10 * CUP + 12 * TBSP) * F(85, 100)
    assert sugar.needed_base == need
    assert sugar.pantry_base == 4 * LB
    assert sugar.purchase_base == need - 4 * LB
    assert dict((label, n) for label, n, _ in sugar.packs.counts) == {"4 lb bag": 1}

    # 6. Sections are grouped in store order.
    names = [s.name for s in data.sections]
    assert names == sorted(
        names,
        key=lambda n: [
            "produce",
            "meat",
            "dairy",
            "bakery",
            "dry goods",
            "canned",
            "frozen",
            "spices",
            "condiments",
        ].index(n),
    )
    assert not data.warnings, data.warnings


def test_batch_split_recipe_at_120_and_8(bundle: pt.Bundle):
    recipes = {r.id: r for r in bundle.recipes}
    ings = {i.id: i for i in bundle.ingredients}
    kit = next(k for k in bundle.kitchens if k.id == "camp-kitchen")
    ev = bundle.events[0]

    def plan(n: int) -> Plan:
        meal = Meal.model_validate(
            {
                "day": 0,
                "label": "lunch",
                "serve_time": "12:00",
                "recipe_ids": ["minestrone"],
                "headcount": n,
            }
        )
        e = ev.model_copy(update={"meals": [meal], "days": 1, "pantry_on_hand": []})
        return build_plan(e, recipes=recipes, ingredients=ings, kitchen=kit)

    big, small = plan(120), plan(8)
    pr = big.meals[0].recipes[0]
    assert pr.batch.n_batches == 3 and pr.batch.servings_per_batch == 40
    count = lambda p, step: sum(1 for s in p.schedule.steps if s.instance.step_id == step)  # noqa: E731
    assert [count(big, x) for x in ("chop", "saute", "simmer", "pasta", "serve")] == [1, 3, 3, 3, 1]
    assert [count(small, x) for x in ("chop", "saute", "simmer", "pasta", "serve")] == [
        1,
        1,
        1,
        1,
        1,
    ]
    assert small.meals[0].recipes[0].batch.n_batches == 1
    assert not big.conflicts and not small.conflicts


def test_same_recipe_under_backpacking_for_six(bundle: pt.Bundle):
    recipes = {r.id: r for r in bundle.recipes}
    ings = {i.id: i for i in bundle.ingredients}
    packing = next(k for k in bundle.kitchens if k.id == "backpacking")
    trip = next(e for e in bundle.events if e.id == "backpacking-trip")
    p = build_plan(trip, recipes=recipes, ingredients=ings, kitchen=packing)
    assert not p.conflicts and not [w for w in p.all_warnings if w.level == "warning"]
    oat = next(pr for m in p.meals for pr in m.recipes if pr.recipe.id == "oatmeal")
    assert oat.batch.n_batches == 1 and oat.people == 6
    # 2 cups oats per 4 servings -> 3 cups for 6 people
    assert {ln.ingredient_id: ln.needed for ln in oat.lines}["rolled-oats"] == 3
    # the very same recipe also scales to the camp kitchen
    camp = next(k for k in bundle.kitchens if k.id == "camp-kitchen")
    big_event = trip.model_copy(
        update={
            "kitchen_profile_id": camp.id,
            "meals": [
                Meal.model_validate(
                    {
                        "day": 1,
                        "label": "breakfast",
                        "serve_time": "08:00",
                        "recipe_ids": ["oatmeal"],
                        "headcount": 120,
                    }
                )
            ],
        }
    )
    big = build_plan(big_event, recipes=recipes, ingredients=ings, kitchen=camp)
    assert big.meals[0].recipes[0].batch.n_batches == 2
    outputs = [g.generate(p, base.GenOptions()) for g in base.all_generators()]
    assert len(outputs) >= 3


def test_export_wipe_import_gives_identical_plan_output(repo, tmp_path: Path):
    seed_database(repo)

    def render() -> dict[str, str]:
        base.discover()
        ings, recs, kits = repo.catalog()
        ev = repo.get("events", "fall-camp-weekend")
        plan = build_plan(ev, recipes=recs, ingredients=ings, kitchen=kits[ev.kitchen_profile_id])
        env = build_environment()
        out = {}
        for gen in base.all_generators():
            result = gen.generate(plan, base.GenOptions())
            out[gen.id] = print_document(plan, gen, result, "Letter", env)
            if result.csv:
                out[gen.id + ".csv"] = result.csv()
        return out

    before = render()
    pt.export_to_dir(repo, tmp_path / "export")
    repo.wipe()
    assert repo.count("recipes") == 0
    pt.import_bundle(repo, pt.load_path(tmp_path / "export"))
    after = render()
    assert before == after and len(before) >= 4
