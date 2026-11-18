"""One-click Findings (fsr_findings_ui) in the real program window: every
line Good Order and Complete, or the lines with an issue get their own
findings and the rest Good Order and Complete. Invented data only."""
import pytest

import fsr_findings_ui as fu
import fsr_shipment as sh
from test_shipment_import_gui import shipment_file


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_home_findings")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    yield g, answers
    h.stop_app(g, answers)


def findings(g):
    return [box.get() for *_, box in fu.item_lines(g)]


def packing_lists(g):
    return [w.hidden.get("Packing List No.", "")
            for _, _, _, w, _ in fu.item_lines(g)]


def imported(g, tmp_path, control):
    """A Receiving draft made from a shipment file, open on the form."""
    g["new_report"](confirm=False)
    g["settings"][sh.SETTING] = "NORTH PLANT"
    path, _ = shipment_file(tmp_path, control)
    assert g["fsr_shipment_ui"].receive_file(g, str(path)) is not None
    return path


def test_all_good_fills_every_line(app, tmp_path):
    g, answers = app
    imported(g, tmp_path, "FSR-ORG-202611-0301")
    assert findings(g) == ["", "", "", ""]
    before = packing_lists(g)
    assert fu.accept_all(g) == 4
    assert findings(g) == [fu.GOOD] * 4
    assert packing_lists(g) == before          # the hidden numbers stay
    assert g["report_state"]["dirty"]


def test_other_findings_are_replaced_only_when_asked(app, tmp_path):
    g, answers = app
    imported(g, tmp_path, "FSR-ORG-202611-0302")
    lines = fu.item_lines(g)
    g["set_entry"](lines[1][4], "1 crate dented")
    answers.yes = False                        # "No": only the empty lines
    try:
        assert fu.accept_all(g) == 3
    finally:
        answers.yes = True
    assert findings(g) == [fu.GOOD, "1 crate dented", fu.GOOD, fu.GOOD]
    assert fu.accept_all(g) == 4               # "Yes": every line
    assert findings(g) == [fu.GOOD] * 4


def test_with_issues_fills_the_rest(app, tmp_path):
    g, answers = app
    imported(g, tmp_path, "FSR-ORG-202611-0303")
    dialog = fu.with_issues(g)
    flag, text, _ = dialog.rows[2]
    flag.set(True)
    text.set("2 pcs short; carton wet")
    dialog.apply()
    assert findings(g) == [fu.GOOD, fu.GOOD, "2 pcs short; carton wet",
                           fu.GOOD]
    # opened again: the issue is ticked with its text, the rest unticked
    dialog = fu.with_issues(g)
    assert [f.get() for f, _, _ in dialog.rows] == [False, False, True,
                                                     False]
    assert dialog.rows[2][1].get() == "2 pcs short; carton wet"
    dialog.destroy()


def test_a_ticked_line_needs_its_findings(app, tmp_path):
    g, answers = app
    imported(g, tmp_path, "FSR-ORG-202611-0304")
    dialog = fu.with_issues(g)
    dialog.rows[0][0].set(True)                # ticked, nothing typed
    answers.calls.clear()
    dialog.apply()
    assert [c for c in answers.calls if c[0] == "showwarning"]
    assert findings(g) == ["", "", "", ""]     # nothing written
    dialog.destroy()


def test_saved_with_the_findings_and_the_packing_lists(app, tmp_path):
    import fsr_storage
    g, answers = app
    imported(g, tmp_path, "FSR-ORG-202611-0305")
    dialog = fu.with_issues(g)
    dialog.rows[1][0].set(True)
    dialog.rows[1][1].set("1 crate dented")
    dialog.apply()
    g["choose_condition"]("Good Order")
    g["SO_number_entry"].insert(0, "SO-FINDINGS-1")
    g["set_inspection_date"]("18-Nov-2026")
    assert g["save_report"]() is True
    rows = fsr_storage.read_report(g["excel_state"]["path"],
                                   g["control_entry"].get())[
        "item_lists"][0]["rows"]
    assert [(r["Findings"], r.get("Packing List No.", "")) for r in rows] == [
        (fu.GOOD, "NOR111126-001 & 002"), ("1 crate dented", "NOR111126-003"),
        (fu.GOOD, "NOR111126-003"), (fu.GOOD, "")]


def test_no_lines_no_change(app):
    g, answers = app
    g["new_report"](confirm=False)
    answers.calls.clear()
    assert fu.accept_all(g) == 0
    assert fu.with_issues(g) is None
    assert [c for c in answers.calls if c[0] == "showinfo"]


# ---------- Phase 3: printing, reviewing, and saving only when verified -----

def test_the_printed_form_shows_packing_list_and_findings(app, tmp_path):
    from openpyxl import load_workbook
    g, answers = app
    imported(g, tmp_path, "FSR-ORG-202611-0306")
    dialog = fu.with_issues(g)
    dialog.rows[1][0].set(True)
    dialog.rows[1][1].set("1 crate dented")
    dialog.apply()
    g["choose_condition"]("Good Order")
    forms, notes, _ = g["create_report_forms"](g["excel_state"]["path"],
                                               g["collect_report_data"]())
    sheet = load_workbook(forms[0])["Cargo Details"]
    import fsr_forms
    first = fsr_forms.CARGO_FIRST_ROW
    assert [sheet[f"K{row}"].value for row in range(first, first + 4)] == [
        "NOR111126-001 & 002 · Good Order and Complete",
        "NOR111126-003 · 1 crate dented",
        "NOR111126-003 · Good Order and Complete",
        "Good Order and Complete"]                 # no Packing List: as before
    assert sheet[f"A{first}"].value == "Diaphragm"
    # a Packing List line longer than one line: two wrapped 9 pt lines;
    # the line without a Packing List shrinks to fit, as every cell did
    long_cell, plain = sheet[f"K{first}"], sheet[f"K{first + 3}"]
    assert long_cell.alignment.wrap_text and not long_cell.alignment.shrink_to_fit
    assert long_cell.font.sz == 9
    assert plain.alignment.shrink_to_fit and not plain.alignment.wrap_text


def test_an_ordinary_report_prints_its_findings_as_before():
    import fsr_storage
    assert fsr_storage.printed_findings({"Findings": "Dented"}) == "Dented"
    assert fsr_storage.printed_findings(
        {"Findings": "", "Packing List No.": "BAC111126-009"}) == \
        "BAC111126-009"
    assert fsr_storage.printed_findings(
        {"Findings": "Good Order and Complete",
         "Packing List No.": "BAC111126-009"}) == \
        "BAC111126-009 · Good Order and Complete"


def test_the_packing_lists_window_counts_the_findings(app, tmp_path):
    g, answers = app
    imported(g, tmp_path, "FSR-ORG-202611-0307")
    lines = fu.item_lines(g)
    g["set_entry"](lines[0][4], fu.GOOD)
    g["set_entry"](lines[1][4], "1 crate dented")
    found = {p["number"]: p for p in fu.packing_lists(g)}
    assert (found["NOR111126-003"]["po_numbers"],
            found["NOR111126-003"]["lines"], found["NOR111126-003"]["issues"],
            found["NOR111126-003"]["empty"]) == (["PO-100", "PO-200"], 2, 1, 1)
    assert found["NOR111126-001 & 002"]["good"] == 1
    dialog = fu.review_window(g)
    rows = [dialog.tree.item(i, "values") for i in dialog.tree.get_children()]
    assert rows[1] == ("NOR111126-003", "PO-100, PO-200", "2", "0", "1", "1")
    dialog.destroy()


def test_saving_asks_while_received_lines_have_no_findings(app, tmp_path):
    g, answers = app
    imported(g, tmp_path, "FSR-ORG-202611-0308")
    g["choose_condition"]("Good Order")
    g["SO_number_entry"].insert(0, "SO-VERIFY-1")
    g["set_inspection_date"]("18-Nov-2026")
    answers.calls.clear()
    answers.yes = False                    # "Save anyway?" - No
    try:
        assert g["save_report"]() is False
    finally:
        answers.yes = True
    asked = [c for c in answers.calls if c[0] == "askyesno"]
    assert asked and "4 line(s) received from the shipment have no Findings" \
        in asked[0][2]
    assert g["report_state"]["dirty"]      # nothing saved
    fu.accept_all(g)                       # verified: no question
    answers.calls.clear()
    assert g["save_report"]() is True
    assert not [c for c in answers.calls
                if c[0] == "askyesno" and "Verification" in str(c[1])]


def test_an_ordinary_report_is_saved_without_the_question(app):
    g, answers = app
    g["new_report"](confirm=False)
    assert not fu.from_shipment(g)
    assert fu.verified_before_save(g) is True
