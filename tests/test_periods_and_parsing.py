from datetime import date

import pytest

import fsr_storage

from warehouse import periods as p
from warehouse import transactions as t

TODAY = date(2026, 10, 29)          # a Thursday


def test_calendar_week_is_monday_to_sunday():
    week = p.period_for("this_week", TODAY)
    assert (week.start, week.end) == (date(2026, 10, 26), date(2026, 11, 1))
    assert week.start.weekday() == 0 and week.days == 7


@pytest.mark.parametrize("key,start,end", [
    ("today", date(2026, 10, 29), date(2026, 10, 29)),
    ("this_month", date(2026, 10, 1), date(2026, 10, 31)),
    ("this_year", date(2026, 1, 1), date(2026, 12, 31)),
    ("previous_day", date(2026, 10, 28), date(2026, 10, 28)),
    ("previous_week", date(2026, 10, 19), date(2026, 10, 25)),
    ("previous_month", date(2026, 9, 1), date(2026, 9, 30)),
    ("previous_year", date(2025, 1, 1), date(2025, 12, 31)),
])
def test_period_boundaries(key, start, end):
    period = p.period_for(key, TODAY)
    assert (period.start, period.end) == (start, end)


def test_previous_period_of_each_kind():
    assert p.previous_period(p.period_for("this_month", date(2026, 3, 15))) \
        .start == date(2026, 2, 1)
    assert p.previous_period(p.period_for("this_month", date(2026, 3, 15))) \
        .end == date(2026, 2, 28)
    custom = p.custom_period(date(2026, 10, 10), date(2026, 10, 19))
    prev = p.previous_period(custom)
    assert (prev.start, prev.end) == (date(2026, 9, 30), date(2026, 10, 9))
    assert p.previous_period(p.ALL_PERIOD) is None


def test_custom_range_validation():
    with pytest.raises(ValueError):
        p.custom_period(date(2026, 10, 5), date(2026, 10, 1))
    with pytest.raises(ValueError):
        p.period_for("custom", TODAY, (None, None))


def test_period_contains_is_inclusive_and_rejects_none():
    week = p.period_for("this_week", TODAY)
    assert week.contains(date(2026, 10, 26)) and week.contains(
        date(2026, 11, 1))
    assert not week.contains(date(2026, 11, 2)) and not week.contains(None)


def test_buckets_fill_empty_days():
    keys = p.buckets_between(date(2026, 10, 1), date(2026, 10, 3), "day")
    assert len(keys) == 3
    months = p.buckets_between(date(2026, 8, 20), date(2026, 10, 2), "month")
    assert months == [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]


@pytest.mark.parametrize("qty,pack,expected", [
    ("12", "pcs", (12.0, "PCS")),
    ("1,250.5", "Pieces", (1250.5, "PCS")),
    ("12 pcs", "", (12.0, "PCS")),
    ("3", "Sets", (3.0, "SET")),
    ("7", "Wooden Crates", (7.0, "CRATE")),
    ("5", "drums of oil", (5.0, "DRUMS OF OIL")),
])
def test_quantity_parsing(qty, pack, expected):
    number, unit, problems = t.parse_quantity(qty, pack)
    assert (number, unit) == expected and not problems


@pytest.mark.parametrize("qty,pack,problem", [
    ("", "pcs", "missing"), ("n/a", "pcs", "not a number"),
    ("-3", "pcs", "negative"), ("12 box", "pcs", "differs"),
])
def test_quantity_problems(qty, pack, problem):
    number, _, problems = t.parse_quantity(qty, pack)
    assert number is None and problem in problems[0]


@pytest.mark.parametrize("qty,pack,uom,expected", [
    ("12", "Wooden Crates", "pcs", (12.0, "PCS")),       # UOM wins
    ("12", "Wooden Crates", "", (12.0, "CRATE")),        # older lines
    ("12 pcs", "Box", "PCS", (12.0, "PCS")),
])
def test_quantity_uom_column(qty, pack, uom, expected):
    number, unit, problems = t.parse_quantity(qty, pack, uom)
    assert (number, unit) == expected and not problems


@pytest.mark.parametrize("text,expected", [
    ("12 pcs", ("12", "pcs")), ("1,250.5 Wooden Crates", ("1,250.5",
                                                         "Wooden Crates")),
    ("12", ("12", "")), ("n/a", ("n/a", "")), ("", ("", "")),
    # a number with thousands or decimals and no unit stays whole (it was
    # split into "18" + ",400" and saved back as "18 ,400")
    ("18,400", ("18,400", "")), ("1,250.50", ("1,250.50", "")),
    ("18,400 KG", ("18,400", "KG")), ("5-10", ("5-10", "")),
])
def test_split_quantity_unit(text, expected):
    assert fsr_storage.split_quantity_unit(text) == expected
    assert fsr_storage.split_quantity_unit(text, "SET")[1] == "SET"


@pytest.mark.parametrize("text,kg", [
    ("1,250 kg", 1250), ("1.5 MT", 1500), ("100 lbs", 45.359237),
    ("500 g", 0.5)])
def test_weight_conversion(text, kg):
    assert t.parse_weight(text)[0] == pytest.approx(kg)


def test_weight_without_unit_is_not_guessed():
    value, note = t.parse_weight("1000")
    assert value is None and "no unit" in note


def test_activity_and_date_parsing():
    assert t.normalize_activity("receiving") == t.RECEIVING
    assert t.normalize_activity("WITHDRAWAL ") == t.WITHDRAWAL
    assert t.parse_day("05-Oct-2026") == date(2026, 10, 5)
    assert t.parse_day("05-10-2026") == date(2026, 10, 5)
    assert t.parse_day("soon") is None
