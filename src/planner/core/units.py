"""Units, exact quantities, conversion and display.

Everything is a ``fractions.Fraction``. There are three base families:

* ``volume``: base unit millilitre
* ``mass``: base unit gram
* ``count:<name>``: a named count (``count:each``, ``count:clove``, ...)

US customary units use their exact legal definitions (1 US gal = 231 in^3 =
3785.411784 ml, 1 lb = 453.59237 g), so ``1/3 cup * 37`` never drifts.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction

VOLUME = "volume"
MASS = "mass"
COUNT_PREFIX = "count:"

_GAL_ML = Fraction(3785411784, 1_000_000)
_LB_G = Fraction(45359237, 100_000)


class UnitError(ValueError):
    """Base class for unit problems the caller may want to turn into a warning."""


class UnknownUnit(UnitError):
    pass


class IncompatibleUnits(UnitError):
    """Units are in different families and cannot be converted (e.g. cup -> each)."""


class MissingDensity(UnitError):
    """Volume <-> mass conversion requested but the ingredient has no density."""


@dataclass(frozen=True)
class Unit:
    name: str
    family: str
    factor: Fraction  # amount of the base unit (ml, g, or 1) in one of this unit
    plural: str = ""

    def label(self, amount: Fraction) -> str:
        if amount <= 1 or not self.plural:
            return self.name
        return self.plural


def _u(name: str, family: str, factor: Fraction, plural: str = "") -> Unit:
    return Unit(name, family, factor, plural)


_UNITS: list[Unit] = [
    _u("tsp", VOLUME, _GAL_ML / 768),
    _u("tbsp", VOLUME, _GAL_ML / 256),
    _u("fl oz", VOLUME, _GAL_ML / 128),
    _u("cup", VOLUME, _GAL_ML / 16, "cups"),
    _u("pt", VOLUME, _GAL_ML / 8),
    _u("qt", VOLUME, _GAL_ML / 4),
    _u("gal", VOLUME, _GAL_ML),
    _u("pinch", VOLUME, _GAL_ML / 768 / 16),
    _u("ml", VOLUME, Fraction(1)),
    _u("l", VOLUME, Fraction(1000)),
    _u("oz", MASS, _LB_G / 16),
    _u("lb", MASS, _LB_G),
    _u("g", MASS, Fraction(1)),
    _u("kg", MASS, Fraction(1000)),
    _u("each", COUNT_PREFIX + "each", Fraction(1)),
]
for _name in ("clove", "can", "bunch", "head", "slice", "piece", "sprig", "stalk", "package"):
    _UNITS.append(_u(_name, COUNT_PREFIX + _name, Fraction(1), _name + "s"))

_ALIASES: dict[str, str] = {
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "tsps": "tsp",
    "t": "tsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "tbsps": "tbsp",
    "tbs": "tbsp",
    "tbl": "tbsp",
    "cups": "cup",
    "c": "cup",
    "pint": "pt",
    "pints": "pt",
    "pts": "pt",
    "quart": "qt",
    "quarts": "qt",
    "qts": "qt",
    "gallon": "gal",
    "gallons": "gal",
    "gals": "gal",
    "fl oz": "fl oz",
    "floz": "fl oz",
    "fl. oz": "fl oz",
    "fl. oz.": "fl oz",
    "fluid ounce": "fl oz",
    "fluid ounces": "fl oz",
    "ounce": "oz",
    "ounces": "oz",
    "oz.": "oz",
    "pound": "lb",
    "pounds": "lb",
    "lbs": "lb",
    "lb.": "lb",
    "gram": "g",
    "grams": "g",
    "gr": "g",
    "kilogram": "kg",
    "kilograms": "kg",
    "kgs": "kg",
    "milliliter": "ml",
    "milliliters": "ml",
    "millilitre": "ml",
    "millilitres": "ml",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "ea": "each",
    "ct": "each",
    "count": "each",
    "whole": "each",
    "pinches": "pinch",
    "cloves": "clove",
    "cans": "can",
    "bunches": "bunch",
    "heads": "head",
    "slices": "slice",
    "pieces": "piece",
    "sprigs": "sprig",
    "stalks": "stalk",
    "packages": "package",
    "pkg": "package",
}

_BY_NAME: dict[str, Unit] = {u.name: u for u in _UNITS}


def known_units() -> list[str]:
    return [u.name for u in _UNITS]


def get_unit(name: str) -> Unit:
    key = " ".join(name.strip().lower().split())
    key = _ALIASES.get(key, key)
    try:
        return _BY_NAME[key]
    except KeyError:
        raise UnknownUnit(f"unknown unit: {name!r}") from None


def normalize_unit(name: str) -> str:
    """Canonical spelling of a unit (``'Cups'`` -> ``'cup'``)."""
    return get_unit(name).name


def family_of(unit: str) -> str:
    return get_unit(unit).family


def is_count(family: str) -> bool:
    return family.startswith(COUNT_PREFIX)


# ---------------------------------------------------------------------------
# Exact numbers


_NUM_RE = re.compile(
    r"^\s*(?:(\d+)\s+(\d+)\s*/\s*(\d+)|(\d+)\s*/\s*(\d+)|(\d+(?:\.\d+)?|\.\d+))\s*$"
)


def parse_number(value: object) -> Fraction:
    """Parse ints, decimals and fractions such as ``"1 1/2"``, ``"1/3"``, ``"0.75"``.

    Floats are accepted only via their shortest decimal repr, so ``0.1`` is exactly 1/10.
    """
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("number must be finite")
        return Fraction(repr(value))
    if isinstance(value, str):
        m = _NUM_RE.match(value)
        if not m:
            raise ValueError(f"not a number: {value!r}")
        if m.group(1):
            den = int(m.group(3))
            if den == 0:
                raise ValueError("zero denominator")
            return int(m.group(1)) + Fraction(int(m.group(2)), den)
        if m.group(4):
            den = int(m.group(5))
            if den == 0:
                raise ValueError("zero denominator")
            return Fraction(int(m.group(4)), den)
        return Fraction(m.group(6))
    raise ValueError(f"not a number: {value!r}")


@dataclass(frozen=True)
class Quantity:
    amount: Fraction
    unit: str  # canonical unit name

    def __str__(self) -> str:
        return format_quantity(self.amount, self.unit)


def parse_quantity(text: str) -> Quantity:
    """Parse ``"1 1/2 cup"``, ``"3/4 tsp"``, ``"2 lb"``, ``"6 each"``."""
    s = text.strip()
    m = re.match(r"^(\d+\s+\d+\s*/\s*\d+|\d+\s*/\s*\d+|\d+(?:\.\d+)?|\.\d+)\s*(.*)$", s)
    if not m:
        raise ValueError(f"cannot parse quantity: {text!r}")
    amount = parse_number(m.group(1))
    unit_text = m.group(2).strip() or "each"
    return Quantity(amount, normalize_unit(unit_text))


# ---------------------------------------------------------------------------
# Conversion


def to_base(amount: Fraction, unit: str) -> tuple[Fraction, str]:
    """Convert to (base amount, family)."""
    u = get_unit(unit)
    return amount * u.factor, u.family


def from_base(base_amount: Fraction, unit: str) -> Fraction:
    return base_amount / get_unit(unit).factor


def convert(
    amount: Fraction,
    from_unit: str,
    to_unit: str,
    density_g_per_ml: Fraction | None = None,
) -> Fraction:
    """Convert between units, crossing volume<->mass through the density.

    Raises ``MissingDensity`` rather than guessing, and ``IncompatibleUnits`` for
    count <-> volume/mass or different named counts.
    """
    src, dst = get_unit(from_unit), get_unit(to_unit)
    base = amount * src.factor
    if src.family == dst.family:
        return base / dst.factor
    pair = {src.family, dst.family}
    if pair == {VOLUME, MASS}:
        if density_g_per_ml is None or density_g_per_ml <= 0:
            raise MissingDensity(f"no density to convert {from_unit} to {to_unit}")
        base = base * density_g_per_ml if src.family == VOLUME else base / density_g_per_ml
        return base / dst.factor
    raise IncompatibleUnits(f"cannot convert {from_unit} to {to_unit}")


def convert_to_family(
    amount: Fraction,
    unit: str,
    family: str,
    density_g_per_ml: Fraction | None = None,
) -> Fraction:
    """Convert to the base unit (ml, g, 1) of ``family``."""
    base_unit = {VOLUME: "ml", MASS: "g"}.get(family)
    if base_unit is None:
        if not is_count(family):
            raise UnknownUnit(f"unknown family {family!r}")
        base_unit = family[len(COUNT_PREFIX) :]
    return convert(amount, unit, base_unit, density_g_per_ml)


# ---------------------------------------------------------------------------
# Display


def ceil_fraction(x: Fraction) -> int:
    return math.ceil(x)


def ceil_to(x: Fraction, step: Fraction) -> Fraction:
    """Round ``x`` up to a multiple of ``step``."""
    return Fraction(math.ceil(x / step)) * step


def round_nearest(x: Fraction, step: Fraction) -> Fraction:
    """Round ``x`` to the nearest multiple of ``step`` (halves go up)."""
    return Fraction(math.floor(x / step + Fraction(1, 2))) * step


def floor_to(x: Fraction, step: Fraction) -> Fraction:
    """Round ``x`` down to a multiple of ``step``."""
    return Fraction(math.floor(x / step)) * step


_NICE = [Fraction(n, d) for d in (2, 3, 4, 8) for n in range(1, d)]
_NICE = sorted(set(_NICE))
_TOL = Fraction(1, 100)


def format_amount(x: Fraction) -> str:
    """Friendly, display-only formatting: ``1 1/2``, ``2/3``, ``0.35``.

    Uses nice kitchen fractions (halves, thirds, quarters, eighths) when within
    1/100; otherwise a decimal with up to two places. The stored value is exact.
    """
    if x < 0:
        return "-" + format_amount(-x)
    whole = x.numerator // x.denominator
    frac = x - whole
    if frac == 0:
        return str(whole)
    for nice in _NICE:
        if abs(frac - nice) <= _TOL:
            return (
                f"{whole} {nice.numerator}/{nice.denominator}"
                if whole
                else (f"{nice.numerator}/{nice.denominator}")
            )
    if abs(frac - 1) <= _TOL:
        return str(whole + 1)
    if frac < _TOL:
        return str(whole)
    text = f"{float(x):.2f}".rstrip("0").rstrip(".")
    return text


def format_quantity(amount: Fraction, unit: str) -> str:
    u = get_unit(unit)
    return f"{format_amount(amount)} {u.label(amount)}"


def humanize(base_amount: Fraction, family: str, system: str = "us") -> tuple[Fraction, str]:
    """Pick a readable unit for a base amount, returning (amount, unit)."""
    if is_count(family):
        return base_amount, family[len(COUNT_PREFIX) :]
    if family == VOLUME:
        if system == "metric":
            return (base_amount / 1000, "l") if base_amount >= 1000 else (base_amount, "ml")
        tsp, tbsp, cup, qt, gal = (_BY_NAME[n].factor for n in ("tsp", "tbsp", "cup", "qt", "gal"))
        if base_amount < tbsp:
            return base_amount / tsp, "tsp"
        if base_amount < cup / 4:
            return base_amount / tbsp, "tbsp"
        if base_amount < qt:
            return base_amount / cup, "cup"
        if base_amount < gal:
            return base_amount / qt, "qt"
        return base_amount / gal, "gal"
    if family == MASS:
        if system == "metric":
            return (base_amount / 1000, "kg") if base_amount >= 1000 else (base_amount, "g")
        oz, lb = _BY_NAME["oz"].factor, _BY_NAME["lb"].factor
        return (base_amount / lb, "lb") if base_amount >= lb else (base_amount / oz, "oz")
    raise UnknownUnit(f"unknown family {family!r}")


def format_base(base_amount: Fraction, family: str, system: str = "us") -> str:
    amount, unit = humanize(base_amount, family, system)
    return format_quantity(amount, unit)
