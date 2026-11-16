"""The Dashboard sheet of the Weekly / Monthly Receiving and Withdrawal
Excel reports (warehouse/dashboard.py, exports.write_dashboard): its cards
and charts show the same figures as the summary, and the file holds real
Excel charts."""
import zipfile

import pytest
from openpyxl import load_workbook

from warehouse import analytics as an
from warehouse import dashboard as dash
from warehouse import exports as ex
from warehouse.periods import month_period
from conftest import ANCHOR


@pytest.mark.parametrize("kind", ["weekly", "monthly"])
@pytest.mark.parametrize("activity", ["Receiving", "Withdrawal"])
def test_the_dashboard_shows_the_summarys_figures(sample, kind, activity):
    snap = sample["snapshot"]
    summary = (an.weekly_summary if kind == "weekly" else
               an.monthly_summary)(snap.transactions, activity, ANCHOR)
    board = dash.build(summary, kind)
    name = "Weekly" if kind == "weekly" else "Monthly"
    assert board.title == f"{name} {activity} Dashboard"
    assert board.period == summary.period.describe()
    cards = {card.label: card for card in board.cards}
    assert cards["Transactions"].value == an.fmt_number(summary.tx_count)
    good = summary.by_condition["Good Order"]
    bad = summary.by_condition["Bad Order"]
    assert cards["Good / Bad Order"].value == f"{good} Good · {bad} Bad"
    charts = {chart.title: chart for chart in board.charts}
    timeline = charts["Transactions per Day" if kind == "weekly"
                      else "Transactions per Week"]
    assert sum(timeline.values) == summary.tx_count
    assert len(timeline.values) == (7 if kind == "weekly"
                                    else len(summary.by_week))
    assert charts["Good Order / Bad Order"].values == [good, bad]
    if activity == "Receiving":
        total = sum(summary.qty.values())
        assert cards["Total Quantity Received"].value == an.fmt_number(total)
        per = charts[f"Quantity Received per "
                     f"{'Day' if kind == 'weekly' else 'Week'}"]
        assert sum(per.values) == pytest.approx(total)
        party = charts["Top Suppliers (transactions)"]
    else:
        assert cards["Cargo Lines Withdrawn"].value == \
            an.fmt_number(summary.line_count)
        per = charts[f"Cargo Lines Withdrawn per "
                     f"{'Day' if kind == 'weekly' else 'Week'}"]
        assert sum(per.values) == summary.line_count
        party = charts["Top Consignees (transactions)"]
    assert sum(party.values) == summary.tx_count
    sites = charts["Transactions per Site / Warehouse"]
    assert sum(sites.values) == summary.tx_count
    assert board.comparison == an.comparison_rows(summary)


def test_the_change_against_the_previous_period_has_an_arrow(sample):
    snap = sample["snapshot"]
    summary = an.monthly_summary(snap.transactions, "Receiving", ANCHOR)
    card = dash.cards_of(summary)[0]
    previous = summary.previous.tx_count
    assert card.change == an.change_text(summary.tx_count, previous)
    assert card.trend == (summary.tx_count > previous) - \
        (summary.tx_count < previous)


def test_long_lists_keep_the_top_ones_and_add_up_the_rest():
    groups = [(f"Supplier {n}", 20 - n, 0) for n in range(12)]
    top = dash._top(groups)
    assert len(top) == dash.TOP_PARTIES
    assert top[0] == ("Supplier 0", 20)
    assert top[-1][0] == "Others (5)"
    assert sum(c for _, c in top) == sum(c for _, c, _ in groups)


@pytest.mark.parametrize("key", ["weekly_receiving_report",
                                 "monthly_withdrawal_report",
                                 "weekly_withdrawal", "monthly_receiving"])
def test_the_excel_file_starts_with_the_dashboard(sample, tmp_path, key):
    snap = sample["snapshot"]
    doc = ex.build_report(key, snap, an.Filters(), ANCHOR)
    path = ex.export(doc, tmp_path / f"{key}.xlsx")
    wb = load_workbook(path)
    assert wb.sheetnames[0] == "Dashboard" and wb.active.title == "Dashboard"
    ws = wb["Dashboard"]
    assert ws["A1"].value == doc.dashboard.title.upper()
    assert ws["A2"].value == doc.dashboard.period
    for index, card in enumerate(doc.dashboard.cards):
        column = index * 4 + 1
        assert ws.cell(row=5, column=column).value == card.label.upper()
        assert ws.cell(row=6, column=column).value == card.value
    shown = [c for c in doc.dashboard.charts
             if c.labels and not (c.kind == "doughnut" and c.empty)]
    assert len(ws._charts) == len(shown)
    # the other sheets are still there, after the dashboard
    assert wb.sheetnames[1] == "Summary"
    with zipfile.ZipFile(path) as z:
        charts = [n for n in z.namelist() if n.startswith("xl/charts/")]
        assert len(charts) == len(shown)
        for name in charts:
            text = z.read(name).decode("utf-8")
            if "#,##0;-#,##0;;" in text:
                # without it Excel labels empty days with 0
                assert 'formatCode="#,##0;-#,##0;;" sourceLinked="0"' in text


def test_daily_reports_and_other_reports_have_no_dashboard(sample, tmp_path):
    snap = sample["snapshot"]
    for key in ("daily_receiving", "bad_order", "management"):
        doc = ex.build_report(key, snap, an.Filters(
            period=month_period(ANCHOR)), ANCHOR)
        assert doc.dashboard is None
        wb = load_workbook(ex.export(doc, tmp_path / f"{key}.xlsx"))
        assert "Dashboard" not in wb.sheetnames


def test_an_empty_period_still_makes_a_dashboard(tmp_path):
    from warehouse import store
    snap = store.load_snapshot(tmp_path / "none.xlsx")
    doc = ex.build_report("weekly_receiving_report", snap, an.Filters(),
                          ANCHOR)
    wb = load_workbook(ex.export(doc, tmp_path / "empty.xlsx"))
    ws = wb["Dashboard"]
    assert ws.cell(row=6, column=1).value == "0"
    notes = [c.value for row in ws.iter_rows() for c in row
             if isinstance(c.value, str) and "no transactions" in c.value]
    assert any("Good Order / Bad Order" in n for n in notes)


def test_axis_steps_are_whole_numbers():
    assert [ex.nice_step(t) for t in (0, 3, 7, 13, 30, 130, 1222)] == \
        [1, 1, 1, 2, 5, 20, 200]


def test_withdrawal_highlights_the_delivery_destinations(sample, tmp_path):
    snap = sample["snapshot"]
    summary = an.monthly_summary(snap.transactions, "Withdrawal", ANCHOR)
    board = dash.build(summary, "monthly")
    charts = {chart.title: chart for chart in board.charts}
    places = charts["Shipments per Delivery Destination"]
    assert sum(places.values) == summary.tx_count
    (table,) = board.tables
    assert table.headings == ["Destination", "Shipments", "Total Packages",
                              "Cargo Line Items", "Share of Shipments"]
    assert sum(r[1] for r in table.rows) == summary.tx_count
    assert sum(r[3] for r in table.rows) == summary.line_count
    assert table.total[:2] == ["TOTAL WITHDRAWAL", summary.tx_count]
    assert sum(r[4] for r in table.rows) == pytest.approx(1)
    by_place = {}
    for tx in summary.transactions:
        key = tx.destination or "(not recorded)"
        by_place[key] = by_place.get(key, 0) + 1
    assert {r[0]: r[1] for r in table.rows} == by_place
    receiving = an.monthly_summary(snap.transactions, "Receiving", ANCHOR)
    assert dash.build(receiving, "monthly").tables == []
    # in the file, under the comparison
    doc = ex.build_report("monthly_withdrawal_report", snap, an.Filters(),
                          ANCHOR)
    ws = load_workbook(ex.export(doc, tmp_path / "wd.xlsx"))["Dashboard"]
    texts = [c.value for row in ws.iter_rows() for c in row if c.value]
    assert "WITHDRAWAL  ·  DELIVERY DESTINATIONS" in texts
    assert "TOTAL WITHDRAWAL" in texts
