"""Formatting of absolute plan minutes (minutes since 00:00 of the event's first day)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

MIN_PER_DAY = 1440


@dataclass(frozen=True)
class Clock:
    start_date: dt.date

    def date_of(self, day: int) -> dt.date:
        return self.start_date + dt.timedelta(days=day)

    def day_name(self, day: int) -> str:
        return self.date_of(day).strftime("%A")

    def day_label(self, day: int) -> str:
        d = self.date_of(day)
        return f"{d.strftime('%A %b')} {d.day}"

    @staticmethod
    def day_of(minute: int) -> int:
        return minute // MIN_PER_DAY

    @staticmethod
    def tod(minute: int) -> str:
        """12-hour time of day, e.g. ``4:05 PM``."""
        m = minute % MIN_PER_DAY
        h, mm = divmod(m, 60)
        suffix = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{mm:02d} {suffix}"

    def describe(self, minute: int) -> str:
        day = self.day_of(minute)
        return f"{self.date_of(day).strftime('%a')} {self.tod(minute)}"

    def range(self, start: int, end: int) -> str:
        if self.day_of(start) == self.day_of(max(start, end - 1)):
            return f"{self.describe(start)}-{self.tod(end)}"
        return f"{self.describe(start)} - {self.describe(end)}"
