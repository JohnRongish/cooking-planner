from fractions import Fraction as F

import pytest

from planner.core.models import Recipe
from planner.web import forms
from tests.helpers import recipe, step


def test_parse_equipment():
    assert forms.parse_equipment("burner, pot@40, oven*2@3, prep table") == [
        {"type": "burner"},
        {"type": "pot", "capacity_hint": "40"},
        {"type": "oven", "count": 2, "capacity_hint": "3"},
        {"type": "prep table"},
    ]
    assert forms.parse_equipment("") == []
    with pytest.raises(forms.FormError):
        forms.parse_equipment("@@")


def test_parse_pairs():
    assert forms.parse_pairs("a=b, c = d\ne=f") == {"a": "b", "c": "d", "e": "f"}
    assert forms.format_pairs({"a": "b", "c": 3}) == "a=b, c=3"
    with pytest.raises(forms.FormError):
        forms.parse_pairs("nope")


def test_recipe_form_round_trip():
    r = Recipe.model_validate(
        {
            "id": "x",
            "name": "X",
            "base_servings": 4,
            "max_batch_servings": 20,
            "tags": ["a", "b"],
            "variants": {"vegan": "y"},
            "diets": ["vegetarian"],
            "ingredients": [
                {
                    "ingredient_id": "i",
                    "quantity": "1/3",
                    "unit": "cup",
                    "scaling": "stepped",
                    "step_size": "1/2",
                }
            ],
            "steps": [
                {
                    "id": "s1",
                    "title": "One",
                    "duration_min": 10,
                    "active_min": 5,
                    "cooks": 2,
                    "equipment": [{"type": "pot", "count": 2, "capacity_hint": "1.5"}],
                    "hold": {"min_temp_f": 140, "max_minutes": 60},
                    "per_batch": True,
                    "earliest_offset": 60,
                    "latest_offset": 10,
                    "day_offset": -1,
                    "depends_on": [],
                    "cooked": True,
                    "can_parallelize_batches": False,
                    "time_scaling": "sqrt",
                }
            ],
        }
    )
    state = forms.recipe_to_form(r)

    class Form(dict):
        def getlist(self, key):
            v = self.get(key, [])
            return v if isinstance(v, list) else [v]

    flat = Form({k: v for k, v in state.items() if k not in ("ingredients", "steps")})
    flat["ing_idx"] = [row["idx"] for row in state["ingredients"]]
    for row in state["ingredients"]:
        for k, v in row.items():
            flat[f"ing_{k}_{row['idx']}"] = v
    flat["st_idx"] = [row["idx"] for row in state["steps"]]
    for row in state["steps"]:
        for k, v in row.items():
            if k in ("cooked", "can_parallelize"):
                if v:
                    flat[f"st_{k}_{row['idx']}"] = "on"
            else:
                flat[f"st_{k}_{row['idx']}"] = v
    again = forms.recipe_form_state(flat)
    data = forms.recipe_data_from_state(again, r)
    assert Recipe.model_validate(data) == r


def test_blank_recipe_state_and_validation_errors():
    state = forms.recipe_to_form(None)
    assert state["base_servings"] == "10"
    state["name"] = "Blank"
    assert forms.recipe_data_from_state(state)["id"] == "blank"
    assert F(1) == 1  # keep Fraction import used
    r = recipe(steps=[step("a", 5)])
    assert forms.recipe_to_form(r)["steps"][0]["duration_min"] == "5"
