"""Phase 5: the shipment work between Windows and Android, every way round,
and older files. Invented data only.

  Windows -> Windows   test_shipment_import_gui (a PC file into a PC draft)
  Android -> Windows   test_shipment_import_gui (the phone's file into a PC
                       draft) and below (a phone hand-over of a received
                       report keeps its Packing Lists on the PC)
  Windows -> Android   below writes tests/data/handover_receiving_from_
                       windows.json, which the app's InteropTest reads; the
                       app's ShipmentFlowTest turns the Windows shipment file
                       into a phone draft
  Android -> Android   the app's InteropTest and ShipmentFlowTest

Older files: a shipment file made before prices travelled (no Currency,
Unit Price, Total Price) still reads and imports, with empty prices.
"""
import json
from datetime import date
from pathlib import Path

import fsr_handover as ho
import fsr_shipment as sh
import fsr_storage as storage
import fsr_store
from factories import report
from test_shipment import SENDER, withdrawal

DATA = Path(__file__).resolve().parent / "data"
FROM_WINDOWS = DATA / "handover_receiving_from_windows.json"
FROM_ANDROID = DATA / "handover_from_android_receiving.json"
RECEIVED = "FSR-WIN-202611-0021"


def received_report():
    """A saved Receiving report made from a shipment: two lines with their
    Packing List and origin, one added at the destination."""
    value = report(RECEIVED, "Receiving", date(2026, 11, 18), "NORTH PLANT",
                   [{"qty": 2, "unit": "Crate", "desc": "Valve body",
                     "po": "PO-100"},
                    {"qty": 4, "unit": "Crate", "desc": "Valve seat",
                     "po": "PO-200"},
                    {"qty": 1, "unit": "Pallet", "desc": "Extra pallet"}],
                   so="SO-WIN-RCV")
    rows = value["item_lists"][0]["rows"]
    rows[0].update({"Packing List No.": "NOR111126-003",
                    "Origin Line": "FSR-ALP-202611-0007/1/2",
                    "Findings": "Good Order and Complete",
                    "Currency": "PHP", "Unit Price": "1,000.00",
                    "Total Price": "2,000.00", "UOM": "CRATE"})
    rows[1].update({"Packing List No.": "NOR111126-003",
                    "Origin Line": "FSR-ALP-202611-0007/1/3",
                    "Findings": "1 crate dented", "UOM": "CRATE"})
    rows[2].update({"Findings": "Not on the packing list", "UOM": "PALLET"})
    return value


def pc(tmp_path, name, *reports):
    book = tmp_path / name / "Field_Survey_Reports.xlsx"
    book.parent.mkdir(parents=True)
    for value in reports:
        fsr_store.ExcelStore(book).write_report(value, False)
    return book


def write_windows_sample(tmp_path):
    """The hand-over file of the received report, as this program writes
    it (written into tests/data for the app's tests)."""
    book = pc(tmp_path, "origin", received_report())
    ho.hand_over_report(book, RECEIVED, FROM_WINDOWS,
                        {"inspector": "Windows Inspector", "initials": "WIN",
                         "device_id": "pc-win"}, to="Phone Inspector")
    return FROM_WINDOWS


# ---------- Windows -> Android: the sample the app reads ----------

def test_the_windows_hand_over_sample_carries_the_shipment_fields():
    """tests/data/handover_receiving_from_windows.json (read by the app's
    InteropTest; a copy is in its test resources): a hand-over this program
    writes, with the Packing List and Origin Line of each received line."""
    payload = ho.read_file(FROM_WINDOWS)
    rows = payload["report"]["item_lists"][0]["rows"]
    assert [(r.get("Packing List No."), r.get("Origin Line"), r["Findings"])
            for r in rows] == [
        ("NOR111126-003", "FSR-ALP-202611-0007/1/2",
         "Good Order and Complete"),
        ("NOR111126-003", "FSR-ALP-202611-0007/1/3", "1 crate dented"),
        (None, None, "Not on the packing list")]
    assert rows[0]["Unit Price"] == "1,000.00"
    phone_copy = (Path(__file__).resolve().parents[2] / "field_survey_report"
                  / "FieldSurveyReport" / "app" / "src" / "test"
                  / "resources" / FROM_WINDOWS.name)
    if phone_copy.exists():
        assert phone_copy.read_bytes() == FROM_WINDOWS.read_bytes()
    # to write it again (from the project folder, PYTHONPATH=.;tests):
    #   python -c "import tempfile, pathlib, test_shipment_interop as t;
    #   t.write_windows_sample(pathlib.Path(tempfile.mkdtemp()))"
    # and copy it to the app's app/src/test/resources.


def test_a_hand_over_keeps_the_shipment_fields_on_another_pc(tmp_path):
    """Windows -> Windows: the received report handed over to another PC."""
    payload = ho.read_file(FROM_WINDOWS)
    other = pc(tmp_path, "other")
    assert ho.receive(other, payload)["result"] == "added"
    rows = storage.read_report(other, RECEIVED)["item_lists"][0]["rows"]
    assert [r.get("Packing List No.") for r in rows] == [
        "NOR111126-003", "NOR111126-003", None]
    assert rows[1]["Findings"] == "1 crate dented"


# ---------- Android -> Windows ----------

def test_a_received_report_handed_over_from_the_phone_keeps_its_fields(
        tmp_path):
    """tests/data/handover_from_android_receiving.json, written by the app's
    InteropTest: a completed Receiving report the phone made from the
    Windows shipment sample, verified there, handed over to a PC."""
    payload = ho.read_file(FROM_ANDROID)
    assert payload["app"] == "android"
    book = pc(tmp_path, "pc")
    result = ho.receive(book, payload)
    assert result["result"] == "added"
    rows = storage.read_report(book, result["control"])["item_lists"][0][
        "rows"]
    assert [(r.get("Packing List No."), r.get("Origin Line"), r["Findings"])
            for r in rows] == [
        ("NOR111126-001 & 002", "FSR-ALP-202611-0007/1/1",
         "Good Order and Complete"),
        ("NOR111126-003", "FSR-ALP-202611-0007/1/2", "1 crate dented"),
        ("NOR111126-003", "FSR-ALP-202611-0007/1/3",
         "Good Order and Complete"),
        (None, "FSR-ALP-202611-0007/1/4", "Good Order and Complete"),
        (None, None, "Not on the packing list")]
    assert rows[0]["Unit Price"] == "1,000.00"
    assert storage.printed_findings(rows[1]) == \
        "NOR111126-003 · 1 crate dented"


# ---------- older shipment files ----------

def test_a_shipment_file_from_before_the_prices_still_imports():
    """Files made by the Phase 1/2 test builds have no price fields: they
    read, and the draft's prices are empty."""
    payload = sh.build_payload(withdrawal(), "NORTH PLANT",
                               ["NOR111126-003"], SENDER)
    for item_list in payload["item_lists"]:
        for row in item_list["rows"]:
            for key in ("Currency", "Unit Price", "Total Price"):
                del row[key]
    back = sh.decode(json.loads(json.dumps(sh._envelope(payload))))
    data = sh.receiving_data(back)
    rows = data["item_lists"][0]["rows"]
    assert [r["Description of Goods"] for r in rows] == ["Valve body",
                                                         "Valve seat"]
    assert {(r["Currency"], r["Unit Price"], r["Total Price"])
            for r in rows} == {("", "", "")}
    assert rows[0]["Packing List No."] == "NOR111126-003"
