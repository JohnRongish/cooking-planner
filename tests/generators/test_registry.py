from pathlib import Path

import pytest

from planner.core.plan import build_plan
from planner.generators import base
from planner.generators.render import build_environment, render_fragment
from tests.generators.example_generator import HeadcountGenerator, register_example
from tests.helpers import event, kitchen, meal, recipe, step


@pytest.fixture()
def example():
    gen = register_example()
    yield gen
    base.unregister(gen.id)


def a_plan():
    r = recipe(steps=[step("a", 10)])
    ev = event([meal(headcount=30), meal(day=1, label="lunch", headcount=45)])
    return build_plan(ev, recipes={"r": r}, ingredients={}, kitchen=kitchen())


def test_builtin_generators_are_discovered():
    loaded = base.discover()
    assert {"shopping", "timeline", "recipe_sheets"} <= set(loaded)
    assert "_stubs" not in loaded and "base" not in loaded
    ids = [g.id for g in base.all_generators()]
    assert ids[:3] == ["shopping", "timeline", "recipes"]


def test_stubs_are_not_registered():
    ids = {g.id for g in base.all_generators()}
    assert not ids & {"cost", "allergens", "equipment", "pack_weight"}
    from planner.generators._stubs.cost import CostStub

    with pytest.raises(NotImplementedError):
        CostStub().generate(a_plan(), base.GenOptions())


def test_example_generator_needs_no_changes_outside_generators(example):
    # registering is all it takes: it lists, generates, renders and exports
    assert base.get("headcount") is example
    assert "headcount" in [g.id for g in base.all_generators()]
    assert example.template_dir in base.template_dirs()
    plan = a_plan()
    result = example.generate(plan, base.GenOptions())
    html = render_fragment(result, plan, build_environment())
    assert "Friday dinner: 30" in html and "Saturday lunch: 45" in html
    assert "Total served: 75" in html
    assert result.csv().splitlines()[0] == "meal,people"
    assert isinstance(example, base.Generator)


def test_example_is_gone_after_unregister():
    assert base.get("headcount") is None


def test_duplicate_ids_are_rejected(example):
    with pytest.raises(base.DuplicateGenerator):
        base.register(HeadcountGenerator())
    assert base.register(example) is example  # re-registering the same object is fine


def test_default_template_dir_exists():
    assert Path(base.DEFAULT_TEMPLATE_DIR, "shopping.html").exists()
