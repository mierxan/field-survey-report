"""The Receiving / Withdrawal cards (analytics.activity_kpis) and the Bad
Order reports by month (analytics.bad_order_by_month). Invented data only."""
from datetime import date
from types import SimpleNamespace

from warehouse import analytics as an
from warehouse.transactions import Transaction


def tx(control, day, packages=None, quantities=()):
    t = Transaction(
        control_no=control, activity="Receiving", date=day, date_text="",
        time="", so_number="SO-1", supplier="Invented Supplier",
        consignee="", warehouse="Invented Yard", destination="",
        condition="Bad Order", po_number="", dr_number="",
        gatepass_number="", bl_awb_number="", remarks="", incident_text="",
        packages=packages)
    # only what qty_by_unit reads: the quantity and the unit of a line
    t.lines = [SimpleNamespace(quantity=q, unit="PCS") for q in quantities]
    return t


def test_the_cards_count_transactions_packages_and_items():
    now = [tx("A", date(2026, 11, 2), 20, (12, 1250)),
           tx("B", date(2026, 11, 3), None, (5,)),         # no Declared Goods
           tx("C", date(2026, 11, 4), 5.5, ())]
    before = [tx("D", date(2026, 10, 2), 10, (100,))]
    cards = an.activity_kpis(now, before, "November 2026")
    assert [c.name for c in cards] == ["Total Transactions", "Total Packages",
                                       "Items Inspected"]
    assert [c.value for c in cards] == [3, 25.5, 1267]
    assert cards[0].comparison.startswith("+200.0%")
    assert cards[2].comparison.startswith("+1167.0%")
    assert all(c.period == "November 2026" for c in cards)


def test_nothing_declared_or_counted_shows_a_dash():
    cards = an.activity_kpis([tx("A", date(2026, 11, 2))])
    assert cards[1].value is None and cards[1].display == "-"
    assert cards[2].value is None and cards[0].comparison == ""


def test_bad_orders_are_grouped_by_month_latest_first():
    reports = [tx("A", date(2026, 10, 5)), tx("B", date(2026, 11, 12)),
               tx("C", date(2026, 11, 2)), tx("D", None)]
    groups = an.bad_order_by_month(reports)
    assert [m for m, _ in groups] == [date(2026, 11, 1), date(2026, 10, 1),
                                      None]
    assert [t.control_no for t in groups[0][1]] == ["B", "C"]
    assert an.bad_order_by_month([]) == []
