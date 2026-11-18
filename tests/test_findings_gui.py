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
