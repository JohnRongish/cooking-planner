from planner.core.plan import build_plan
from planner.generators import base
from planner.generators.recipe_sheets import build_recipe_sheets
from planner.generators.render import build_environment, render_fragment
from planner.generators.timeline import build_timeline, timeline_csv
from tests.helpers import event, ingredient, kitchen, meal, recipe, step


def make_plan(headcount=120, k=None, meals=None):
    stew = recipe(
        "stew",
        base_servings=8,
        max_batch_servings=50,
        scaling_notes="Season at the end.",
        ingredients=[
            {"ingredient_id": "beans", "quantity": 1, "unit": "lb"},
            {"ingredient_id": "bay", "quantity": 2, "unit": "each", "scaling": "fixed"},
            {"ingredient_id": "milk", "quantity": 1, "unit": "cup"},
        ],
        steps=[
            step("chop", 20, instructions="Chop everything.", equipment=[{"type": "prep_table"}]),
            step(
                "cook",
                90,
                active_min=15,
                depends_on=["chop"],
                cooked=True,
                equipment=[{"type": "burner"}, {"type": "pot", "capacity_hint": 4}],
                hold={"min_temp_f": 140, "max_minutes": 120},
            ),
            step("serve", 15, depends_on=["cook"]),
        ],
    )
    ings = {
        i.id: i
        for i in [ingredient("beans"), ingredient("bay"), ingredient("milk", allergens=["milk"])]
    }
    ev = event(
        meals
        or [
            meal(recipes=["stew"], headcount=headcount),
            meal(day=1, label="lunch", time="12:00", recipes=["stew"], headcount=headcount),
        ]
    )
    return build_plan(
        ev,
        recipes={"stew": stew},
        ingredients=ings,
        kitchen=k or kitchen(burner=4, prep_table=2, pot=[(2, 30)], max_cooks=4),
    )


def test_recipe_sheet_spells_out_batches():
    sheets = build_recipe_sheets(make_plan()).sheets
    s = sheets[0]
    assert s.batch_statement == "Make 3 batches of ~40 servings"
    assert "max 50 servings per batch" in s.batch_reasons or "holds" in s.batch_reasons
    beans = next(i for i in s.ingredients if i.name == "Beans")
    assert beans.amount == "15 lb" and beans.per_batch == "5 lb"
    bay = next(i for i in s.ingredients if i.name == "Bay")
    assert bay.amount == "6 each" and "does not scale" in bay.note
    assert s.allergens == ("milk",)
    cook = next(x for x in s.steps if x.title == "Cook")
    assert "each of the 3 batches" in cook.batch_note
    assert cook.hold.startswith("Hold at 140 F or above")
    assert cook.when and "Fri" in cook.when


def test_recipe_sheet_single_batch_at_8_servings():
    s = build_recipe_sheets(make_plan(headcount=8)).sheets[0]
    assert s.batch_statement == "Make 1 batch"
    assert all(i.per_batch == "" for i in s.ingredients)


def test_recipe_sheets_render_html():
    p = make_plan()
    result = base.get("recipes").generate(p, base.GenOptions())
    html = render_fragment(result, p, build_environment())
    assert "Make 3 batches of ~40 servings" in html
    assert html.count("<article") == 2 and "Season at the end." in html


def test_timeline_days_and_stations():
    p = make_plan()
    t = build_timeline(p)
    assert [d.label for d in t.days][0].startswith("Friday")
    assert any("batch 1 of 3" in r.batch or r.batch for d in t.days for r in d.rows)
    names = [s.name for s in t.stations]
    assert any(n.startswith("Burner") for n in names) and any(n.startswith("Pot") for n in names)
    assert "Hands only (no equipment)" in names
    assert "not a guarantee" in t.footer and "135" in t.footer
    csv = timeline_csv(t).splitlines()
    assert csv[0].startswith("day,start,end,meal") and len(csv) > 3


def test_timeline_shows_conflicts_prominently():
    p = make_plan(
        k=kitchen(burner=1, prep_table=1, pot=[(1, 30)], max_cooks=1),
        meals=[meal(recipes=["stew"], headcount=120)],
    )
    t = build_timeline(p)
    result = base.get("timeline").generate(p, base.GenOptions())
    html = render_fragment(result, p, build_environment())
    if t.conflicts:
        assert "CONFLICTS" in html
    # one pot, 3 batches of 90 min fit by running one after another with no conflict,
    # but a 45 minute window does not
    p2 = make_plan(k=kitchen(burner=1, prep_table=1, pot=[(1, 30)], max_cooks=1))
    assert "Timeline" in render_fragment(
        base.get("timeline").generate(p2, base.GenOptions()), p2, build_environment()
    )


def test_timeline_html_marks_conflicting_rows():
    r = recipe("r", steps=[step("a", 60, earliest_offset=0, equipment=[{"type": "burner"}])])
    ev = event([meal(recipes=["r", "r2"])])
    r2 = recipe("r2", steps=[step("b", 60, earliest_offset=0, equipment=[{"type": "burner"}])])
    p = build_plan(ev, recipes={"r": r, "r2": r2}, ingredients={}, kitchen=kitchen(burner=1))
    html = render_fragment(
        base.get("timeline").generate(p, base.GenOptions()), p, build_environment()
    )
    assert "CONFLICTS" in html and 'class="conflict"' in html
    assert "needs 2 burners" in html
