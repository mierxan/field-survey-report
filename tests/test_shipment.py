"""Sharing a Withdrawal report's Packing Lists with its destinations
(fsr_shipment). Invented reports in temporary folders; no widgets."""
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

import fsr_shipment as sh
import fsr_storage as storage
import fsr_store
import fsr_withdrawal as wd
from factories import report
from test_withdrawal import books, linked_report

SENDER = {"inspector": "Inspector Alpha", "initials": "ALP",
          "device_id": "pc-a"}
CONTROL = "FSR-ALP-202611-0007"
DATA = Path(__file__).resolve().parent / "data"
FIXTURE = DATA / "shipment_from_windows.fsrshipment"


def line(desc, po, findings, qty="1", unit="CRATE", **more):
    row = {h: "" for h in storage.ITEM_LINE_HEADERS}
    row.update({"Description of Goods": desc, "PO Number": po,
                "Packaging": "Crate", "Quantity": qty, "UOM": unit,
                "Dimensions": "1x1x1 cm", "Weights": "10 KG",
                "Unit Price": "1,000.00", "Total Price": "1,000.00",
                "Currency": "PHP", "Findings": findings,
                "Cargo ID": "CARGO-1", "Receiving Ref": "RCV-X-1-01"})
    row.update(more)
    return row


def withdrawal(control=CONTROL, destination="NORTH PLANT"):
    """A Withdrawal with three Packing Lists (one written as a pair), a line
    without one, in two Item Lists - as the origin inspectors type them."""
    data = report(control, "Withdrawal", date(2026, 11, 11), "Origin Yard",
                  so="SO-SECRET-1", supplier="Secret Supplier Co")
    data["general_information"]["destination"] = destination
    data["item_lists"] = [
        {"name": "Item List 1", "rows": [
            line("Diaphragm", "PO-100", "NOR111126-001 & 002"),
            line("Valve body", "PO-100", "NOR111126-003", qty="2"),
            line("Valve seat", "PO-200", "NOR111126-003", qty="4"),
            line("Spare kit", "PO-300", "Good condition")]},
        {"name": "Item List 2", "rows": [
            line("Rotor", "PO-400", "SOU111126-001", qty="1", unit="SET")]},
    ]
    return data


def workbook(tmp_path, *reports):
    book = tmp_path / "pc" / "Field_Survey_Reports.xlsx"
    book.parent.mkdir(parents=True, exist_ok=True)
    for value in reports:
        fsr_store.ExcelStore(book).write_report(value, False)
    return book


def digest(folder):
    """Every file of a folder and its content (to prove nothing changed)."""
    return {p.relative_to(folder).as_posix(): hashlib.sha256(
        p.read_bytes()).hexdigest() for p in sorted(Path(folder).rglob("*"))
        if p.is_file()}


# ---------- packing lists ----------

def test_packing_lists_are_read_from_findings_exactly_as_written():
    found = sh.groups(withdrawal())
    assert [(g["number"], g["po_numbers"], len(g["lines"])) for g in found] \
        == [("NOR111126-001 & 002", ["PO-100"], 1),
            ("NOR111126-003", ["PO-100", "PO-200"], 2),
            ("", ["PO-300"], 1),                  # "Good condition"
            ("SOU111126-001", ["PO-400"], 1)]


def test_the_own_packing_list_field_wins_over_findings():
    row = line("X", "PO", "Dented corner", **{sh.PACKING_LIST: "ABC111126-9"})
    assert sh.packing_list_of(row) == "ABC111126-9"
    assert sh.packing_list_of(line("X", "PO", "Dented corner")) == ""
    assert sh.packing_list_of(line("X", "PO", "MTA11126-001")) == \
        "MTA11126-001"


# ---------- one and several destinations ----------

def test_one_destination_gets_its_packing_lists_and_nothing_private(
        tmp_path):
    book = workbook(tmp_path, withdrawal())
    out = tmp_path / "out"
    out.mkdir()
    written = sh.write_shipments(
        fsr_store.ExcelStore(book), CONTROL,
        {"NOR111126-001 & 002": "NORTH PLANT", "NOR111126-003": "NORTH PLANT"},
        out, SENDER, day=date(2026, 11, 18))
    assert [(d, p.name) for d, p, _ in written] == [(
        "NORTH PLANT",
        f"FSR_Shipment_{CONTROL}_to_NORTH_PLANT_2026-11-18.fsrshipment")]
    payload = sh.read_file(written[0][1])
    assert payload["origin"] == {
        "control_no": CONTROL, "activity": "Withdrawal",
        "location": "Origin Yard", "inspection_date": "11-Nov-2026",
        "item_form": "Default"}
    assert payload["destination"] == "NORTH PLANT"
    assert payload["from"] == SENDER
    rows = [r for il in payload["item_lists"] for r in il["rows"]]
    assert [(r["Description of Goods"], r[sh.PACKING_LIST], r[sh.ORIGIN_LINE])
            for r in rows] == [
        ("Diaphragm", "NOR111126-001 & 002", f"{CONTROL}/1/1"),
        ("Valve body", "NOR111126-003", f"{CONTROL}/1/2"),
        ("Valve seat", "NOR111126-003", f"{CONTROL}/1/3")]
    assert set(rows[0]) == set(sh.LINE_FIELDS)
    assert rows[1]["Quantity"] == "2" and rows[1]["UOM"] == "CRATE"
    text = written[0][1].read_text(encoding="utf-8")
    for secret in ("SO-SECRET-1", "Secret Supplier Co", "RCV-X-1-01",
                   "CARGO-1", "Good condition"):
        assert secret not in text
    # the prices travel (owner's decision, 18 November 2026)
    assert (rows[0]["Currency"], rows[0]["Unit Price"],
            rows[0]["Total Price"]) == ("PHP", "1,000.00", "1,000.00")


def test_several_destinations_each_get_only_their_own_lines(tmp_path):
    book = workbook(tmp_path, withdrawal())
    out = tmp_path / "out"
    out.mkdir()
    written = sh.write_shipments(
        fsr_store.ExcelStore(book), CONTROL,
        {"NOR111126-001 & 002": "NORTH PLANT", "NOR111126-003": "north plant",
         "SOU111126-001": "SOUTH PLANT", "": "SOUTH PLANT"}, out, SENDER)
    assert [d for d, _, _ in written] == ["NORTH PLANT", "SOUTH PLANT"]
    north, south = (sh.read_file(p) for _, p, _ in written)
    assert north["transfer_id"] != south["transfer_id"]
    assert [p["number"] for p in north["packing_lists"]] == [
        "NOR111126-001 & 002", "NOR111126-003"]
    assert [(p["number"], p["line_count"]) for p in south["packing_lists"]] \
        == [("", 1), ("SOU111126-001", 1)]
    # the lines keep their Item Lists (renumbered from 1), origin lines kept
    assert [[r[sh.ORIGIN_LINE] for r in il["rows"]]
            for il in south["item_lists"]] == [[f"{CONTROL}/1/4"],
                                               [f"{CONTROL}/2/1"]]
    assert [il["name"] for il in south["item_lists"]] == ["Item List 1",
                                                          "Item List 2"]


def test_packing_lists_without_a_destination_are_not_shared(tmp_path):
    book = workbook(tmp_path, withdrawal())
    out = tmp_path / "out"
    out.mkdir()
    written = sh.write_shipments(fsr_store.ExcelStore(book), CONTROL,
                                 {"SOU111126-001": "SOUTH PLANT",
                                  "NOR111126-003": ""}, out, SENDER)
    assert len(written) == 1
    rows = written[0][2]["item_lists"][0]["rows"]
    assert [r["Description of Goods"] for r in rows] == ["Rotor"]


def test_the_same_name_twice_gets_a_second_file_not_an_overwrite(tmp_path):
    book = workbook(tmp_path, withdrawal())
    out = tmp_path / "out"
    out.mkdir()
    store = fsr_store.ExcelStore(book)
    first = sh.write_shipments(store, CONTROL, {"SOU111126-001": "SOUTH"},
                               out, SENDER, day=date(2026, 11, 18))
    second = sh.write_shipments(store, CONTROL, {"SOU111126-001": "SOUTH"},
                                out, SENDER, day=date(2026, 11, 18))
    assert first[0][1] != second[0][1] and first[0][1].exists()
    assert second[0][1].stem.endswith("_2")


# ---------- the origin report is never changed ----------

def test_sharing_leaves_the_origin_report_and_its_files_unchanged(tmp_path):
    book = workbook(tmp_path, withdrawal())
    before = digest(book.parent)
    out = tmp_path / "out"
    out.mkdir()
    sh.write_shipments(fsr_store.ExcelStore(book), CONTROL,
                       {"NOR111126-003": "NORTH PLANT",
                        "SOU111126-001": "SOUTH PLANT"}, out, SENDER)
    assert digest(book.parent) == before
    assert storage.read_report(book, CONTROL)["item_lists"][0]["rows"][1][
        "Findings"] == "NOR111126-003"


def test_a_po_linked_withdrawal_is_shared_and_stays_unchanged(tmp_path):
    main, book = books(tmp_path)
    data = linked_report(tmp_path, picks=[("4500001", "1"), ("4500001", "3")],
                         quantities=["40", "2.5"])
    rows = data["item_lists"][0]["rows"]
    rows[0]["Findings"] = "LEY111126-003"
    rows[1]["Findings"] = "LEY111126-001 & 002"
    wd.write_withdrawal_report(book, data, False, main)
    before = digest(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    store = fsr_store.ExcelStore(main)
    assert [r["control_no"] for r in sh.withdrawal_reports(store)] == [
        data["control_no"]]
    written = sh.write_shipments(store, data["control_no"],
                                 {"LEY111126-003": "LGPF",
                                  "LEY111126-001 & 002": "LGPF"}, out, SENDER)
    shared = [r for il in written[0][2]["item_lists"] for r in il["rows"]]
    assert [(r["Description of Goods"], r["Quantity"], r[sh.PACKING_LIST])
            for r in shared] == [("Pump", "40", "LEY111126-003"),
                                 ("Cable", "2.5", "LEY111126-001 & 002")]
    assert all(set(r) == set(sh.LINE_FIELDS) for r in shared)
    assert digest(tmp_path) == before | {
        f"out/{written[0][1].name}": digest(out)[written[0][1].name]}


# ---------- nothing half-made ----------

def test_a_failed_write_leaves_no_file_behind(tmp_path, monkeypatch):
    book = workbook(tmp_path, withdrawal())
    out = tmp_path / "out"
    out.mkdir()
    real = storage.write_json_atomic
    calls = []

    def second_fails(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(storage, "write_json_atomic", second_fails)
    with pytest.raises(OSError, match="disk full"):
        sh.write_shipments(fsr_store.ExcelStore(book), CONTROL,
                           {"NOR111126-003": "NORTH", "SOU111126-001":
                            "SOUTH"}, out, SENDER)
    assert list(out.iterdir()) == []


@pytest.mark.parametrize("assign, message", [
    ({}, "at least one"),
    ({"NOR111126-003": "  "}, "at least one"),
    ({"XYZ999999-999": "NORTH"}, "no Packing List"),
])
def test_wrong_choices_make_no_file(tmp_path, assign, message):
    book = workbook(tmp_path, withdrawal())
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(sh.ShipmentError, match=message):
        sh.write_shipments(fsr_store.ExcelStore(book), CONTROL, assign, out,
                           SENDER)
    assert list(out.iterdir()) == []


def test_a_receiving_report_cannot_be_shared(tmp_path):
    value = withdrawal()
    value["inspection_schedule"]["activity"] = "Receiving"
    book = workbook(tmp_path, value)
    store = fsr_store.ExcelStore(book)
    assert sh.withdrawal_reports(store) == []
    with pytest.raises(sh.ShipmentError, match="not a Withdrawal"):
        sh.write_shipments(store, CONTROL, {"SOU111126-001": "S"}, tmp_path,
                           SENDER)


# ---------- reading a file back ----------

def envelope(payload, **changes):
    root = sh._envelope(payload)
    root.update(changes)
    return root


def sample_payload():
    return sh.build_payload(withdrawal(), "NORTH PLANT",
                            ["NOR111126-003"], SENDER)


def test_damaged_or_foreign_files_are_refused():
    payload = sample_payload()
    assert sh.decode(envelope(payload)) == payload
    with pytest.raises(sh.ShipmentError, match="hand-over file"):
        sh.decode({"format": "fsr-handover", "version": 1})
    with pytest.raises(sh.ShipmentError, match="not a Field Survey"):
        sh.decode({"format": "something-else"})
    with pytest.raises(sh.ShipmentError, match="version 2"):
        sh.decode(envelope(payload, version=2))
    with pytest.raises(sh.ShipmentError, match="damaged or incomplete"):
        root = envelope(payload)
        root["payload"] = root["payload"].replace("Valve", "Valv")
        sh.decode(root)


@pytest.mark.parametrize("change, reason", [
    (lambda p: p["item_lists"][0]["rows"][0].update(
        {"Cargo ID": "CID-5"}), "not shared"),
    (lambda p: p["item_lists"][0]["rows"][0].update(
        {sh.ORIGIN_LINE: ""}), "origin line"),
    (lambda p: p.update(destination=""), "no destination"),
    (lambda p: p["origin"].update(control_no=""), "origin Control"),
    (lambda p: p["packing_lists"][0].update(line_count=9), "do not match"),
    (lambda p: p.update(item_lists=[]), "no Item List"),
    (lambda p: p.update(kind="report"), "not a Withdrawal shipment"),
])
def test_a_file_that_says_more_or_less_than_it_should_is_refused(
        change, reason):
    payload = sample_payload()
    change(payload)
    with pytest.raises(sh.ShipmentError, match=reason):
        sh.decode(envelope(payload))


# ---------- the file the Android tests read ----------

def fixture_payload():
    return sh.build_payload(
        withdrawal(), "NORTH PLANT", ["NOR111126-001 & 002", "NOR111126-003",
                                      ""],
        SENDER, transfer_id="0123456789abcdef0123456789abcdef",
        created_at="2026-11-18T09:30:00+08:00")


def test_the_sample_file_for_the_android_tests_is_current():
    """tests/data/shipment_from_windows.fsrshipment is read by the Android
    app's tests (ShipmentCodecTest): it must be what this program writes."""
    expected = sh._envelope(fixture_payload())
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == expected
    assert sh.read_file(FIXTURE) == fixture_payload()
    phone_copy = (Path(__file__).resolve().parents[2] / "field_survey_report"
                  / "FieldSurveyReport" / "app" / "src" / "test" / "resources"
                  / FIXTURE.name)
    if phone_copy.exists():             # the Android project beside this one
        assert phone_copy.read_bytes() == FIXTURE.read_bytes()
    # to write it again after a deliberate format change (from the project
    # folder):  set PYTHONPATH=.;tests  then
    #   python -c "import fsr_storage, fsr_shipment as sh, test_shipment as t;
    #   fsr_storage.write_json_atomic(t.FIXTURE,
    #   sh._envelope(t.fixture_payload()))"
    # and copy it to the Android project's app/src/test/resources.


def test_the_file_the_phone_app_writes_is_read():
    """tests/data/shipment_from_android.fsrshipment: written by the Android
    app's ShipmentCodecTest from the same invented Withdrawal."""
    payload = sh.read_file(DATA / "shipment_from_android.fsrshipment")
    assert payload["app"] == "android"
    assert payload["origin"]["control_no"] == "FSR-PHN-202611-0007"
    assert payload["destination"] == "NORTH PLANT"
    assert payload["from"] == {"inspector": "Phone Inspector",
                               "initials": "PHN", "device_id": "phone-1"}
    rows = [r for il in payload["item_lists"] for r in il["rows"]]
    assert [(r["Description of Goods"], r[sh.PACKING_LIST], r[sh.ORIGIN_LINE])
            for r in rows] == [
        ("Diaphragm", "NOR111126-001 & 002", "FSR-PHN-202611-0007/1/1"),
        ("Valve body", "NOR111126-003", "FSR-PHN-202611-0007/1/2"),
        ("Valve seat", "NOR111126-003", "FSR-PHN-202611-0007/1/3"),
        ("Spare kit", "", "FSR-PHN-202611-0007/1/4")]
    assert rows[0]["Weights"] == "10 KG" and rows[1]["Quantity"] == "2"
    # the same lines as this program writes for the same Withdrawal
    ours = fixture_payload()
    assert [{k: v for k, v in r.items() if k != sh.ORIGIN_LINE}
            for il in ours["item_lists"] for r in il["rows"]] == \
        [{k: v for k, v in r.items() if k != sh.ORIGIN_LINE} for r in rows]
    assert ours["packing_lists"] == payload["packing_lists"]


def test_a_phone_line_keeps_its_packing_list_on_the_pc():
    """A phone draft handed over to a PC (fsr_handover.phone_report_data):
    the two fields come along when a line has them, and only then."""
    import fsr_handover
    phone = {"controlNo": "FSR-PHN-202611-0011", "itemForm": "Default",
             "activity": "Receiving",
             "itemLists": {"Default": [{"lines": [
                 {"description": "Valve body", "quantity": "2",
                  "findings": "Good Order and Complete",
                  "packingListNo": "NOR111126-003",
                  "originLine": "FSR-ALP-202611-0007/1/2"},
                 {"description": "Typed at the destination", "quantity": "1",
                  "packingListNo": "", "originLine": ""}]}]}}
    rows = fsr_handover.phone_report_data(phone)["item_lists"][0]["rows"]
    assert (rows[0]["Packing List No."], rows[0]["Origin Line"],
            rows[0]["Findings"]) == ("NOR111126-003",
                                     "FSR-ALP-202611-0007/1/2",
                                     "Good Order and Complete")
    assert "Packing List No." not in rows[1] and "Origin Line" not in rows[1]


def test_a_new_line_packing_list_field_is_shared_as_is():
    """A Receiving line made from a shipment keeps its Packing List No. even
    when Findings is edited, and a later share uses that field."""
    row = line("Valve body", "PO-1", "1 crate dented",
               **{sh.PACKING_LIST: "NOR111126-003"})
    assert sh.packing_list_of(row) == "NOR111126-003"
