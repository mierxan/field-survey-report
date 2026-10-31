"""Reporting periods with fixed calendar boundaries.

Weeks are calendar weeks Monday-Sunday (ISO 8601). Every period is a closed
range of whole days: start <= day <= end.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

DISPLAY_FORMAT = "%d-%b-%Y"

# (key, label) in the order the period selector shows them.
PERIOD_CHOICES = [
    ("today", "Today"),
    ("this_week", "This Week"),
    ("this_month", "This Month"),
    ("this_year", "This Year"),
    ("previous_day", "Previous Day"),
    ("previous_week", "Previous Week"),
    ("previous_month", "Previous Month"),
    ("previous_year", "Previous Year"),
    ("all", "All Records"),
    ("custom", "Custom Date Range"),
]
PERIOD_LABELS = dict(PERIOD_CHOICES)


@dataclass(frozen=True)
class Period:
    start: date | None          # None = no lower limit ("All Records")
    end: date | None
    kind: str                   # day, week, month, year, custom, all
    label: str

    def contains(self, day):
        if day is None:
            return False
        if self.start is not None and day < self.start:
            return False
        if self.end is not None and day > self.end:
            return False
        return True

    @property
    def days(self):
        if self.start is None or self.end is None:
            return None
        return (self.end - self.start).days + 1

    def range_text(self):
        if self.start is None:
            return "All recorded dates"
        if self.start == self.end:
            return self.start.strftime(DISPLAY_FORMAT)
        return (f"{self.start.strftime(DISPLAY_FORMAT)} to "
                f"{self.end.strftime(DISPLAY_FORMAT)}")

    def describe(self):
        return f"{self.label} ({self.range_text()})"


def week_start(day):
    return day - timedelta(days=day.weekday())


def month_end(day):
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def day_period(day, label=None):
    return Period(day, day, "day", label or day.strftime(DISPLAY_FORMAT))


def week_period(day, label=None):
    start = week_start(day)
    end = start + timedelta(days=6)
    iso = start.isocalendar()
    return Period(start, end, "week",
                  label or f"Week {iso[1]}, {iso[0]}")


def month_period(day, label=None):
    start = day.replace(day=1)
    return Period(start, month_end(start), "month",
                  label or start.strftime("%B %Y"))


def year_period(day, label=None):
    return Period(date(day.year, 1, 1), date(day.year, 12, 31), "year",
                  label or str(day.year))


def custom_period(start, end, label="Custom Date Range"):
    if start is None or end is None:
        raise ValueError("A custom range needs a start and an end date.")
    if end < start:
        raise ValueError("The end date is before the start date.")
    return Period(start, end, "custom", label)


ALL_PERIOD = Period(None, None, "all", "All Records")


def period_for(key, today=None, custom=None):
    """The period of a selector choice. `custom` = (start, end)."""
    today = today or date.today()
    if key == "today":
        return day_period(today, "Today")
    if key == "this_week":
        return week_period(today, "This Week")
    if key == "this_month":
        return month_period(today, "This Month")
    if key == "this_year":
        return year_period(today, "This Year")
    if key == "previous_day":
        return day_period(today - timedelta(days=1), "Previous Day")
    if key == "previous_week":
        return week_period(week_start(today) - timedelta(days=7),
                           "Previous Week")
    if key == "previous_month":
        return month_period(today.replace(day=1) - timedelta(days=1),
                            "Previous Month")
    if key == "previous_year":
        return year_period(date(today.year - 1, 1, 1), "Previous Year")
    if key == "all":
        return ALL_PERIOD
    if key == "custom":
        start, end = custom or (None, None)
        return custom_period(start, end)
    raise ValueError(f"Unknown period: {key}")


def previous_period(period):
    """The period of the same kind just before `period` (for comparisons).
    None for "All Records"."""
    if period.start is None:
        return None
    if period.kind == "day":
        return day_period(period.start - timedelta(days=1), "Previous Day")
    if period.kind == "week":
        return week_period(period.start - timedelta(days=7), "Previous Week")
    if period.kind == "month":
        return month_period(period.start - timedelta(days=1),
                            "Previous Month")
    if period.kind == "year":
        return year_period(date(period.start.year - 1, 1, 1),
                           "Previous Year")
    length = period.days
    end = period.start - timedelta(days=1)
    return Period(end - timedelta(days=length - 1), end, "custom",
                  "Previous Range")


# ---------- buckets for trend charts ----------

def bucket_key(day, granularity):
    """The first day of the day / week / month that contains `day`."""
    if granularity == "day":
        return day
    if granularity == "week":
        return week_start(day)
    if granularity == "month":
        return day.replace(day=1)
    raise ValueError(granularity)


def bucket_label(start, granularity):
    if granularity == "day":
        return start.strftime("%d-%b")
    if granularity == "week":
        return f"Wk {start.isocalendar()[1]} ({start.strftime('%d-%b')})"
    return start.strftime("%b %Y")


def buckets_between(start, end, granularity):
    """Every bucket start from `start` to `end` (so empty days show as 0)."""
    if start is None or end is None or end < start:
        return []
    keys, current = [], bucket_key(start, granularity)
    while current <= end:
        keys.append(current)
        if granularity == "day":
            current += timedelta(days=1)
        elif granularity == "week":
            current += timedelta(days=7)
        else:
            current = (month_end(current) + timedelta(days=1))
    return keys


def auto_granularity(period):
    days = period.days
    if days is None or days > 120:
        return "month"
    if days > 31:
        return "week"
    return "day"
