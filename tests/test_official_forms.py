"""The approved official forms OPSF-068 v4.0 (data/excel, as committed):
the real template files are used, so a later change of a template is
caught here.

* The official First Page has no Control # (owner's decision): nothing is
  written for it, no "Entry for ..." words are left, and nothing is said
  about it (no note, no log line).
* The footer of the official forms - the names, the date and
  "OPSF-068 v4.0" - is on every printed sheet, inside its print area,
  extra Cargo Details pages and the remarks page included.
"""
import logging
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook

pytestmark = pytest.mark.gui

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "data" / "excel"
FOOTER = ("Mierxan P. Rojo", "Jan Michael V. Siason", "OPSF-068 v4.0")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_forms_home")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    yield g, answers
    h.stop_app(g, answers)


def report_data(control="FSR-ZZP-209911-0042", lines=3, remarks=0,
                form="Default"):
    from factories import report
    data = report(control, "Receiving", date(2026, 11, 5), "Warehouse 1",
                  [{"qty": n + 1, "unit": "Box", "desc": f"Item {n + 1}",
                    "po": "4500001", "cargo": f"C-{n}"}
                   for n in range(lines)], so="SO-OFFICIAL-FORM")
    data["item_form"] = form
    data["other_item_forms"] = {}
    data["findings_and_remarks"] = [f"Finding {n + 1}"
                                    for n in range(remarks)]
    return data


def texts(ws, area_only=True):
    """Every text on the sheet (inside its print area)."""
    cells = ws.iter_rows()
    if area_only and ws.print_area:
        ref = str(ws.print_area).split("!")[-1].replace("$", "")
        cells = ws[ref]
    found = []
    for row in cells:
        for cell in row:
            if cell.value not in (None, ""):
                found.append(str(cell.value))
    return found


def test_the_official_first_page_template_has_no_control_number():
    ws = load_workbook(TEMPLATES / "First_Page.xlsx").active
    assert not [t for t in texts(ws, False) if "control" in t.lower()]


def test_first_page_gets_no_control_number_and_nothing_is_said(app,
                                                               caplog):
    g, answers = app
    data = report_data()
    path = g["excel_state"]["path"]
    caplog.set_level(logging.DEBUG, logger="fsr")
    answers.calls.clear()

    forms, notes, summary = g["create_report_forms"](path, data)

    first = load_workbook(forms[0])["First Page"]
    shown = texts(first, False)
    assert not [t for t in shown if data["control_no"] in t]
    assert not [t for t in shown if t.startswith("Entry for")]
    assert "SO-OFFICIAL-FORM" in shown          # the form is filled
    assert notes == []                          # no note about it
    assert answers.calls == []
    assert not [r for r in caplog.records
                if "placeholder" in r.getMessage().lower()
                or "control" in r.getMessage().lower()]
    # the file of the printed report still carries the number
    assert Path(forms[0]).name == f"{data['control_no']}_Report.xlsx"


@pytest.mark.parametrize("lines,remarks,form", [
    (3, 0, "Default"),
    (35, 0, "Default"),         # a second Cargo Details page
    (8, 40, "Default"),         # remarks continue on the blank form
    (4, 0, "Containerized"),
    (4, 0, "Loading"),
])
def test_footer_is_on_every_printed_sheet(app, lines, remarks, form):
    g, _ = app
    data = report_data(lines=lines, remarks=remarks, form=form)
    if form != "Default":                    # the form's own lines
        import fsr_storage
        for number, row in enumerate(data["item_lists"][0]["rows"], 1):
            row[fsr_storage.UNIT_NO_HEADER] = f"ABC {number}"
    forms, notes, summary = g["create_report_forms"](
        g["excel_state"]["path"], data)
    wb = load_workbook(forms[0])
    assert len(wb.sheetnames) >= 2              # First Page + cargo pages
    if lines > 30:
        assert len(wb.sheetnames) >= 3
    for ws in wb:
        shown = texts(ws)                       # inside the print area
        for words in FOOTER:
            assert words in shown, (ws.title, words)
