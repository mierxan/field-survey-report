"""A long Description prints as the Findings of a shipment line: one line
in the form's font when it fits, two wrapped 9 pt lines when it fits two,
and only a still longer one shrinks to fit (as every cell did) - with a
warning. The Item List Descriptions (every Item List form) and the
Declared Goods Descriptions of the First Page. Invented data only."""
from datetime import date

import pytest
from openpyxl import load_workbook

import fsr_forms as forms
import fsr_print_fit as fit
from factories import report

ONE_LINE = "Digital Pressure gauge 0 to 200 psi"
TWO_LINES = ("Digital Pressure gauge -30 to 300 psi Digital Pressure gauge "
             "-30 to 300 psi")
TOO_LONG = TWO_LINES + " " + TWO_LINES
FIRST = forms.CARGO_FIRST_ROW


# ---------- measuring ----------

def test_the_three_layouts_of_the_item_list_description():
    assert forms.description_fit(ONE_LINE) == fit.ONE
    assert forms.description_fit(TWO_LINES) == fit.TWO
    assert forms.description_fit(TOO_LONG) == fit.LONG
    assert forms.description_fit("") == fit.ONE
    # a little too long for one line: one line shrunk (10-11 pt) reads
    # better than two 9 pt lines
    for slightly in ("Webbing Nylon Sling Anchor Strap 150 cm",
                     "DT902 Proximity Probe Field Calibrator"):
        assert forms.description_fit(slightly) == fit.ONE
    for form in (forms.ITEM_FORM_CONTAINERIZED, forms.ITEM_FORM_LOADING):
        assert forms.description_fit(TWO_LINES, form) == fit.TWO
        assert forms.description_fit(TOO_LONG, form) == fit.LONG


def test_the_findings_cell_measures_as_its_two_line_rule():
    """The measure agrees with the Findings rule already printed (K: about
    23 letters on one line, 56 on two)."""
    findings = forms.column_widths(
        load_cargo_xml(), "K")
    sample = "BAC111126-008 · Good Order and Complete"
    assert fit.layout(sample, findings, 12) == fit.TWO
    assert fit.wrapped_lines(sample, fit.cell_points(findings), 9) == [
        "BAC111126-008 · Good Order and", "Complete"]


def test_wide_letters_and_unknown_letters_count_as_wider():
    widths = (20,)
    assert fit.text_points("W" * 10, 11) > fit.text_points("i" * 10, 11)
    # a letter outside the table is never measured narrower than it is
    assert fit.text_points("漢", 11) >= fit.text_points("W", 11)
    assert fit.layout("漢" * 60, widths, 11) == fit.LONG


def test_a_word_longer_than_a_line_is_cut():
    lines = fit.wrapped_lines("X" * 200, 50, 9)
    assert "".join(lines) == "X" * 200 and len(lines) > 2


def load_cargo_xml():
    import zipfile
    with zipfile.ZipFile(forms.CARGO_TEMPLATE) as source:
        xml, _, _ = forms.locate_template_sheet(source, "WarehouseReceiving")
    return xml


# ---------- the printed forms ----------

def item_report(form=forms.ITEM_FORM_DEFAULT):
    value = report("FSR-TST-202611-0901", "Receiving", date(2026, 11, 19),
                   lines=[{"qty": 1, "desc": ONE_LINE},
                          {"qty": 2, "desc": TWO_LINES},
                          {"qty": 3, "desc": TOO_LONG}])
    value["item_form"] = form
    value["declared_goods"] = [
        {"description": d, "quantity": "1", "packaging": "Box"}
        for d in ("Valves", TWO_LINES + " " + TWO_LINES[:20],
                  TOO_LONG + " " + TOO_LONG)]
    return value


@pytest.mark.parametrize("form, column", [
    (forms.ITEM_FORM_DEFAULT, "A"),
    (forms.ITEM_FORM_CONTAINERIZED, "B"),
    (forms.ITEM_FORM_LOADING, "B"),
])
def test_the_cargo_details_description_prints_on_two_lines(tmp_path, form,
                                                           column):
    data = item_report(form)
    path, pages = forms.create_cargo_form(tmp_path / "book.xlsx", data,
                                          tmp_path)
    sheet = load_workbook(path).worksheets[0]
    short, two, long_ = (sheet[f"{column}{FIRST + i}"] for i in range(3))
    assert [c.value for c in (short, two, long_)] == [ONE_LINE, TWO_LINES,
                                                      TOO_LONG]
    # fits one line: as before (shrinks only if it must), its own font
    assert short.alignment.shrink_to_fit and not short.alignment.wrap_text
    assert short.font.sz != 9
    # two wrapped 9 pt lines, as the Findings of a shipment line
    assert two.alignment.wrap_text and not two.alignment.shrink_to_fit
    assert two.font.sz == 9
    # still longer: one shrunken line (nothing cut off), and reported
    assert long_.alignment.shrink_to_fit and not long_.alignment.wrap_text
    rows = data["item_lists"][0]["rows"]
    assert len(pages["too_long"]) == 1 and pages["too_long"][0] is rows[2]
    assert forms.too_long_notes(data["item_lists"], pages["too_long"]) == [
        forms.too_long_note("Item List 1, line 3")]


def test_the_first_page_declared_goods_description(tmp_path):
    data = item_report()
    path, notes = forms.create_report_form(tmp_path / "book.xlsx", data,
                                           tmp_path)
    sheet = load_workbook(path).worksheets[0]
    one, two, long_ = (sheet[f"A{forms.GOODS_FIRST_ROW + i}"]
                       for i in range(3))
    assert one.value == "Valves" and one.alignment.shrink_to_fit
    assert two.alignment.wrap_text and two.font.sz == 9
    assert long_.alignment.shrink_to_fit and not long_.alignment.wrap_text
    assert forms.too_long_note("Declared Goods line 3") in notes
    assert not any("Declared Goods line 2" in n for n in notes)
    # the Quantity and Packaging cells are untouched
    assert sheet[f"D{forms.GOODS_FIRST_ROW + 1}"].value == "1"


def test_an_ordinary_report_prints_as_before(tmp_path):
    """Short Descriptions: the same cells and styles as before."""
    data = report("FSR-TST-202611-0902", "Receiving", date(2026, 11, 19),
                  lines=[{"qty": 1, "desc": "Valve"}])
    path, pages = forms.create_cargo_form(tmp_path / "book.xlsx", data,
                                          tmp_path)
    cell = load_workbook(path).worksheets[0][f"A{FIRST}"]
    assert cell.value == "Valve" and cell.alignment.shrink_to_fit
    assert pages["too_long"] == []


# ---------- the warning in the program window ----------

@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_home_description")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    yield g, answers
    h.stop_app(g, answers)


def type_description(g, section, line, text):
    widgets = section.rows[line]
    g["set_entry"](section.cell(widgets, "Description of Goods"), text)
    section.row_changed(widgets, "Description of Goods")


@pytest.mark.gui
def test_the_item_list_warns_while_typing(app):
    g, answers = app
    g["new_report"](confirm=False)
    section = g["item_frames"][0]
    warning = section.description_warning
    type_description(g, section, 0, TWO_LINES)
    assert warning.cget("text") == "" and not warning.winfo_ismapped()
    type_description(g, section, 2, TOO_LONG)
    g["window"].update_idletasks()
    assert warning.cget("text").startswith("Line 3: the Description is too "
                                           "long for two printed lines")
    type_description(g, section, 0, TOO_LONG)
    assert warning.cget("text").startswith("Lines 1, 3: the Descriptions")
    type_description(g, section, 0, "Valve")
    type_description(g, section, 2, "Pump")
    assert warning.cget("text") == ""


@pytest.mark.gui
def test_a_loaded_report_is_checked_and_a_new_one_clears(app):
    g, answers = app
    g["new_report"](confirm=False)
    section = g["item_frames"][0]
    section.set_values([{"Description of Goods": "Pump"},
                        {"Description of Goods": TOO_LONG}])
    assert section.too_long_lines() == [2]
    assert section.description_warning.cget("text").startswith("Line 2:")
    g["new_report"](confirm=False)
    assert g["item_frames"][0].description_warning.cget("text") == ""


@pytest.mark.gui
def test_print_tells_which_line_prints_smaller(app):
    g, answers = app
    g["new_report"](confirm=False)
    section = g["item_frames"][0]
    type_description(g, section, 0, "Valve")
    type_description(g, section, 1, TOO_LONG)
    g["choose_condition"]("Good Order")
    forms_made, notes, _ = g["create_report_forms"](
        g["excel_state"]["path"], g["collect_report_data"]())
    assert forms.too_long_note("Item List 1, line 2") in notes
    sheet = load_workbook(forms_made[0])["Cargo Details"]
    assert sheet[f"A{FIRST + 1}"].value == TOO_LONG
