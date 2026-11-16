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


def test_a_draft_from_the_phone_app_is_continued_and_keeps_its_number(app):
    """A phone draft with every field: received while other work is on the
    form (which stays as it was), restored with the phone's Control #, and
    saved here as the same report the phone app itself would export."""
    import fsr_draft_form
    from pathlib import Path
    g, answers = app
    data = Path(__file__).resolve().parent / "data"
    number = "FSR-PHN-202611-0007"
    expected = json.loads((data / "android_rich_draft_windows_shape.json")
                          .read_text(encoding="utf-8"))

    g["new_report"](confirm=False)
    g["set_entry"](g["SO_number_entry"], "SO-MY-OWN-WORK")
    g["set_entry"](g["other_remarks_entries"][0], "My unsaved remark")
    g["window"].update()
    before = (fsr_draft_form.capture(g), dict(g["report_state"]),
              g["control_entry"].get())
    answers.calls.clear()
    result = g["receive_handover"](
        str(data / "handover_from_android_rich_draft.json"))
    shown = g["draft_controller"].dialog
    if shown is not None and shown.winfo_exists():
        shown.destroy()
    assert result["result"] == "draft"
    said = "\n".join(c[2] for c in answers.calls)
    assert f"unfinished report {number} (a draft from the phone app)" in said
    assert f"it keeps its Control # {number} when you save it" in said
    assert not [c for c in answers.calls if c[0] == "showerror"]
    # the work on the form is as it was
    assert (fsr_draft_form.capture(g), dict(g["report_state"]),
            g["control_entry"].get()) == before

    g["new_report"](confirm=False)
    (value,) = [v for v in g["draft_controller"].store.list()[0]
                if (v.get("received") or {}).get("control") == number]
    assert g["draft_controller"].restore(value)
    g["window"].update()
    assert g["control_entry"].get() == number
    assert g["SO_number_entry"].get() == "SO-PHONE-RICH"
    answers.calls.clear()
    assert g["save_report"]() is True, answers.calls
    path = g["excel_state"]["path"]
    saved = g["data_store"](path).read_report(number)
    # the form writes times its own way, as for any report saved here
    expected["inspection_schedule"].update(commenced_time="0830H",
                                           completion_time="1145H")
    expected["item_lists"][0]["rows"][0].update({"Unit Price": "10.00",
                                                 "Total Price": "40.00"})
    for key in ("cargo_condition", "item_form", "goods_types",
                "general_information", "inspection_schedule",
                "transport_details", "documents_used", "declared_goods",
                "other_important_remarks", "findings_and_remarks"):
        assert saved[key] == expected[key], key
    columns = ("Description of Goods", "Quantity", "UOM", "Weights",
               "Currency", "Unit Price", "Total Price", "Findings",
               "Container / Truck No.", "Dimensions", "Cargo ID",
               "Packaging")

    def lines(lists):
        return [[{c: str(row.get(c) or "") for c in columns}
                 for row in value["rows"]] for value in lists]
    assert lines(saved["item_lists"]) == lines(expected["item_lists"])
    assert saved["item_lists"][0]["rows"][0]["Receiving Ref"] == \
        f"RCV-{number}-1-01"
    others = g["data_store"](path).load_item_forms(number)
    assert lines(others["Default"]) == lines(
        expected["other_item_forms"]["Default"])
    incidents = saved["incident_reports"]
    assert [card["lines"] for card in incidents] == [
        card["lines"] for card in expected["incident_reports"]]
    assert incidents[0]["vessel"] == "MV Invented"
    # the phone's report: its id and next revision are recorded here
    entry = fsr_handover.status(path, number)
    assert entry["report_id"] == "uid-1" and entry["revision"] == 3
    # and the draft is gone from Unfinished work
    assert not [v for v in g["draft_controller"].store.list()[0]
                if (v.get("received") or {}).get("control") == number]


def test_a_phone_draft_without_any_item_list_is_continued(app, tmp_path):
    """A real phone draft had no item lists at all: restored, the form shows
    one empty Item List, and it saves with the phone's number."""
    from pathlib import Path
    g, answers = app
    data = Path(__file__).resolve().parent / "data"
    payload = fsr_handover.read_file(data / "handover_from_android_draft.json")
    payload["handover_id"] = "e" * 32
    phone = payload["draft"]["report"]
    number = "FSR-PHN-202611-0099"
    phone.update(controlNo=number, cargoCondition="", otherRemarks=[],
                 additionalDetails=[], soNumber="SO-NO-ITEM-LISTS",
                 itemLists={"Default": [], "Containerized": [],
                            "Loading": []})
    payload["draft"]["identity"]["report_id"] = "uid-empty-lists"
    file = tmp_path / "empty_lists.json"
    file.write_text(json.dumps(fsr_handover._envelope(payload)),
                    encoding="utf-8")

    g["new_report"](confirm=False)
    answers.calls.clear()
    assert g["receive_handover"](str(file))["result"] == "draft"
    shown = g["draft_controller"].dialog
    if shown is not None and shown.winfo_exists():
        shown.destroy()
    assert not [c for c in answers.calls if c[0] == "showerror"]
    (value,) = [v for v in g["draft_controller"].store.list()[0]
                if (v.get("received") or {}).get("control") == number]
    assert g["draft_controller"].restore(value)
    g["window"].update()
    assert g["control_entry"].get() == number
    assert len(g["item_frames"]) == 1
    # the phone left Cargo Condition empty: SAVE asks for it first
    answers.calls.clear()
    assert g["save_report"]() is False
    assert answers.calls[0][1] == "Cargo Condition"
    g["choose_condition"]("Good Order")
    assert g["save_report"]() is True
    path = g["excel_state"]["path"]
    saved = g["data_store"](path).read_report(number)
    assert saved["general_information"]["so_number"] == "SO-NO-ITEM-LISTS"
    assert fsr_handover.status(path, number)["report_id"] == \
        "uid-empty-lists"
