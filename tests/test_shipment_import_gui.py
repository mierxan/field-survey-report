"""Receive Shipment in the real program window (see gui_harness.py): a
shipment file becomes a new Receiving draft, which is restored, verified and
saved. Everything happens in a temporary FSR_HOME folder with invented
reports; the workbook keeps the reports (FSR_NO_SQLITE=1, as the harness
runs), so its Item List sheet can be looked at directly."""
from datetime import date

import pytest
from openpyxl import load_workbook

import fsr_shipment as sh
import fsr_storage
from test_shipment import SENDER, withdrawal


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_home_shipment_import")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    yield g, answers
    h.stop_app(g, answers)


def shipment_file(folder, control, destination="NORTH PLANT",
                  numbers=("NOR111126-001 & 002", "NOR111126-003", "")):
    """A file as the origin's Share with Destination writes it."""
    payload = sh.build_payload(withdrawal(control), destination,
                               list(numbers), SENDER)
    target = folder / sh.file_name(control, destination, date(2026, 11, 18))
    fsr_storage.write_json_atomic(target, sh._envelope(payload))
    return target, payload


def errors(answers):
    return [c for c in answers.calls if c[0] == "showerror"]


def cell(section, row, header):
    return row[section.headers.index(header)].get()


def test_a_shipment_becomes_a_receiving_draft_that_is_saved(
        app, tmp_path):
    g, answers = app
    g["settings"][sh.SETTING] = "NORTH PLANT"
    path, payload = shipment_file(tmp_path, "FSR-ORG-202611-0101")
    answers.calls.clear()
    value = g["fsr_shipment_ui"].receive_file(g, str(path))
    assert value is not None and not errors(answers)
    # the summary was shown before anything was made
    asked = [c for c in answers.calls if c[0] == "askyesno"][0][2]
    assert "Shipment for NORTH PLANT" in asked
    assert "FSR-ORG-202611-0101" in asked and "NOR111126-003" in asked
    assert "(matches)" in asked
    # the draft is in the account's drafts, and recorded
    found, _ = g["draft_controller"].store.list()
    assert any(v["id"] == value["id"] and v.get("shipment") for v in found)
    entry = sh.load_ledger(g["excel_state"]["path"])["imports"][
        payload["transfer_id"]]
    assert entry["draft_id"] == value["id"]
    assert entry["origin_lines"] == sh.origin_lines(payload)

    # it was opened on the form: Item List filled, First Page empty
    assert g["schedule_entries"]["activity"].get() == "Receiving"
    assert g["SO_number_entry"].get() == ""
    assert g["get_inspection_date"]() == ""
    assert g["consignee_combobox"].get() == "" and \
        g["supplier_combobox"].get() == ""
    section = g["item_frames"][0]
    lines = [r for r in section.rows if section.line_values(r)]
    assert [cell(section, r, "Description of Goods") for r in lines] == [
        "Diaphragm", "Valve body", "Valve seat", "Spare kit"]
    assert [cell(section, r, "Findings") for r in lines] == ["", "", "", ""]
    assert [r.hidden.get("Packing List No.") for r in lines] == [
        "NOR111126-001 & 002", "NOR111126-003", "NOR111126-003", ""]
    assert lines[1].hidden["Origin Line"] == "FSR-ORG-202611-0101/1/2"
    # the prices came along (owner's decision, 18 November 2026)
    assert (cell(section, lines[0], "Currency"),
            cell(section, lines[0], "Unit Price"),
            cell(section, lines[0], "Total Price")) == (
        "PHP", "1,000.00", "1,000.00")

    # the destination verifies: Findings typed, First Page filled, saved
    lines[0][section.headers.index("Findings")].insert(
        0, "Good Order and Complete")
    lines[1][section.headers.index("Findings")].insert(0, "1 crate dented")
    g["choose_condition"]("Good Order")
    g["SO_number_entry"].insert(0, "SO-DEST-1")
    g["set_inspection_date"]("18-Nov-2026")
    answers.calls.clear()
    assert g["save_report"]() is True
    assert not errors(answers)
    control = g["control_entry"].get()
    saved = fsr_storage.read_report(g["excel_state"]["path"], control)
    rows = saved["item_lists"][0]["rows"]
    assert [(r["Findings"], r.get("Packing List No.", ""))
            for r in rows] == [
        ("Good Order and Complete", "NOR111126-001 & 002"),
        ("1 crate dented", "NOR111126-003"),
        ("", "NOR111126-003"), ("", "")]
    assert rows[3]["Origin Line"] == "FSR-ORG-202611-0101/1/4"
    assert "Packing List No." not in rows[3]     # nothing there: not carried
    # a fresh Receiving Ref of THIS report, not the origin's
    assert rows[0]["Receiving Ref"] == fsr_storage.default_receiving_ref(
        control, 1, 1)
    # the workbook's Item List sheet ends with the two new columns
    sheet = load_workbook(g["excel_state"]["path"])["Item List"]
    headers = [c.value for c in sheet[1]]
    assert headers[-2:] == ["Packing List No.", "Origin Line"]
    # the draft was retired by the save
    found, _ = g["draft_controller"].store.list()
    assert not any(v["id"] == value["id"] for v in found)


def test_the_same_shipment_is_not_imported_twice(app, tmp_path):
    g, answers = app
    g["settings"][sh.SETTING] = "NORTH PLANT"
    path, payload = shipment_file(tmp_path, "FSR-ORG-202611-0102",
                                  numbers=("SOU111126-001",))
    g["new_report"](confirm=False)
    first = g["fsr_shipment_ui"].receive_file(g, str(path))
    assert first is not None
    g["new_report"](confirm=False)
    # the same file again: refused, the draft exists
    answers.calls.clear()
    assert g["fsr_shipment_ui"].receive_file(g, str(path)) is None
    assert "imported before" in errors(answers)[0][2]
    # another file of the same lines (the origin made it twice): refused too
    again, _ = shipment_file(tmp_path, "FSR-ORG-202611-0102",
                             numbers=("SOU111126-001",))
    answers.calls.clear()
    assert g["fsr_shipment_ui"].receive_file(g, str(again)) is None
    assert "imported before" in errors(answers)[0][2]
    # the draft discarded by mistake: it may come in again
    g["draft_controller"].store.discard(first["id"])
    answers.calls.clear()
    assert g["fsr_shipment_ui"].receive_file(g, str(path)) is not None
    assert not errors(answers)


def test_lines_already_in_a_saved_report_are_refused(app, tmp_path):
    g, answers = app
    g["settings"][sh.SETTING] = "NORTH PLANT"
    path, _ = shipment_file(tmp_path, "FSR-ORG-202611-0101")  # saved above
    answers.calls.clear()
    assert g["fsr_shipment_ui"].receive_file(g, str(path)) is None
    assert "already in saved report" in errors(answers)[0][2]


def test_a_shipment_for_another_destination_is_refused(app, tmp_path):
    g, answers = app
    g["settings"][sh.SETTING] = "SOUTH PLANT"
    path, payload = shipment_file(tmp_path, "FSR-ORG-202611-0103")
    before = g["draft_controller"].store.list()[0]
    answers.calls.clear()
    assert g["fsr_shipment_ui"].receive_file(g, str(path)) is None
    message = errors(answers)[0][2]
    assert "for NORTH PLANT" in message and "SOUTH PLANT" in message
    assert len(g["draft_controller"].store.list()[0]) == len(before)
    assert payload["transfer_id"] not in sh.load_ledger(
        g["excel_state"]["path"])["imports"]


def test_no_destination_set_means_no_import(app, tmp_path):
    g, answers = app
    g["settings"].pop(sh.SETTING, None)
    path, _ = shipment_file(tmp_path, "FSR-ORG-202611-0104")
    answers.calls.clear()
    assert g["fsr_shipment_ui"].receive_file(g, str(path)) is None
    assert "not set yet" in errors(answers)[0][2]


def test_a_damaged_file_makes_no_draft(app, tmp_path):
    g, answers = app
    g["settings"][sh.SETTING] = "NORTH PLANT"
    path, _ = shipment_file(tmp_path, "FSR-ORG-202611-0105")
    path.write_text(path.read_text(encoding="utf-8").replace(
        "Valve", "Valv"), encoding="utf-8")
    before = len(g["draft_controller"].store.list()[0])
    answers.calls.clear()
    assert g["fsr_shipment_ui"].receive_file(g, str(path)) is None
    assert "damaged" in errors(answers)[0][2]
    assert len(g["draft_controller"].store.list()[0]) == before


def test_a_shipment_file_chosen_as_a_hand_over_goes_to_receive_shipment(
        app, tmp_path, monkeypatch):
    g, answers = app
    g["settings"][sh.SETTING] = "NORTH PLANT"
    path, _ = shipment_file(tmp_path, "FSR-ORG-202611-0106",
                            numbers=("",))
    seen = []
    monkeypatch.setitem(g, "open_receive_shipment",
                        lambda chosen=None: seen.append(chosen))
    g["receive_handover"](str(path))
    assert seen == [str(path)]


def test_a_shipment_made_on_the_phone_becomes_a_draft_on_the_pc(app):
    """Android origin -> Windows destination: the file the phone app writes
    (tests/data/shipment_from_android.fsrshipment, by its own tests)."""
    from pathlib import Path
    g, answers = app
    g["settings"][sh.SETTING] = "NORTH PLANT"
    g["new_report"](confirm=False)
    phone_file = Path(__file__).resolve().parent / "data" / \
        "shipment_from_android.fsrshipment"
    answers.calls.clear()
    value = g["fsr_shipment_ui"].receive_file(g, str(phone_file))
    assert value is not None and not errors(answers)
    assert "from the phone app" in [c for c in answers.calls
                                    if c[0] == "askyesno"][0][2]
    section = g["item_frames"][0]
    lines = [r for r in section.rows if section.line_values(r)]
    assert [cell(section, r, "Description of Goods") for r in lines] == [
        "Diaphragm", "Valve body", "Valve seat", "Spare kit"]
    assert [cell(section, r, "Weights") for r in lines][0] == "10"
    assert [r.hidden.get("Origin Line") for r in lines][3] == \
        "FSR-PHN-202611-0007/1/4"
    assert lines[0].hidden["Packing List No."] == "NOR111126-001 & 002"
