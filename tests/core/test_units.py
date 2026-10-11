from fractions import Fraction as F

import pytest
from hypothesis import given
from hypothesis import strategies as st

from planner.core import units as u

VOL = ["tsp", "tbsp", "fl oz", "cup", "pt", "qt", "gal", "ml", "l", "pinch"]
MASS = ["oz", "lb", "g", "kg"]


def test_exact_us_definitions():
    assert u.convert(F(1), "gal", "ml") == F(3785411784, 1_000_000)
    assert u.convert(F(1), "gal", "cup") == 16
    assert u.convert(F(1), "cup", "tbsp") == 16
    assert u.convert(F(1), "tbsp", "tsp") == 3
    assert u.convert(F(1), "pt", "cup") == 2
    assert u.convert(F(1), "qt", "pt") == 2
    assert u.convert(F(1), "lb", "oz") == 16
    assert u.convert(F(1), "kg", "g") == 1000
    assert u.convert(F(1), "pinch", "tsp") == F(1, 16)


def test_no_drift():
    assert F(1, 3) * 37 * 3 == 37
    assert u.convert(F(1, 3) * 37, "cup", "tbsp") == F(16 * 37, 3)


@pytest.mark.parametrize(
    "text,amount,unit",
    [
        ("1 1/2 cup", F(3, 2), "cup"),
        ("3/4 tsp", F(3, 4), "tsp"),
        ("2 lb", F(2), "lb"),
        ("0.25 Cups", F(1, 4), "cup"),
        ("6", F(6), "each"),
        ("2 Tablespoons", F(2), "tbsp"),
        ("12 fl oz", F(12), "fl oz"),
        ("1 clove", F(1), "clove"),
        ("3 cloves", F(3), "clove"),
    ],
)
def test_parse_quantity(text, amount, unit):
    q = u.parse_quantity(text)
    assert (q.amount, q.unit) == (amount, unit)


def test_parse_errors():
    with pytest.raises(ValueError):
        u.parse_quantity("lots of salt")
    with pytest.raises(u.UnknownUnit):
        u.parse_quantity("3 furlongs")
    with pytest.raises(ValueError):
        u.parse_number("1/0")
    with pytest.raises(ValueError):
        u.parse_number("1 1/0")
    with pytest.raises(ValueError):
        u.parse_number(True)
    with pytest.raises(ValueError):
        u.parse_number(float("inf"))
    with pytest.raises(ValueError):
        u.parse_number([1])


def test_parse_number_forms():
    assert u.parse_number(0.1) == F(1, 10)
    assert u.parse_number(3) == 3
    assert u.parse_number(F(1, 3)) == F(1, 3)
    assert u.parse_number(".5") == F(1, 2)
    assert u.parse_number("2 1/4") == F(9, 4)


def test_density_conversion():
    d = F(1)  # water
    assert u.convert(F(1), "cup", "g", d) == u.convert(F(1), "cup", "ml")
    flour = F(53, 100)
    g = u.convert(F(2), "cup", "g", flour)
    assert u.convert(g, "g", "cup", flour) == 2


def test_missing_density_and_incompatible():
    with pytest.raises(u.MissingDensity):
        u.convert(F(1), "cup", "lb")
    with pytest.raises(u.MissingDensity):
        u.convert(F(1), "cup", "lb", F(0))
    with pytest.raises(u.IncompatibleUnits):
        u.convert(F(1), "cup", "each")
    with pytest.raises(u.IncompatibleUnits):
        u.convert(F(1), "clove", "each")


def test_convert_to_family_and_base():
    assert u.convert_to_family(F(1), "kg", u.MASS) == 1000
    assert u.convert_to_family(F(1), "l", u.VOLUME) == 1000
    assert u.convert_to_family(F(3), "clove", "count:clove") == 3
    with pytest.raises(u.UnknownUnit):
        u.convert_to_family(F(1), "g", "weird")
    base, fam = u.to_base(F(2), "lb")
    assert fam == u.MASS and u.from_base(base, "oz") == 32
    assert u.family_of("cups") == u.VOLUME
    assert "tsp" in u.known_units()
    assert u.is_count(u.family_of("clove"))


@given(
    st.fractions(min_value=F(1, 1000), max_value=F(100000)),
    st.sampled_from(VOL),
    st.sampled_from(VOL),
)
def test_volume_round_trip(x, a, b):
    assert u.convert(u.convert(x, a, b), b, a) == x


@given(
    st.fractions(min_value=F(1, 1000), max_value=F(100000)),
    st.sampled_from(MASS),
    st.sampled_from(MASS),
)
def test_mass_round_trip(x, a, b):
    assert u.convert(u.convert(x, a, b), b, a) == x


@given(
    st.fractions(min_value=F(1, 1000), max_value=F(100000)),
    st.sampled_from(VOL),
    st.sampled_from(MASS),
    st.fractions(min_value=F(1, 10), max_value=F(5)),
)
def test_density_round_trip(x, v, m, d):
    assert u.convert(u.convert(x, v, m, d), m, v, d) == x


@given(st.fractions(min_value=F(1, 100), max_value=F(1000)), st.sampled_from(VOL))
def test_conversion_is_additive(x, a):
    assert u.convert(x + x, a, "ml") == 2 * u.convert(x, a, "ml")


@pytest.mark.parametrize(
    "x,s",
    [
        (F(1), "1"),
        (F(3, 2), "1 1/2"),
        (F(1, 3), "1/3"),
        (F(2, 3), "2/3"),
        (F(1, 8), "1/8"),
        (F(1, 3) * 37, "12 1/3"),
        (F(7, 20), "0.35"),
        (F(0), "0"),
        (F(-1, 2), "-1/2"),
        (F(2999, 1000), "3"),
        (F(1, 1000), "0"),
    ],
)
def test_format_amount(x, s):
    assert u.format_amount(x) == s


def test_format_quantity_plural():
    assert u.format_quantity(F(1), "cup") == "1 cup"
    assert u.format_quantity(F(2), "cup") == "2 cups"
    assert u.format_quantity(F(3), "clove") == "3 cloves"
    assert u.format_quantity(F(1, 2), "cup") == "1/2 cup"
    assert u.format_quantity(F(3, 2), "cup") == "1 1/2 cups"
    assert str(u.Quantity(F(1, 2), "tsp")) == "1/2 tsp"


def test_humanize():
    ml = lambda x, unit: u.to_base(F(x), unit)[0]  # noqa: E731
    assert u.humanize(ml(1, "tsp"), u.VOLUME)[1] == "tsp"
    assert u.humanize(ml(2, "tbsp"), u.VOLUME)[1] == "tbsp"
    assert u.humanize(ml(2, "cup"), u.VOLUME)[1] == "cup"
    assert u.humanize(ml(2, "qt"), u.VOLUME)[1] == "qt"
    assert u.humanize(ml(5, "gal"), u.VOLUME)[1] == "gal"
    assert u.humanize(F(500), u.VOLUME, "metric") == (500, "ml")
    assert u.humanize(F(2500), u.VOLUME, "metric") == (F(5, 2), "l")
    assert u.humanize(F(100), u.MASS)[1] == "oz"
    assert u.humanize(F(5000), u.MASS)[1] == "lb"
    assert u.humanize(F(500), u.MASS, "metric") == (500, "g")
    assert u.humanize(F(2500), u.MASS, "metric") == (F(5, 2), "kg")
    assert u.humanize(F(3), "count:clove") == (3, "clove")
    with pytest.raises(u.UnknownUnit):
        u.humanize(F(1), "weird")
    assert u.format_base(u.to_base(F(3), "lb")[0], u.MASS) == "3 lb"


def test_ceil_helpers():
    assert u.ceil_to(F(5, 3), F(1, 2)) == 2
    assert u.ceil_to(F(2), F(1, 2)) == 2
    assert u.ceil_fraction(F(7, 3)) == 3


def test_round_nearest_and_floor():
    assert u.round_nearest(F(5, 3), F(1, 8)) == F(13, 8)
    assert u.round_nearest(F(1, 16), F(1, 8)) == F(1, 8)  # halves go up
    assert u.floor_to(F(5, 3), F(1, 2)) == F(3, 2)
    assert u.floor_to(F(1, 100), F(1)) == 0
