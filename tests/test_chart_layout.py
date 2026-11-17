"""How the dashboard charts sit on the sheet (warehouse/chart_style.py), for
the Weekly / Monthly Dashboard and the interactive one: pinned to their
cells inside the 16 columns, never over another chart, title and legend in
their own place, and printed pages that start between charts.

Seen in the field: charts given in centimetres ran past their columns
(display scaling, WPS Office, phone viewers) and lay under the next chart,
and the title was drawn over the legend. Invented data only."""
import pytest
from openpyxl import Workbook
from openpyxl.drawing.spreadsheet_drawing import TwoCellAnchor

from warehouse import analytics as an
from warehouse import chart_style
from warehouse import dashboard as dash
from warehouse import exports as ex
from conftest import ANCHOR
from test_weekly_dashboard import make

COLUMNS = 16


def boards(sample):
    snap = sample["snapshot"]
    for kind in ("weekly", "monthly"):
        for activity in ("Receiving", "Withdrawal"):
            summary = (an.weekly_summary if kind == "weekly" else
                       an.monthly_summary)(snap.transactions, activity,
                                           ANCHOR)
            yield kind, activity, dash.build(summary, kind)


def sheets(sample):
    for kind, activity, board in boards(sample):
        wb = Workbook()
        yield f"{kind} {activity}", ex.write_dashboard(wb, board)
    yield "interactive", make()["Dashboard"]


def box(chart):
    """(first column, first row, last column, last row) a chart covers,
    0-based."""
    a = chart.anchor
    return (a._from.col, a._from.row, a.to.col, a.to.row)


def test_every_chart_is_pinned_to_cells_inside_the_sheet(sample):
    for name, ws in sheets(sample):
        assert ws._charts, name
        for chart in ws._charts:
            anchor = chart.anchor
            assert isinstance(anchor, TwoCellAnchor), name
            first, _, last, _ = box(chart)
            assert 0 <= first <= last < COLUMNS, name
            # clear of the right edge, inside the last column
            assert anchor.to.colOff < chart_style.COLUMN_PIXELS * \
                chart_style.EMU_PER_PIXEL, name


def test_charts_side_by_side_keep_a_gap_and_never_overlap(sample):
    for name, ws in sheets(sample):
        rows = {}
        for chart in ws._charts:
            rows.setdefault(chart.anchor._from.row, []).append(chart)
        for charts in rows.values():
            if len(charts) == 1:
                continue
            left, right = sorted(charts, key=lambda c: c.anchor._from.col)
            assert left.anchor._from.col == 0 and left.anchor.to.col == 7
            assert right.anchor._from.col == 8 and right.anchor._from.colOff > 0
        ordered = sorted(ws._charts, key=lambda c: c.anchor._from.row)
        for upper, lower in zip(ordered, ordered[1:]):
            if upper.anchor._from.row != lower.anchor._from.row:
                assert upper.anchor.to.row < lower.anchor._from.row, name


def test_titles_and_legends_do_not_lie_on_the_chart(sample):
    for name, ws in sheets(sample):
        for chart in ws._charts:
            assert chart.title.overlay is False, name
            assert chart.title.tx.rich.p[0].r[0].rPr.sz == \
                chart_style.TITLE_SIZE
            assert chart.roundedCorners is False
            if chart.legend is not None:
                assert chart.legend.overlay is False
                assert chart.legend.position == "b", name


def test_a_month_of_days_is_labelled_with_day_numbers(sample):
    for kind, _, board in boards(sample):
        if kind != "monthly":
            continue
        days = {c.title: c for c in board.charts}["Transactions per Day"]
        assert days.labels[:3] == ["1", "2", "3"]
    calc = make()["Calc"]
    first_day = [calc.cell(row=r, column=1).value for r in range(1, 60)]
    assert "1" in first_day and "31" in first_day


def test_printed_pages_start_between_the_charts(sample):
    for name, ws in sheets(sample):
        starts = [brk.id + 1 for brk in ws.row_breaks.brk]
        assert starts, name
        chart_rows = [(c.anchor._from.row + 1, c.anchor.to.row + 1)
                      for c in ws._charts]
        for start in starts:
            assert not any(top < start <= bottom
                           for top, bottom in chart_rows), (name, start)


def test_card_texts_shrink_rather_than_run_past_their_card(sample):
    _, _, board = next(boards(sample))
    ws = ex.write_dashboard(Workbook(), board)
    assert ws["A6"].alignment.shrink_to_fit
    assert make()["Dashboard"]["A10"].alignment.shrink_to_fit


@pytest.mark.parametrize("side,first,last", [
    ("left", 0, 7), ("right", 8, 15), ("wide", 0, 15)])
def test_place_puts_a_chart_in_its_half(side, first, last):
    from openpyxl.chart import BarChart
    ws = Workbook().active
    where = chart_style.place(ws, BarChart(), 11, 18, side)
    assert (where._from.col, where.to.col) == (first, last)
    # rows 11..27 (0-based 10..26); row 28 is the gap to the next charts
    assert (where._from.row, where.to.row) == (10, 26)
