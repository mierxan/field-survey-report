"""Hand Over and Receive Hand-over in the real program window (see
gui_harness.py). Everything happens in a temporary FSR_HOME folder with
invented reports."""
import json
from datetime import date
from tkinter import messagebox

import pytest

import fsr_handover
import fsr_storage
import fsr_store
from factories import report


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_home_handover")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    yield g, answers
    h.stop_app(g, answers)


def invented(control, so="SO-GUI-HANDOVER"):
    value = report(control, "Receiving", date(2099, 1, 5), "GUI Yard",
                   [{"qty": 2, "unit": "Crate", "desc": "Invented crate",
                     "ref": f"RCV-{control}-1-01"}], so=so)
    value["other_important_remarks"] = ["Invented remark"]
    return value


def widgets(widget, kind):
    for child in widget.winfo_children():
        if child.winfo_class() == kind:
            yield child
        yield from widgets(child, kind)


def press(dialog, text):
    (button,) = [b for b in widgets(dialog, "TButton")
                 if b.cget("text") == text]
    button.invoke()


def fill_in(dialog, to):
    search, to_entry, _note = list(widgets(dialog, "TEntry"))
    to_entry.insert(0, to)


def selected_row(dialog):
    (tree,) = list(widgets(dialog, "Treeview"))
    (iid,) = tree.selection()
    return tree.item(iid, "values")


def test_a_saved_report_is_handed_over_and_locked(app, tmp_path,
                                                  monkeypatch):
    g, answers = app
    path = g["excel_state"]["path"]
    number = "FSR-TST-209901-0500"
    g["data_store"](path).write_report(invented(number), False)
    g["load_report_into_form"](number)
    target = tmp_path / "handover.json"
    monkeypatch.setattr(g["filedialog"], "asksaveasfilename",
                        lambda **_: str(target))

    dialog = g["open_hand_over"]()
    assert selected_row(dialog)[:2] == ("Report", number)
    fill_in(dialog, "Next Inspector")
    answers.calls.clear()
    press(dialog, "Hand Over...")
    g["window"].update()
    assert not [c for c in answers.calls if c[0] == "showerror"]
    assert fsr_handover.read_file(target)["report"]["control_no"] == number
    assert fsr_handover.handed_over(path, number)["to"] == "Next Inspector"
    assert selected_row(dialog)[4].startswith("Handed over to Next Inspector")
    dialog.destroy()

    g["load_report_into_form"](number)
    g["set_entry"](g["SO_number_entry"], "SO-CHANGED-AFTER")
    answers.calls.clear()
    assert g["save_report"]() is False
    assert [c[1] for c in answers.calls] == ["Handed Over"]
    assert fsr_storage.read_report(path, number)["general_information"][
        "so_number"] == "SO-GUI-HANDOVER"

    # Cancel Hand-over: it can be saved here again
    g["new_report"](confirm=False)
    dialog = g["open_hand_over"]()
    (tree,) = list(widgets(dialog, "Treeview"))
    (iid,) = [i for i in tree.get_children()
              if tree.item(i, "values")[1] == number]
    tree.selection_set(iid)
    g["window"].update()
    press(dialog, "Cancel Hand-over")
    assert fsr_handover.handed_over(path, number) is None
    dialog.destroy()


def test_a_file_from_another_inspector_is_received(app, tmp_path):
    g, answers = app
    path = g["excel_state"]["path"]
    other = tmp_path / "other" / "Field_Survey_Reports.xlsx"
    other.parent.mkdir()
    number = "FSR-OTH-209901-0001"
    fsr_store.ExcelStore(other).write_report(invented(number, "SO-OTHER"),
                                             False)
    fsr_handover.hand_over_report(
        other, number, tmp_path / "in.json",
        {"inspector": "Other Inspector", "initials": "OTH",
         "device_id": "pc-other"}, to="Test User", note="Please finish")

    answers.calls.clear()
    result = g["receive_handover"](str(tmp_path / "in.json"))
    assert result["result"] == "added" and result["control"] == number
    asked = [c for c in answers.calls if c[0] == "askyesno"]
    assert "handed over by Other Inspector" in asked[0][2]
    assert "Note: Please finish" in asked[0][2]
    assert not [c for c in answers.calls if c[0] == "showerror"]
    assert fsr_storage.read_report(path, number)["general_information"][
        "so_number"] == "SO-OTHER"
    # the same file again changes nothing
    answers.calls.clear()
    assert g["receive_handover"](str(tmp_path / "in.json"))["result"] == \
        "unchanged"


def test_the_unsaved_form_is_handed_over_as_a_draft(app, tmp_path,
                                                    monkeypatch):
    g, answers = app
    g["new_report"](confirm=False)
    g["set_entry"](g["SO_number_entry"], "SO-DRAFT-GUI")
    g["window"].update()
    assert g["report_state"]["dirty"]
    target = tmp_path / "draft.json"
    monkeypatch.setattr(g["filedialog"], "asksaveasfilename",
                        lambda **_: str(target))
    # No = keep the changes as a draft and hand the draft over
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: False)

    dialog = g["open_hand_over"]()
    assert selected_row(dialog)[:2] == ("Draft", "New report")
    fill_in(dialog, "Draft Receiver")
    press(dialog, "Hand Over...")
    g["window"].update()
    payload = fsr_handover.read_file(target)
    assert payload["kind"] == "draft" and payload["report"] is None
    assert payload["draft"]["form"]["simple"]["SO_number_entry"] == \
        "SO-DRAFT-GUI"
    # the form is free again; the draft is kept, marked handed over
    assert not g["report_state"]["dirty"]
    assert g["SO_number_entry"].get() == ""
    kept = [v for v in g["draft_controller"].store.list()[0]
            if v.get("handed_over")]
    assert kept and kept[0]["handed_over"]["to"] == "Draft Receiver"
    dialog.destroy()
    assert json.loads(target.read_text(encoding="utf-8"))["format"] == \
        "fsr-handover"


def test_nothing_is_written_while_the_reports_move_into_the_database(
        app, tmp_path):
    g, answers = app
    g["db_move_state"]["running"] = True
    try:
        answers.calls.clear()
        assert g["receive_handover"](str(tmp_path / "any.json")) is None
        assert g["open_hand_over"]() is None
        assert [c[0] for c in answers.calls] == ["showinfo", "showinfo"]
        assert "being moved" in answers.calls[0][2]
    finally:
        g["db_move_state"]["running"] = False
