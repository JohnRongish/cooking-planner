"""Tunable planning parameters (food-safety thresholds, grid, lookback)."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class PlanSettings:
    hot_hold_f: Fraction = Fraction(135)  # hot food must stay at or above this
    cold_hold_f: Fraction = Fraction(41)  # cold food must stay at or below this
    out_of_temp_min: int = 240  # max minutes cooked food may sit out of temperature
    grid_min: int = 5  # step start times are multiples of this
    max_lookback_min: int = 4320  # default earliest a step may end before serve (72 h)
    units: str = "us"  # display system: "us" or "metric"
