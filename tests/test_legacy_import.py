"""Old master data CSV -> Import Master Data file -> the Excel data file."""
import csv
import json
from datetime import date

import pytest

import fsr_import as imp
import fsr_legacy_import as legacy
import fsr_storage as s
from factories import report

NAMES = {"Comdiv": "Comdiv #", "Container": "Container type",
         "Shipment": "Shipment type", "PO": "Purchased order", "DR": "DR/WB",
         "Vehicle": "Plate#/Vehicle type", "Qty": "Quatity", "Unit": "Unit price",
         "Total": "Total price", "Remarks": "Other Important Remarks",
         "JO": "Job Order", "AWB": "BL / AWB", "Marks": "other marks"}


def row(**values):
    cells = {header: "" for header in legacy.EXPECTED_HEADERS}
    cells.update({NAMES.get(k, k): v for k, v in values.items()})
    return cells


def head(**values):
    cells = dict(Comdiv="PH-MNL-1", Activity="Receiving",
                 Container="Non-containerized", Shipment="Local",
                 Date="05-Jan-26", Location="DHL warehouse - Sta. Rosa",
                 Consignee="Energy Development Corp.", Supplier="Acme",
                 DR="DR#: 1234", Description="Pump", Packaging="Box",
                 Qty="2 pcs", Unit="php 1,000.00", Total="php 2,000.00",
                 Condition="Good order", Remarks="-Line one., -Line two, , , ")
    cells.update(values)
    return row(**cells)


def write_csv(path, *rows, encoding="utf-8"):
    with open(path, "w", newline="", encoding=encoding) as file:
        writer = csv.DictWriter(file, fieldnames=legacy.EXPECTED_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def old(tmp_path):
    return tmp_path / "old.csv"


@pytest.fixture
def book(tmp_path):
    return tmp_path / "data.xlsx"


def run_import(path, book, target=None):
    plan = legacy.plan_migration(path, target)
    file_path = path.with_suffix(".json")
    file_path.write_text(json.dumps(legacy.master_file(plan)), encoding="utf-8")
    return plan, imp.import_master_data(book, imp.read_master_file(file_path))


def test_full_record_lands_in_the_right_fields(old, book):
    write_csv(old, head(
        Broker="AC Obsum", Hauler="Libcap", Destination="LGPF", Origin="Japan",
        Invoice="INV-1", PO="1001", Gatepass="GP-1", JO="JO-1", AWB="AWB#: 9",
        Marks="Seal 1", Vehicle="4W close van / NBB 1124", Dimension="1x2 cm",
        Weight="5 kg"))
    _, summary = run_import(old, book)
    back = s.read_report(book, summary["added"][0])
    general = back["general_information"]
    assert general["so_number"] == "PH-MNL-1"
    assert general["inspection_date"] == "05-Jan-2026"
    assert general["brokerage"] == "AC Obsum" and general["hauler"] == "Libcap"
    assert general["country_of_origin"] == "Japan"
    documents = back["documents_used"]
    assert documents["jo_number"] == "JO-1" and documents["dr_number"] == "DR#: 1234"
    assert documents["other_documents"] == "Seal 1"
    transport = back["transport_details"]
    assert transport["vehicle_type"] == "4W close van"
    assert transport["vehicle_plate_number"] == "NBB 1124"
    assert transport["container_type"] == "Non-Containerized"
    line = back["item_lists"][0]["rows"][0]
    assert (line["Quantity"], line["UOM"]) == ("2", "pcs")
    assert (line["Unit Price"], line["Total Price"]) == ("1,000.00", "2,000.00")
    assert line["Currency"] == "PHP" and line["Weights"] == "5 kg"
    assert back["other_important_remarks"] == ["-Line one.", "-Line two"]


def test_fields_without_source_stay_blank(old, book):
    write_csv(old, head())
    _, summary = run_import(old, book)
    back = s.read_report(book, summary["added"][0])
    schedule = back["inspection_schedule"]
    assert schedule["commenced_date"] == schedule["completion_time"] == ""
    assert back["transport_details"]["vessel_carrier"] == ""
    assert back["declared_goods"] == [] and back["findings_and_remarks"] == []
    assert back["general_information"]["hauler"] == ""
    assert not any(back["goods_types"].values())
    line = back["item_lists"][0]["rows"][0]
    assert line["Cargo ID"] == "" and line["PO Number"] == ""
    assert back["incident_reports"] == []


def test_continuation_rows_join_the_record_and_keep_their_condition(old, book):
    write_csv(old, head(), row(Description="Second", Packaging="Box", Qty="1 set",
                               Weight="'", Condition="Bad order"))
    plan, summary = run_import(old, book)
    rows = s.read_report(book, summary["added"][0])["item_lists"][0]["rows"]
    assert [r["Description of Goods"] for r in rows] == ["Pump", "Second"]
    assert rows[1]["Findings"] == "Bad order" and rows[1]["Weights"] == "'"
    assert ("ditto_mark_kept", "line 3") in plan["import"][0]["issues"]


def test_more_than_thirty_lines_flow_to_a_second_item_list(old, book):
    extra = [row(Description=f"Item {n}") for n in range(35)]
    write_csv(old, head(), *extra)
    _, summary = run_import(old, book)
    lists = s.read_report(book, summary["added"][0])["item_lists"]
    assert [len(item["rows"]) for item in lists] == [30, 6]


def test_invalid_date_is_skipped_not_guessed(old):
    write_csv(old, head(Date="Jun 09-10, 2026"), head(Date="", Supplier="Other"))
    plan = legacy.plan_migration(old)
    assert plan["import"] == [] and len(plan["skipped"]) == 2
    assert plan["skipped"][0]["reason"] == "invalid_date"


def test_second_page_row_is_held_for_review(old):
    write_csv(old, head(), head(Location="", Supplier="", DR=""))
    plan = legacy.plan_migration(old)
    assert len(plan["import"]) == 1
    assert "second page" in plan["skipped"][0]["reason"]


def test_duplicate_in_file_is_held_and_can_be_released(old):
    write_csv(old, head(), head(Shipment="Import"), head(DR="DR#: 7777"))
    plan = legacy.plan_migration(old)
    assert [item["line"] for item in plan["import"]] == [2, 4]
    assert plan["duplicates"][0]["line"] == 3
    released = legacy.plan_migration(old, release_lines={3})
    assert len(released["import"]) == 3


def test_report_already_in_workbook_is_held_and_untouched(old, book):
    saved = report("FSR-2026-0001", "Receiving", date(2026, 1, 5), so="MINE")
    saved["documents_used"]["dr_number"] = "1234"
    s.write_report_to_excel(book, saved, False)
    write_csv(old, head())
    plan, summary = run_import(old, book, book)
    assert summary["added"] == []
    assert plan["duplicates"][0]["reason"] == "may already exist as FSR-2026-0001"
    assert s.read_report(book, "FSR-2026-0001")["general_information"]["so_number"] == "MINE"


def test_existing_reports_survive_an_import(old, book):
    s.write_report_to_excel(
        book, report("FSR-2026-0009", "Receiving", date(2026, 2, 1), so="MINE"), False)
    write_csv(old, head())
    _, summary = run_import(old, book, book)
    assert summary["backup"]
    assert len(s.read_all_reports(book)) == 2
    assert s.read_report(book, "FSR-2026-0009")["general_information"]["so_number"] == "MINE"


def test_second_run_changes_nothing(old, book):
    write_csv(old, head())
    run_import(old, book)
    before = book.read_bytes()
    _, again = run_import(old, book, book)
    assert again["added"] == [] and len(again["unchanged"]) == 1
    assert book.read_bytes() == before


def test_failure_midway_can_be_repeated_without_duplicates(old, book):
    write_csv(old, head(), head(DR="DR#: 5678", Supplier="Other"))
    plan = legacy.plan_migration(old)
    calls = []

    def fail_second(_report):      # stands in for a MySQL error
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("database down")

    with pytest.raises(RuntimeError):
        imp.import_master_data(book, json.loads(json.dumps(legacy.master_file(plan))),
                               fail_second)
    summary = imp.import_master_data(
        book, json.loads(json.dumps(legacy.master_file(plan))))
    assert len(summary["unchanged"]) == 2
    assert len(s.read_all_reports(book)) == 2


@pytest.mark.parametrize("encoding, text", [("utf-8", "Café Ñino 株式"),
                                            ("cp1252", "supplier’s Ñino")])
def test_special_characters_are_kept(old, book, encoding, text):
    write_csv(old, head(Supplier=text), encoding=encoding)
    _, summary = run_import(old, book)
    assert s.read_report(book, summary["added"][0])[
        "general_information"]["supplier"] == text


def test_empty_cells_become_empty_cells(old, book):
    write_csv(old, head(Hauler="", Dimension=""))
    run_import(old, book)
    wb = s.open_workbook_for_read(book)
    assert next(s.report_dicts(wb["Reports"]))["Hauler"] is None


def test_wrong_file_is_refused(tmp_path):
    path = tmp_path / "other.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(legacy.LegacyFileError):
        legacy.plan_migration(path)


def test_source_file_is_not_changed(old, tmp_path):
    write_csv(old, head())
    before = old.read_bytes()
    legacy.write_outputs(legacy.plan_migration(old), tmp_path / "out")
    assert old.read_bytes() == before


@pytest.mark.parametrize("text, expected", [
    ("4W Pick up / NBA 7417", ("4W Pick up", "NBA 7417", False)),
    ("NAX 9872 / 6W close van", ("6W close van", "NAX 9872", False)),
    ("Plate#: NFL 2949 / HBT", ("HBT", "NFL 2949", False)),
    ("NKJ 1507", ("", "NKJ 1507", False)),
    ("cvan#: EGSU 382225-5", ("cvan#: EGSU 382225-5", "", True)),
    ("HBT / NKC 3596 / 020110", ("HBT / NKC 3596 / 020110", "", True)),
    ("n/a", ("n/a", "", False)),
])
def test_vehicle_split_only_when_clear(text, expected):
    assert legacy.split_vehicle(text) == expected


@pytest.mark.parametrize("unit, total, expected", [
    ("jpy 34,500,000.-", "jpy 34,500,000.-", ("34,500,000", "34,500,000", "JPY", True)),
    ("php 48.50", "n/a", ("48.50", "n/a", "PHP", True)),
    ("jpy 4,000.-", "php 16,000.-", ("jpy 4,000.-", "php 16,000.-", "", False)),
    ("eur 65,307,00", "eur 65,307,00", ("eur 65,307,00", "eur 65,307,00", "", False)),
    ("n/a", "n/a", ("n/a", "n/a", "", True)),
])
def test_money_split_only_when_clear(unit, total, expected):
    assert legacy.split_money(unit, total) == expected
