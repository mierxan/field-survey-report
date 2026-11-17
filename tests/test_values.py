"""The Owner's Dashboard: Top 10 Suppliers by Total Value in PHP, from the
Receiving reports only (warehouse/values.py), and the exchange rates kept
with the warehouse settings. Invented data only."""
from datetime import date

import pytest

from warehouse import analytics as an
from warehouse import values as val
from warehouse.periods import month_period
from warehouse.store import SideStore
from warehouse.transactions import build_transactions
from conftest import ANCHOR

RATES = {"USD": 58.0, "JPY": 0.38}


def report(control, supplier, rows, activity="Receiving", day="05-Nov-2026"):
    return {"control_no": control,
            "general_information": {"inspection_date": day,
                                    "supplier": supplier,
                                    "location": "Invented Yard"},
            "inspection_schedule": {"activity": activity},
            "item_lists": [{"rows": rows}]}


def row(quantity="", unit="", total="", currency=""):
    return {"Description of Goods": "Invented item", "Quantity": quantity,
            "Unit Price": unit, "Total Price": total, "Currency": currency}


TRANSACTIONS = build_transactions([
    report("FSR-T-0001", "Invented Alpha",
           [row("2", "1,000", "2,000", "PHP"),          # 2,000
            row("3", "10", "", "USD")]),                 # 30 USD = 1,740
    report("FSR-T-0002", "Invented Beta",
           [row("1", "", "10,000", "JPY")]),             # 3,800
    report("FSR-T-0003", "Invented Beta",
           [row("1", "", "usd 100.-", "")]),             # 5,800
    report("FSR-T-0004", "Invented Gamma",
           [row("1", "", "50", "SEK"),                   # no rate
            row("1", "", "75", ""),                      # no currency
            row("4", "", "", "")]),                      # no price
    # Withdrawals are never counted
    report("FSR-T-0005", "Invented Alpha",
           [row("1", "", "999,999", "PHP")], activity="Withdrawal"),
    # another month
    report("FSR-T-0006", "Invented Alpha",
           [row("1", "", "500", "PHP")], day="05-Oct-2026"),
])
NOVEMBER = an.Filters(period=month_period(date(2026, 11, 5)))


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
    assert val.parse_money(text) == expected


def test_suppliers_are_ranked_by_value_in_php():
    result = val.top_suppliers_by_value(TRANSACTIONS, NOVEMBER, RATES)
    assert result.rows == [
        ("Invented Beta", pytest.approx(3800 + 5800), 2),
        ("Invented Alpha", pytest.approx(2000 + 1740), 1)]
    assert result.priced_lines == 4
    assert result.no_rate == {"SEK": 1}
    assert result.no_currency == 1
    assert result.unpriced == 1
    note = result.note()
    assert "SEK (1 line)" in note and "no currency: 1" in note


def test_without_a_rate_only_php_is_counted():
    result = val.top_suppliers_by_value(TRANSACTIONS, NOVEMBER, {})
    assert result.rows == [("Invented Alpha", 2000, 1)]
    assert result.no_rate == {"USD": 2, "JPY": 1, "SEK": 1}


def test_only_the_top_ten_are_shown():
    many = build_transactions([
        report(f"FSR-T-{n:04d}", f"Invented Supplier {n:02d}",
               [row("1", "", str(n * 100), "PHP")]) for n in range(1, 15)])
    result = val.top_suppliers_by_value(many, NOVEMBER, {})
    assert len(result.rows) == 10
    assert result.rows[0] == ("Invented Supplier 14", 1400, 1)
    assert result.rows[-1][0] == "Invented Supplier 05"


def test_the_currencies_used_are_offered_for_a_rate():
    assert val.currencies_in(TRANSACTIONS) == ["JPY", "SEK", "USD"]


def test_the_rates_are_kept_with_the_warehouse_settings(tmp_path):
    side = SideStore(tmp_path / "Invented.xlsx")
    assert side.php_rates() == {} and side.php_rates_updated() is None
    side.set_php_rates({"usd": 58.25, "JPY": "", "EUR": 63}, "Invented Owner")
    again = SideStore(tmp_path / "Invented.xlsx")
    assert again.php_rates() == {"USD": 58.25, "EUR": 63.0}
    assert again.php_rates_updated()[1] == "Invented Owner"
    with pytest.raises(ValueError):
        again.set_php_rates({"USD": 0})
    assert val.rates_text(again.php_rates()) == \
        "1 EUR = 63 PHP  ·  1 USD = 58.25 PHP"


def test_the_demo_data_has_prices_on_receiving_lines_only(sample):
    snap = sample["snapshot"]
    priced = [(tx.activity, line.currency) for tx in snap.transactions
              for line in tx.lines if line.total_price]
    assert priced and {a for a, _ in priced} == {"Receiving"}
    result = val.top_suppliers_by_value(
        snap.transactions, an.Filters(period=month_period(ANCHOR)),
        {"USD": 58, "JPY": 0.38, "EUR": 63})
    assert 0 < len(result.rows) <= 10
    values = [v for _, v, _ in result.rows]
    assert values == sorted(values, reverse=True)
    assert result.no_rate == {}
