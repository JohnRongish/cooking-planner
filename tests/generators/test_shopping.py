from fractions import Fraction as F

from hypothesis import given, settings
from hypothesis import strategies as st

from planner.core.plan import build_plan
from planner.generators import base
from planner.generators.render import build_environment, render_fragment
from planner.generators.shopping import build_shopping, choose_packs, shopping_csv
from tests.helpers import event, ingredient, kitchen, meal, recipe

LB = F(45359237, 100000)  # grams per lb
CUP = F(3785411784, 1_000_000) / 16  # ml per US cup


def ri(iid, q, unit):
    return {"ingredient_id": iid, "quantity": q, "unit": unit}


def packs(*specs):
    return [{"label": label, "size": size, "unit": unit} for label, size, unit in specs]


INGS = [
    ingredient(
        "onion",
        store_section="produce",
        trim_yield="4/5",
        purchase_packs=packs(("50 lb bag", 50, "lb"), ("10 lb bag", 10, "lb")),
    ),
    ingredient(
        "oil",
        store_section="Dry Goods",
        purchase_packs=packs(("1 gal jug", 1, "gal"), ("1 qt bottle", 1, "qt")),
    ),
    ingredient(
        "flour",
        store_section="dry goods",
        density_g_per_ml="0.5",
        purchase_packs=packs(("25 lb bag", 25, "lb"), ("5 lb bag", 5, "lb")),
    ),
    ingredient("salt", store_section="spices"),
    ingredient("mystery", store_section="canned"),
]
A = recipe(
    "a",
    base_servings=10,
    ingredients=[
        ri("onion", 2, "lb"),
        ri("oil", "1/4", "cup"),
        ri("flour", 1, "cup"),
        ri("salt", 1, "tbsp"),
        ri("mystery", 1, "cup"),
    ],
)
B = recipe(
    "b",
    base_servings=5,
    ingredients=[
        ri("onion", 1, "lb"),
        ri("oil", 3, "tbsp"),
        ri("flour", "1/2", "lb"),
        ri("mystery", 1, "lb"),
        ri("ghost", 1, "each"),
    ],
)


def plan(pantry=None, k=None):
    ev = event(
        [meal(recipes=["a"], headcount=100), meal(day=1, recipes=["b"], headcount=50)],
        pantry_on_hand=pantry or [],
    )
    return build_plan(
        ev,
        recipes={"a": A, "b": B},
        ingredients={i.id: i for i in INGS},
        kitchen=k or kitchen(burner=2),
    )


def line(data, iid, family=None):
    return next(
        x for x in data.lines if x.ingredient_id == iid and (family is None or x.family == family)
    )


def test_onions_merge_trim_and_round_to_packs():
    # recipes need 20 lb + 10 lb = 30 lb; 80% yield -> buy 37.5 lb.
    # 4 x 10 lb (leftover 2.5 lb) beats 1 x 50 lb (leftover 12.5 lb).
    ln = line(build_shopping(plan()), "onion")
    assert ln.needed_base == 30 * LB
    assert ln.purchase_base == F(75, 2) * LB
    assert [(label, n) for label, n, _ in ln.packs.counts] == [("10 lb bag", 4)]
    assert ln.packs.leftover == F(5, 2) * LB
    assert ln.needed == "30 lb" and ln.pack_text.startswith("4 x 10 lb bag")
    assert ln.leftover == "2 1/2 lb"


def test_pantry_is_subtracted_from_the_purchase_quantity():
    ln = line(
        build_shopping(plan([{"ingredient_id": "onion", "quantity": 10, "unit": "lb"}])), "onion"
    )
    assert ln.purchase_base == F(55, 2) * LB  # 37.5 - 10
    assert [(label, n) for label, n, _ in ln.packs.counts] == [("10 lb bag", 3)]
    assert ln.pantry == "10 lb"


def test_pantry_can_cover_everything():
    ln = line(
        build_shopping(plan([{"ingredient_id": "onion", "quantity": 100, "unit": "lb"}])), "onion"
    )
    assert ln.purchase_base == 0 and ln.packs is None
    assert ln.to_buy.startswith("none")


def test_volume_amounts_merge_and_pick_pack_combo():
    # 2.5 cup + 30 tbsp (1.875 cup) = 4.375 cup. 2 qt bottles (8 cup) beat a 1 gal jug.
    ln = line(build_shopping(plan()), "oil")
    assert ln.needed_base == F(35, 8) * CUP
    assert [(label, n) for label, n, _ in ln.packs.counts] == [("1 qt bottle", 2)]
    assert ln.packs.leftover == F(29, 8) * CUP
    assert ln.leftover == "3 5/8 cups"


def test_volume_and_weight_merge_through_density():
    # 10 cups of flour (0.5 g/ml) + 5 lb
    ln = line(build_shopping(plan()), "flour")
    assert ln.family == "mass"
    expected = 10 * CUP * F(1, 2) + 5 * LB
    assert ln.needed_base == expected
    assert [(label, n) for label, n, _ in ln.packs.counts] == [("5 lb bag", 2)]
    assert ln.packs.total - ln.needed_base == ln.packs.leftover > 0


def test_missing_density_gives_two_lines_and_a_warning():
    data = build_shopping(plan())
    lines = [x for x in data.lines if x.ingredient_id == "mystery"]
    assert {x.family for x in lines} == {"volume", "mass"}
    assert any("cannot be merged" in w and "Mystery" in w for w in data.warnings)


def test_unknown_ingredient_and_no_pack_lines():
    data = build_shopping(plan())
    assert any("ghost" in w and "catalog" in w for w in data.warnings)
    salt = line(data, "salt")
    assert salt.packs is None and "no pack sizes in catalog" in salt.notes
    assert salt.to_buy  # still a usable number


def test_sections_are_grouped_in_store_order():
    data = build_shopping(plan())
    names = [s.name for s in data.sections]
    assert names.index("produce") < names.index("dry goods") < names.index("canned")
    assert "other" in names  # the ghost ingredient
    assert [x.name for x in data.sections[0].lines] == sorted(
        x.name for x in data.sections[0].lines
    )


def test_csv_and_html_render():
    data = build_shopping(plan())
    text = shopping_csv(data)
    lines = text.strip().splitlines()
    assert lines[0].startswith("section,ingredient,needed_in_recipe,to_purchase")
    assert any(row.startswith("produce,Onion,30 lb") for row in lines)
    gen = base.get("shopping")
    result = gen.generate(plan(), base.GenOptions())
    assert result.csv is not None and result.csv() == text
    html = render_fragment(result, plan(), build_environment())
    assert "Shopping list" in html and "10 lb bag" in html and 'class="box"' in html


def test_unserved_diets_are_noted():
    r = recipe("x", ingredients=[ri("salt", 1, "tbsp")])
    ev = event([meal(recipes=["x"], headcount=10, diet_splits={"vegan": 3})])
    p = build_plan(ev, recipes={"x": r}, ingredients={}, kitchen=kitchen())
    assert any("vegan" in n for n in build_shopping(p).notes)


def test_choose_packs_basics():
    assert choose_packs(F(0), [("a", F(1))]) is None
    assert choose_packs(F(5), []) is None
    c = choose_packs(F(49), [("50", F(50)), ("5", F(5)), ("1", F(1))])
    assert [(lbl, n) for lbl, n, _ in c.counts] == [("50", 1)]  # not 9x5 + 4x1
    c = choose_packs(F(11), [("10", F(10)), ("1", F(1))])
    assert [(lbl, n) for lbl, n, _ in c.counts] == [("10", 1), ("1", 1)]
    c = choose_packs(F(3), [("only", F(2))])
    assert c.n_packs == 2 and c.leftover == 1


def test_choose_packs_tie_prefers_fewer_then_larger():
    c = choose_packs(F(10), [("big", F(10)), ("small", F(5))])
    assert [(lbl, n) for lbl, n, _ in c.counts] == [("big", 1)]


@settings(max_examples=60, deadline=None)
@given(
    st.fractions(min_value=F(1, 10), max_value=F(500)),
    st.lists(
        st.fractions(min_value=F(1, 2), max_value=F(100)), min_size=1, max_size=4, unique=True
    ),
)
def test_choose_packs_always_covers_need(need, sizes):
    c = choose_packs(need, [(str(s), s) for s in sizes])
    assert c.total >= need
    assert c.leftover == c.total - need
    assert all(n > 0 for _, n, _ in c.counts)
    # nothing is wasted: dropping any chosen pack would leave the need uncovered
    assert all(c.total - size < need for _, _, size in c.counts)
