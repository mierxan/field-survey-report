"""The Weekly Summary and its Excel export, in the real program (MySQL off).

The exported file is opened again and compared cell by cell with a fixed
expected table: values, the Date as a real date, prices as numbers with the
currency in the number format, one TOTAL per currency, the header row and
the page set-up. Reports are invented and written to the test folder."""
from datetime import date, datetime

import pytest
from openpyxl import load_workbook

import fsr_storage
from factories import report

pytestmark = pytest.mark.gui

WEEK = (2031, 3, 2)                      # March 2031, Week 2 = 8-14 March


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_weekly_home")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    yield g, answers
    h.stop_app(g, answers)


def live(g):
    return g["save_report"].__globals__


def line(desc, qty, uom, currency="", unit="", total="", po="",
         packaging="Box", dimensions="", weights=""):
    row = {h: "" for h in fsr_storage.ITEM_LINE_HEADERS}
    row.update({"Description of Goods": desc, "Quantity": qty, "UOM": uom,
                "Currency": currency, "Unit Price": unit,
                "Total Price": total, "PO Number": po,
                "Packaging": packaging, "Dimensions": dimensions,
                "Weights": weights})
    return row


def invented(control, day, so, lines, condition="Good Order",
             activity="Receiving"):
    data = report(control, activity, day, "WH-W", so=so,
                  supplier="Supplier W", condition=condition)
    info = data["general_information"]
    info.update(brokerage="Broker W", hauler="Hauler W",
                destination="Plant 3", country_of_origin="Japan")
    data["documents_used"].update(invoice_number=f"INV-{so}",
                                  po_number="PO-HEAD", jo_number="JO-1",
                                  gatepass_number="GP-1",
                                  bl_awb_number="BL-1", dr_number="DR-1")
    data["transport_details"].update(shipment_type="Import",
                                     vehicle_type="Truck",
                                     vehicle_plate_number="ABC 123")
    data["item_lists"][0]["rows"] = lines
    return data


@pytest.fixture(scope="module")
def week_reports(app):
    """Three reports inside the week (one has no item lines), one the day
    after it and one the day before it."""
    g, _ = app
    store = live(g)["data_store"]()
    items = [
        (invented("FSR-W-0002", date(2031, 3, 9), "SO-W2", [
            line("Valve", "6", "pcs", "jpy", "460000", "2760000", "PO-7"),
            line("Gasket", "1,250.50", "Kg", "usd", "2", "2501", "PO-8",
                 dimensions="10x10", weights="1250")]), False, None),
        (invented("FSR-W-0001", date(2031, 3, 8), "SO-W1", [
            line("Pump", "2", "units", "usd", "1,000", "2000", "PO-1")]),
         False, None),
        (invented("FSR-W-0003", date(2031, 3, 14), "SO-W3", [],
                  condition="Bad Order", activity="Withdrawal"), False, None),
        (invented("FSR-W-0004", date(2031, 3, 15), "SO-OUT-AFTER", [
            line("Late", "1", "pcs", "usd", "5", "5")]), False, None),
        (invented("FSR-W-0005", date(2031, 3, 7), "SO-OUT-BEFORE", [
            line("Early", "1", "pcs", "usd", "5", "5")]), False, None),
    ]
    store.write_reports(items)
    return g


HEAD = ["Import", "Supplier W", "Broker W", "Hauler W", "Plant 3", "Japan"]
DOCS = ["PO-HEAD", "JO-1", "GP-1", "BL-1", "DR-1", "Truck", "ABC 123"]

# The exported sheet, row by row (row 1 = headings), as openpyxl reads it.
EXPECTED_ROWS = [
    ["SO-W1", datetime(2031, 3, 8), "Receiving", *HEAD, "INV-SO-W1", *DOCS,
     "Pump", "PO-1", "Box", "2 units", None, None, 1000, 2000, "Good Order"],
    ["SO-W2", datetime(2031, 3, 9), "Receiving", *HEAD, "INV-SO-W2", *DOCS,
     "Valve", "PO-7", "Box", "6 pcs", None, None, 460000, 2760000,
     "Good Order"],
    ["SO-W2", datetime(2031, 3, 9), "Receiving", *HEAD, "INV-SO-W2", *DOCS,
     # A Quantity is shown as it was typed ("1,250.50"); the workbook
     # keeps the number with a display format (tests/test_typed_quantities).
     "Gasket", "PO-8", "Box", "1,250.50 Kg", "10x10", "1250", 2, 2501,
     "Good Order"],
    ["SO-W3", datetime(2031, 3, 14), "Withdrawal", *HEAD, "INV-SO-W3", *DOCS,
     None, None, None, None, None, None, None, None, "Bad Order"],
]
EXPECTED_FORMATS = {               # (row, heading) -> number format
    (2, "Date"): "dd-mmm-yyyy",
    (2, "Unit Price"): '"usd "#,##0.00', (2, "Total Price"): '"usd "#,##0.00',
    (3, "Unit Price"): '"jpy "#,##0.00', (3, "Total Price"): '"jpy "#,##0.00',
    (4, "Total Price"): '"usd "#,##0.00',
}


def test_the_week_has_the_right_lines_in_date_order(week_reports):
    g = week_reports
    rows = g["weekly_rows"](*WEEK, "excel")
    assert [(r[0], r[17]) for r in rows] == [
        ("SO-W1", "Pump"), ("SO-W2", "Valve"), ("SO-W2", "Gasket"),
        ("SO-W3", "")]
    assert all(len(r) == 28 for r in rows)
    # A Quantity saved with its unit in it is split.
    assert g["weekly_display"](rows[0])[20] == "2 units"
    assert g["weekly_display"](rows[1])[23:25] == ["jpy 460,000.00",
                                                   "jpy 2,760,000.00"]


def test_the_titles_and_a_month_without_week_5(app):
    g, _ = app
    assert g["weekly_title"](*WEEK) == \
        "Weekly Summary Report - March 2031, Week 2 (8-14 March)"
    assert g["weekly_title"](2031, 3, 0) == \
        "Weekly Summary Report - March 2031 (whole month)"
    assert g["week_span"](2031, 3, 5) == (29, 31)
    assert g["week_span"](2027, 2, 5) is None           # 28 days
    assert g["weekly_rows"](2027, 2, 5, "excel") == []
    assert g["weekly_title"](2027, 2, 5) == \
        "Weekly Summary Report - February 2027 (whole month)"


def test_the_whole_month_takes_every_report_of_it(week_reports):
    g = week_reports
    sos = [r[0] for r in g["weekly_rows"](2031, 3, 0, "excel")]
    assert sos == ["SO-OUT-BEFORE", "SO-W1", "SO-W2", "SO-W2", "SO-W3",
                   "SO-OUT-AFTER"]


def test_the_exported_file_matches_the_expected_sheet(week_reports,
                                                      tmp_path):
    g = week_reports
    rows = g["weekly_rows"](*WEEK, "excel")
    path = tmp_path / "week.xlsx"
    g["write_weekly_workbook"](path, g["weekly_title"](*WEEK), rows)

    book = load_workbook(path)
    assert book.sheetnames == ["Weekly Summary"]
    ws = book["Weekly Summary"]
    headings = [h for h, _ in g["WEEKLY_COLUMNS"]]
    assert len(headings) == 26

    # the heading row
    assert [c.value for c in ws[1]] == headings
    for cell in ws[1]:
        assert cell.font.bold and cell.font.color.rgb == "00FFFFFF"
        assert cell.fill.fgColor.rgb == "002E75B6"
    assert ws.column_dimensions["A"].width == 120 // 7
    assert ws.column_dimensions["R"].width == 230 // 7   # Description
    assert ws.column_dimensions["O"].width == 12         # DR: 85 // 7 = 12

    # the lines, cell by cell
    body = [[c.value for c in row] for row in ws.iter_rows(min_row=2,
                                                           max_row=5)]
    assert body == EXPECTED_ROWS
    for (row, heading), wanted in EXPECTED_FORMATS.items():
        cell = ws.cell(row=row, column=headings.index(heading) + 1)
        assert cell.number_format == wanted, (row, heading)
    # amounts are numbers (Excel can add them up), not text
    assert isinstance(ws["Y3"].value, int)

    # one TOTAL per currency, never added across currencies
    totals = [[c.value for c in row][22:25]
              for row in ws.iter_rows(min_row=6, max_row=ws.max_row)]
    assert totals == [[None, "TOTAL JPY", 2760000],
                      [None, "TOTAL USD", 2000 + 2501]]
    assert ws["Y6"].number_format == '"jpy "#,##0.00'
    assert ws["Y7"].number_format == '"usd "#,##0.00'
    assert ws["X6"].font.bold and ws["Y7"].font.bold
    assert ws.max_row == 7

    # filter over the lines, header frozen, printed landscape on one width
    assert ws.auto_filter.ref == "A1:Z5"
    assert ws.freeze_panes == "B2"
    assert ws.oddHeader.center.text == \
        "Weekly Summary Report - March 2031, Week 2 (8-14 March)"
    assert ws.page_setup.orientation == "landscape"
    assert ws.page_setup.fitToWidth == 1 and ws.page_setup.fitToHeight == 0
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True
    assert ws.print_title_rows == "$1:$1"     # the heading row on every page


def test_an_amount_that_is_not_a_number_stays_as_text(app, tmp_path):
    g, _ = app
    data = invented("FSR-W-TXT", date(2031, 3, 9), "SO-TXT", [
        line("Odd", "3", "pcs", "eur", "n/a", "about 10")])
    rows = g["report_to_weekly_rows"](data)
    path = tmp_path / "text.xlsx"
    g["write_weekly_workbook"](path, "t", rows)
    ws = load_workbook(path)["Weekly Summary"]
    assert ws["X2"].value == "eur n/a" and ws["Y2"].value == "eur about 10"
    assert ws.max_row == 2                  # no TOTAL: nothing to add up


def test_an_empty_period_exports_only_the_headings(app, tmp_path):
    g, _ = app
    path = tmp_path / "empty.xlsx"
    g["write_weekly_workbook"](path, "t", [])
    ws = load_workbook(path)["Weekly Summary"]
    assert ws.max_row == 1 and ws.auto_filter.ref is None


def _choose(g, year, month, week):
    w = live(g)
    w["source_var_weekly"].set("excel")
    w["year_var"].set(str(year))
    w["month_var"].set(w["MONTH_LIST"][month - 1])
    w["choose_week"](week)


def test_the_page_shows_the_lines_and_exports_them(week_reports, tmp_path,
                                                   monkeypatch):
    g = week_reports
    w = live(g)
    _choose(g, *WEEK)
    assert w["summary_note"].cget("text") == "4 line(s) from 3 report(s)"
    shown = [w["summary_tree"].item(i, "values")
             for i in w["summary_tree"].get_children()]
    assert [v[0] for v in shown] == ["SO-W1", "SO-W2", "SO-W2", "SO-W3"]
    assert "08-Mar-2031 to 14-Mar-2031" in w["range_label"].cget("text")

    target = tmp_path / "chosen.xlsx"
    offered = {}

    def ask(**kw):
        offered.update(kw)
        return str(target)
    monkeypatch.setattr(w["filedialog"], "asksaveasfilename", ask)
    notes = []
    monkeypatch.setitem(w, "notify", notes.append)
    w["export_weekly_summary"]()
    assert offered["initialfile"] == "Weekly Summary March 2031 Week 2.xlsx"
    assert notes == ["Exported 4 line(s) to chosen.xlsx"]
    # the interactive Dashboard comes first; the table is as before
    book = load_workbook(target)
    assert book.sheetnames == ["Dashboard", "Weekly Summary", "Data", "Calc"]
    assert book["Dashboard"]["E6"].value == "Week 2 (8-14)"
    data = [r for r in book["Data"].iter_rows(min_row=2, values_only=True)]
    assert [(r[0], r[10]) for r in data] == [
        ("FSR-W-0001", 1), ("FSR-W-0002", 1), ("FSR-W-0002", 0),
        ("FSR-W-0003", 1)]
    ws = book["Weekly Summary"]
    assert [[c.value for c in r] for r in ws.iter_rows(min_row=2,
                                                       max_row=5)] == \
        EXPECTED_ROWS


def test_export_with_nothing_shown_says_so(app):
    g, answers = app
    w = live(g)
    _choose(g, 2027, 2, 5)                       # no Week 5 in Feb 2027
    assert "has no Week 5" in w["range_label"].cget("text")
    assert w["summary_note"].cget("text") == "No reports in this period."
    answers.calls.clear()
    w["export_weekly_summary"]()
    assert answers.calls == [("showinfo", "Weekly Summary",
                              "There is nothing to export for this period.")]


def test_export_to_a_file_open_in_excel_says_close_it(week_reports, tmp_path,
                                                      monkeypatch):
    g = week_reports
    w = live(g)
    _choose(g, *WEEK)
    monkeypatch.setattr(w["filedialog"], "asksaveasfilename",
                        lambda **kw: str(tmp_path / "busy.xlsx"))

    def in_use(*a, **k):
        raise PermissionError("in use")
    monkeypatch.setitem(w, "write_weekly_workbook", in_use)
    import tkinter.messagebox as mb
    seen = []
    monkeypatch.setattr(mb, "showerror",
                        lambda title, message, **k: seen.append(title))
    w["export_weekly_summary"]()
    assert seen == ["File In Use"]


def test_a_read_failure_shows_on_the_page_not_as_a_crash(app, monkeypatch):
    g, _ = app
    w = live(g)

    def fails(*a, **k):
        raise PermissionError("locked")
    monkeypatch.setitem(w, "weekly_rows", fails)
    _choose(g, *WEEK)
    assert w["summary_note"].cget("text") == \
        "The Excel file is open in Excel - close it."
    assert w["weekly_state"]["rows"] == []


def test_the_mysql_source_asks_the_database_for_the_same_days(app,
                                                              monkeypatch):
    g, _ = app
    w = live(g)
    asked = []

    def summary(first, last, with_control=False):
        asked.append((first, last))
        return []
    monkeypatch.setattr(w["db_mysql"], "weekly_summary", summary)
    assert g["weekly_rows"](*WEEK, "mysql") == []
    assert g["weekly_rows"](2031, 3, 5, "mysql") == []
    assert asked == [(date(2031, 3, 8), date(2031, 3, 14)),
                     (date(2031, 3, 29), date(2031, 3, 31))]
