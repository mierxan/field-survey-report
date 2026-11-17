"""Saving a report: a price with no currency is caught (fsr_price_checks).
Invented data only."""
import pytest

import fsr_price_checks as checks


@pytest.mark.parametrize("currency,unit,total,expected", [
    ("", "", "6,585", True),            # a price, no currency
    ("", "2,195", "", True),
    ("PHP", "2,195", "6,585", False),   # currency chosen
    ("", "", "usd 100.-", False),       # code typed with the price
    ("", "", "1,000 jpy", False),
    ("", "", "", False),                # no price at all
    ("", "n/a", "", False),
    ("  ", "", "75", True),
])
def test_a_price_needs_a_currency(currency, unit, total, expected):
    assert checks.needs_currency(currency, unit, total) is expected


def test_the_warning_names_each_line():
    text = checks.missing_currency_text([("Item List 1", [3]),
                                         ("Item List 2", [1, 4])])
    assert "Item List 1: line 3" in text
    assert "Item List 2: lines 1, 4" in text
    assert text.endswith("Save anyway?")


@pytest.mark.parametrize("text,expected", [
    ("1,250.50", (1250.5, "")),
    ("jpy 4,000.-", (4000.0, "JPY")),
    ("PHP 16,000", (16000.0, "PHP")),
    ("₱ 500", (500.0, "PHP")),
    ("1,000 usd", (1000.0, "USD")),
    ("n/a", (None, "")),
    ("", (None, "")),
])
def test_prices_are_read_with_their_currency(text, expected):
    assert checks.parse_money(text) == expected
