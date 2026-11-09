"""Export Master Data: one JSON file covering both workbooks and sidecars, which
the owner brings in with Import Master Data."""
import json
from datetime import date

import pytest

import fsr_import
import fsr_master_export as export
import fsr_storage as s
from factories import report
from warehouse.store import SideStore


def saved_book(tmp_path):
    path = tmp_path / "data.xlsx"
    data = report("FSR-202611-0001", "Receiving", date(2026, 11, 1), "WH",
                  [{"qty": 2, "unit": "Crate", "desc": "Pump"}])
    data["cargo_condition"] = s.CONDITION_BAD
    s.write_report_to_excel(path, data, False)
    s.save_incident_data(path, "FSR-202611-0001", "SO", [{"lines": ["Crate crushed"]}])
    return path


def test_export_covers_reports_incidents_and_statuses(tmp_path):
    path = saved_book(tmp_path)
    SideStore(path).set_case_status("FSR-202611-0001", "Open", user="U")
    target = tmp_path / "out.json"
    assert export.write_export(path, target, "pc-1", "Ana") == 1
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["device_id"] == "pc-1" and data["inspector"] == "Ana"
    assert data["format"] == fsr_import.FORMAT
    only = data["reports"][0]
    assert only["incident_reports"][0]["lines"] == ["Crate crushed"]
    assert only["last_saved"]
    assert data["case_status"][0]["status"] == "Open"
    assert fsr_import.read_master_file(target)["reports"]


def test_export_stops_when_an_incident_file_is_damaged(tmp_path):
    path = saved_book(tmp_path)
    s.incident_json_path(path, "FSR-202611-0001").write_text("{broken", encoding="utf-8")
    target = tmp_path / "out.json"
    with pytest.raises(export.MasterExportError):
        export.write_export(path, target, "pc-1")
    assert not target.exists()


def test_export_does_not_change_the_workbook(tmp_path):
    path = saved_book(tmp_path)
    before = path.read_bytes()
    export.write_export(path, tmp_path / "out.json", "pc-1")
    assert path.read_bytes() == before


LISTS = {"consignee_list": ["Site Consignee", " "], "supplier_list": ["Site Supplier"]}


def test_export_includes_the_master_lists(tmp_path):
    path = saved_book(tmp_path)
    target = tmp_path / "out.json"
    export.write_export(path, target, "pc-1", "Ana", LISTS)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["master_lists"]["consignee_list"] == ["Site Consignee"]
    assert data["master_lists"]["hauler_list"] == []
    assert set(data["master_lists"]) == set(fsr_import.LIST_KEYS)


def test_owner_imports_a_site_export_once(tmp_path):
    """User edition PC -> Master Data file -> Owner edition PC."""
    site = tmp_path / "site"
    site.mkdir()
    path = saved_book(site)
    target = tmp_path / "FSR_Master_Data_site.json"
    export.write_export(path, target, "site-pc", "Ana", LISTS)

    owner = tmp_path / "owner"
    owner.mkdir()
    owner_book = owner / "data.xlsx"
    data = fsr_import.read_master_file(target)
    copied = []
    summary = fsr_import.import_master_data(owner_book, data, copied.append)
    assert summary["added"] == ["FSR-202611-0001"] and len(copied) == 1
    saved = s.read_report(owner_book, "FSR-202611-0001")
    assert saved["general_information"]["so_number"] == "SO-1"
    incident = s.load_incident_data(owner_book, "FSR-202611-0001")
    assert "Crate crushed" in json.dumps(incident)

    owner_lists = {"consignee_list": ["Con"], "supplier_list": []}
    names = fsr_import.new_master_names(data, owner_lists)
    assert names["consignee_list"] == ["Site Consignee"]
    assert names["supplier_list"] == ["Site Supplier"]

    again = fsr_import.import_master_data(owner_book, data)
    assert again["unchanged"] == ["FSR-202611-0001"] and not again["added"]
