from fractions import Fraction as F

import pytest
from hypothesis import given
from hypothesis import strategies as st

from planner.core.models import Recipe, RecipeIngredient
from planner.core.scaling import (
    plan_batches,
    purchase_quantity,
    scale_amount,
    scale_factor,
    scale_minutes,
)


def ri(q, unit="cup", scaling="linear", step=1):
    return RecipeIngredient(
        ingredient_id="x", quantity=q, unit=unit, scaling=scaling, step_size=step
    )


def test_scale_factor():
    assert scale_factor(120, F(5, 4), F(8)) == F(75, 4)
    assert scale_factor(4, F(1), F(4)) == 1


def test_linear_exact():
    # 1/3 cup for 4 servings, 148 servings -> 37x -> exactly 37/3 cup
    assert scale_amount(ri("1/3"), F(37)) == F(37, 3)


def test_fixed_per_batch():
    assert scale_amount(ri(1, "each", "fixed"), F(30), 1) == 1
    assert scale_amount(ri(1, "each", "fixed"), F(30), 3) == 3


def test_stepped_rounds_up_per_batch():
    egg = ri(1, "each", "stepped")
    assert scale_amount(egg, F(5, 2)) == 3  # 2.5 -> 3
    # 3 batches, each needs 2.5/3 *... factor 7.5 -> 2.5/batch -> 3 each -> 9
    assert scale_amount(egg, F(15, 2), 3) == 9
    can = ri(2, "can", "stepped", step=F(1, 2))
    assert scale_amount(can, F(3, 4)) == F(3, 2)


def test_trim_yield():
    assert purchase_quantity(F(8), F(4, 5)) == 10
    assert purchase_quantity(F(8), None) == 8


@pytest.mark.parametrize(
    "mins,mode,scale,out",
    [
        (10, "none", F(30), 10),
        (0, "linear", F(3), 0),
        (10, "linear", F(3), 30),
        (10, "linear", F(1, 100), 1),
        (10, "sqrt", F(4), 20),
        (10, "sqrt", F(2), 15),
        (10, "sqrt", F(1), 10),
        (60, "sqrt", F(1, 4), 30),
    ],
)
def test_scale_minutes(mins, mode, scale, out):
    assert scale_minutes(mins, mode, scale) == out


@given(st.integers(1, 600), st.fractions(min_value=F(1, 50), max_value=F(60)))
def test_sqrt_is_ceiling_of_true_root(mins, scale):
    out = scale_minutes(mins, "sqrt", scale)
    assert out >= 1
    assert F(out) ** 2 >= F(mins) ** 2 * scale
    assert F(out - 1) ** 2 < F(mins) ** 2 * scale or out == 1


@given(st.fractions(min_value=F(1, 100), max_value=F(100)), st.integers(1, 500))
def test_linear_scaling_is_proportional(q, n):
    r = ri(q)
    assert scale_amount(r, F(n)) == q * n
    assert scale_amount(r, F(n)) / q == n


def recipe(max_batch=None, hint=None, base=8, per_batch=None):
    return Recipe.model_validate(
        {
            "id": "r",
            "name": "R",
            "base_servings": base,
            "max_batch_servings": max_batch,
            "steps": [
                {
                    "id": "cook",
                    "title": "Cook",
                    "duration_min": 30,
                    "per_batch": per_batch,
                    "equipment": [{"type": "pot", "capacity_hint": hint}],
                }
            ],
        }
    )


def test_one_batch_at_small_size():
    plan = plan_batches(recipe(max_batch=50), F(8))
    assert plan.n_batches == 1 and not plan.is_split


def test_three_batches_at_120():
    plan = plan_batches(recipe(max_batch=50), F(120))
    assert plan.n_batches == 3
    assert plan.servings_per_batch == 40
    assert plan.is_split and plan.reasons


def test_capacity_forces_split():
    # needs 4 L at 8 servings -> 60 L at 120. Largest pot 40 L -> 2 batches of 60 servings
    plan = plan_batches(recipe(hint=4), F(120), {"pot": F(40)})
    assert plan.n_batches == 2
    assert plan_batches(recipe(hint=4), F(8), {"pot": F(40)}).n_batches == 1


def test_capacity_and_max_batch_take_larger():
    plan = plan_batches(recipe(max_batch=20, hint=4), F(120), {"pot": F(100)})
    assert plan.n_batches == 6


def test_capacity_ignored_without_data():
    assert plan_batches(recipe(hint=4), F(120), {}).n_batches == 1
    assert plan_batches(recipe(hint=4), F(120), {"pot": None}).n_batches == 1


def test_shared_steps_dont_force_batches():
    assert plan_batches(recipe(hint=4, per_batch=False), F(120), {"pot": F(10)}).n_batches == 1


def test_batch_never_exceeds_servings():
    assert plan_batches(recipe(max_batch=F(1, 2)), F(3)).n_batches == 3


@given(st.integers(1, 400), st.integers(1, 80))
def test_batches_cover_servings_equally(servings, maxb):
    plan = plan_batches(recipe(max_batch=maxb), F(servings))
    assert plan.servings_per_batch * plan.n_batches == servings
    assert plan.servings_per_batch <= max(maxb, 1) or plan.n_batches == servings
