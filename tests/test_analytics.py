"""Receiving / Withdrawal summaries, KPIs and filters. Expected values are
counted independently from the hand-made records."""

from datetime import date

from factories import ledger, rec, report, wdr
from warehouse import analytics as an
from warehouse import periods as p
from warehouse.transactions import build_transactions

TODAY = date(2026, 10, 29)


def data():
    return [
        rec("R1", date(2026, 10, 26), "A", 10, warehouse="WH-A",
            supplier="S1", weight="100 kg"),
        rec("R2", date(2026, 10, 26), "B", 5, unit="set", warehouse="WH-B",
            supplier="S2", condition="Bad Order"),
        rec("R3", date(2026, 10, 28), "C", 7, warehouse="WH-A",
            supplier="S1", weight="70"),                 # weight w/o unit
        rec("R4", date(2026, 10, 19), "D", 3, warehouse="WH-A"),  # prev week
        rec("R5", date(2026, 9, 30), "E", 9, warehouse="WH-A"),   # prev month
        wdr("W1", date(2026, 10, 27), "A", 4, warehouse="WH-A",
            consignee="K1"),
        wdr("W2", date(2026, 11, 1), "B", 2, unit="set", warehouse="WH-B",
            consignee="K2"),                              # Sunday, same week
        wdr("W3", date(2026, 11, 2), "C", 1, warehouse="WH-A"),   # next week
    ]


def txs():
    return build_transactions(data())


def test_daily_summary():
    s = an.daily_summary(txs(), "Receiving", date(2026, 10, 26))
    assert s.tx_count == 2 and s.line_count == 2
    assert s.qty == {"PCS": 10, "SET": 5}           # units never combined
    assert s.previous.tx_count == 0


def test_weekly_summary_and_previous_week():
    s = an.weekly_summary(txs(), "Receiving", TODAY)
    assert [t.control_no for t in s.transactions] == ["R1", "R2", "R3"]
    assert s.by_day[date(2026, 10, 26)] == 2 and s.by_day[
        date(2026, 10, 28)] == 1 and len(s.by_day) == 7
    assert s.previous.tx_count == 1                 # R4
    assert dict((w, n) for w, n, _ in s.by_warehouse) == {"WH-A": 2,
                                                          "WH-B": 1}
    assert s.by_condition == {"Good Order": 2, "Bad Order": 1}
    w = an.weekly_summary(txs(), "Withdrawal", TODAY)
    assert [t.control_no for t in w.transactions] == ["W1", "W2"]


def test_monthly_summary():
    s = an.monthly_summary(txs(), "Receiving", TODAY)
    assert s.tx_count == 4                          # R1-R4
    assert s.previous.tx_count == 1                 # R5 in September
    assert dict((k, n) for k, n, _ in s.by_supplier)["S1"] == 2
    assert sum(s.by_week.values()) == 4


def test_weight_total_only_with_units():
    s = an.weekly_summary(txs(), "Receiving", TODAY)
    assert s.weight.kg == 100
    assert s.weight.lines_with_weight == 1 and s.weight.lines_without == 2


def test_filters_warehouse_condition_search():
    f = an.Filters(period=p.period_for("this_month", TODAY),
                   warehouse="wh-a")
    assert {t.control_no for t in an.filter_transactions(txs(), f)} == \
        {"R1", "R3", "R4", "W1"}
    bad = an.Filters(condition="Bad Order")
    assert [t.control_no for t in an.filter_transactions(txs(), bad)] == \
        ["R2"]
    search = an.Filters(search="r3")
    assert [t.control_no for t in an.filter_transactions(txs(), search)] \
        == ["R3"]


def test_inspection_kpis_match_records():
    f = an.Filters(period=p.period_for("this_week", TODAY))
    kpis = {k.name: k for k in an.inspection_kpis(txs(), f)}
    assert kpis["Total Inspection Reports"].value == 5     # R1-3, W1, W2
    assert kpis["Bad Order Reports"].value == 1
    assert kpis["Good Order Reports"].value == 4
    assert round(kpis["Bad Order Percentage"].value, 1) == 20.0
    assert kpis["Receiving Transactions"].value == 3
    assert kpis["Withdrawal Transactions"].value == 2
    assert kpis["Total Inspection Reports"].comparison == \
        "+400.0% vs previous (1)"


def test_change_text_never_divides_by_zero():
    assert an.change_text(5, 0) == \
        "Previous period: 0 - % change not meaningful"
    assert an.change_text(0, 0) == "No change (previous period: 0)"
    assert an.change_text(5, None) == ""
    assert an.change_text(15, 10) == "+50.0% vs previous (10)"


def test_warehouse_kpis_period_versus_balance():
    transactions = txs()
    inventory = ledger(data(), as_of=TODAY)
    f = an.Filters(period=p.period_for("today", TODAY))
    kpis = {k.name: k for k in an.warehouse_kpis(transactions, inventory, f)}
    assert kpis["Total Receiving Transactions"].value == 0   # none today
    # ...but the balance is current, not limited to "today"
    assert kpis["Distinct Cargo Items in Stock"].value == 5
    assert kpis["Estimated Remaining Quantity"].value == {
        "PCS": 6 + 7 + 3 + 9, "SET": 5}             # W2/W3 are after TODAY
    assert "Current balance" in kpis["Distinct Cargo Items in Stock"].period


def test_empty_dataset_does_not_crash():
    f = an.Filters(period=p.period_for("this_month", TODAY))
    empty = ledger([])
    kpis = an.inspection_kpis([], f) + an.warehouse_kpis([], empty, f)
    assert all(k.value in (0, None) for k in kpis)
    bad = {k.name: k for k in an.bad_order_kpis([], f, {})}
    assert bad["Bad Order Percentage"].display == "-"
    assert bad["Unresolved Bad Order Cases"].display == "Not tracked"
    s = an.monthly_summary([], "Receiving", TODAY)
    assert s.tx_count == 0 and s.qty == {} and s.weight.kg is None
    an.management_summary([], empty, f, {})


def test_bad_order_unresolved_only_from_recorded_status():
    f = an.Filters()
    kpis = {k.name: k for k in an.bad_order_kpis(txs(), f, {})}
    assert kpis["Unresolved Bad Order Cases"].value is None
    statuses = {"R2": {"status": "Open"}}
    kpis = {k.name: k for k in an.bad_order_kpis(txs(), f, statuses)}
    assert kpis["Unresolved Bad Order Cases"].value == 1
    statuses = {"R2": {"status": "Resolved"}}
    kpis = {k.name: k for k in an.bad_order_kpis(txs(), f, statuses)}
    assert kpis["Unresolved Bad Order Cases"].value == 0


def test_trend_counts_transactions_per_bucket():
    period = p.custom_period(date(2026, 10, 26), date(2026, 11, 2))
    series, gran = an.trend(txs(), period, "day", activity="Receiving")
    assert gran == "day" and len(series) == 8
    assert [n for _, n in series][:3] == [2, 0, 1]
    weekly, _ = an.trend(txs(), period, "week", activity="Withdrawal")
    assert [n for _, n in weekly] == [2, 1]


def test_types_of_goods_breakdown():
    reports = [report("X1", "Receiving", date(2026, 10, 1), lines=[
        {"cargo": "a", "qty": 1}], goods="used", condition="Bad Order")]
    b = an.bad_order_breakdowns(build_transactions(reports), an.Filters())
    assert b["cargo_type"] == [("Used", 1)]
