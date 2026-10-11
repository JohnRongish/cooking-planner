import json
from fractions import Fraction as F

import pytest
from pydantic import ValidationError

from planner.core.models import (
    Event,
    Ingredient,
    KitchenProfile,
    Meal,
    Recipe,
    Step,
    format_hhmm,
    parse_hhmm,
    slugify,
)
from tests.helpers import event, ingredient, kitchen, meal, recipe, step


def test_hhmm():
    assert parse_hhmm("7:05") == 425
    assert format_hhmm(425) == "07:05"
    with pytest.raises(ValueError):
        parse_hhmm("25:00")
    assert slugify("Mac & Cheese!") == "mac-cheese"
    assert slugify("!!!") == "item"


def test_qty_round_trip_json():
    ing = Ingredient.model_validate(
        {
            "id": "x",
            "name": "X",
            "density_g_per_ml": "0.53",
            "trim_yield": "4/5",
            "purchase_packs": [{"label": "bag", "size": "1/3", "unit": "lb"}],
        }
    )
    assert ing.density_g_per_ml == F(53, 100)
    dumped = ing.model_dump(mode="json")
    assert dumped["density_g_per_ml"] == 0.53
    assert dumped["purchase_packs"][0]["size"] == "1/3"
    again = Ingredient.model_validate(json.loads(json.dumps(dumped)))
    assert again == ing


def test_ingredient_validation():
    with pytest.raises(ValidationError):
        ingredient("Bad Id")
    with pytest.raises(ValidationError):
        ingredient("x", trim_yield="1.5")
    with pytest.raises(ValidationError):
        ingredient("x", density_g_per_ml=0)
    with pytest.raises(ValidationError):
        ingredient("x", purchase_packs=[{"label": "z", "size": 0, "unit": "g"}])
    with pytest.raises(ValidationError):
        ingredient("x", surprise=1)
    with pytest.raises(ValidationError):
        ingredient("x", density_g_per_ml="abc")


def test_step_validation():
    with pytest.raises(ValidationError):
        Step(id="a", title="t", duration_min=5, active_min=10)
    with pytest.raises(ValidationError):
        Step(id="a", title="t", earliest_offset=5, latest_offset=10)
    with pytest.raises(ValidationError):
        Step(id="a", title="t", day_offset=1)
    s = Step(id="a", title="t", duration_min=5)
    assert s.active == 5 and not s.is_per_batch
    assert Step(id="a", title="t", duration_min=5, active_min=2).active == 2
    assert Step(id="a", title="t", per_batch=True).is_per_batch


def test_recipe_graph_validation():
    with pytest.raises(ValidationError, match="duplicate"):
        recipe(steps=[step("a", 1), step("a", 1)])
    with pytest.raises(ValidationError, match="unknown step"):
        recipe(steps=[step("a", 1, depends_on=["zz"])])
    with pytest.raises(ValidationError, match="itself"):
        recipe(steps=[step("a", 1, depends_on=["a"])])
    with pytest.raises(ValidationError, match="cycle"):
        recipe(steps=[step("a", 1, depends_on=["b"]), step("b", 1, depends_on=["a"])])
    with pytest.raises(ValidationError):
        recipe(base_servings=0)
    with pytest.raises(ValidationError):
        recipe(max_batch_servings=0)
    with pytest.raises(ValidationError):
        Recipe.model_validate(
            {
                "id": "r",
                "name": "R",
                "base_servings": 1,
                "ingredients": [{"ingredient_id": "x", "quantity": -1, "unit": "g"}],
            }
        )
    with pytest.raises(ValidationError):
        Recipe.model_validate(
            {
                "id": "r",
                "name": "R",
                "base_servings": 1,
                "ingredients": [{"ingredient_id": "x", "quantity": 1, "unit": "g", "step_size": 0}],
            }
        )


def test_recipe_derived_fields():
    r = recipe(
        tags=["backpacking-only", "x"],
        steps=[step("a", 1, equipment=[{"type": "Big Pot"}, {"type": "burner"}])],
    )
    assert r.equipment_required == ["big_pot", "burner"]
    assert r.only_for == ["backpacking"]
    # derived key in exported data is accepted on import
    data = r.model_dump(mode="json")
    data["equipment_required"] = ["big_pot", "burner"]
    assert Recipe.model_validate(data) == r


def test_kitchen():
    k = kitchen(oven=2, pot=[(1, 40), (2, 20)], max_cooks=3)
    assert k.units_of("pot") == [F(40), F(20), F(20)]
    assert k.max_capacity("pot") == 40
    assert k.max_capacity("oven") is None
    assert k.units_of("grill") == []
    assert k.work_start_min == 360 and k.work_end_min == 1320
    with pytest.raises(ValidationError):
        KitchenProfile.model_validate(
            {"id": "k", "name": "K", "work_start": "22:00", "work_end": "06:00"}
        )
    with pytest.raises(ValidationError):
        KitchenProfile.model_validate({"id": "k", "name": "K", "max_cooks": 0})


def test_event_and_meal():
    e = event([meal(day=1, time="7:30")])
    assert e.meals[0].serve_time == "07:30"
    assert e.meals[0].serve_minute_of_day == 450
    with pytest.raises(ValidationError, match="day"):
        event([meal(day=5)], days=2)
    with pytest.raises(ValidationError):
        Meal.model_validate(meal(headcount=0))
    with pytest.raises(ValidationError):
        Meal.model_validate(meal(portion_factor=0))
    with pytest.raises(ValidationError):
        Meal.model_validate(meal(diet_splits={"veg": -1}))
    assert Event.model_validate(e.model_dump(mode="json")) == e
