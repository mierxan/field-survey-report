"""The approved official forms OPSF-068 v4.0 (data/excel, as committed):
the real template files are used, so a later change of a template is
caught here.

* First Page: the Control # goes into A5 as before (its "Entry for Control
  number" placeholder), but the cell's number format ";;;" shows nothing -
  on screen, on paper, in the PDF. The number stays in the file only
  (formula bar, file name). Owner's decision, 13 November 2026.
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
HIDDEN = ";;;"                  # the number format that shows nothing


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


def test_the_official_first_page_has_a_hidden_control_number_cell():
    ws = load_workbook(TEMPLATES / "First_Page.xlsx").active
    assert ws["A5"].value == "Entry for Control number"
    assert ws["A5"].number_format == HIDDEN
    others = [c.coordinate for row in ws.iter_rows() for c in row
              if isinstance(c.value, str) and c.value.startswith("Entry for")
              and "control" in c.value.lower() and c.coordinate != "A5"]
    assert others == []


def test_first_page_holds_the_control_number_but_shows_nothing(app,
                                                               caplog):
    g, answers = app
    data = report_data()
    path = g["excel_state"]["path"]
    caplog.set_level(logging.DEBUG, logger="fsr")
    answers.calls.clear()

    forms, notes, summary = g["create_report_forms"](path, data)

    first = load_workbook(forms[0])["First Page"]
    assert first["A5"].value == data["control_no"]        # in the file
    assert first["A5"].number_format == HIDDEN            # shown: nothing
    shown = texts(first, False)
    assert not [t for t in shown if t.startswith("Entry for")]
    assert "SO-OFFICIAL-FORM" in shown
    assert notes == [] and answers.calls == []
    assert not [r for r in caplog.records
                if "placeholder" in r.getMessage().lower()]
    assert Path(forms[0]).name == f"{data['control_no']}_Report.xlsx"


def test_the_pdf_shows_no_control_number_and_the_whole_footer(app,
                                                              tmp_path):
    """Printed through Microsoft Excel (or LibreOffice), as the program
    does: the hidden Control # is not in the PDF's text, the footer is on
    every page."""
    from pypdf import PdfReader
    g, _ = app
    data = report_data(lines=35)            # First Page + 2 cargo pages
    forms, _, _ = g["create_report_forms"](g["excel_state"]["path"], data)
    pdf = tmp_path / "report.pdf"
    try:
        g["convert_form_to_pdf"](forms[0], pdf)
    except RuntimeError as error:
        pytest.skip(f"no Excel or LibreOffice on this PC to print: {error}")
    pages = PdfReader(str(pdf)).pages
    assert len(pages) == 3
    for page in pages:
        text = page.extract_text() or ""
        assert data["control_no"] not in text
        assert "Entry for" not in text
        for words in FOOTER:
            assert words in text, words


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
