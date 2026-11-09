"""Export for the web portal: one JSON file covering both workbooks and sidecars."""
import json
from datetime import date

import pytest

import fsr_import
import fsr_portal_export as export
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
    with pytest.raises(export.PortalExportError):
        export.write_export(path, target, "pc-1")
    assert not target.exists()


def test_export_does_not_change_the_workbook(tmp_path):
    path = saved_book(tmp_path)
    before = path.read_bytes()
    export.write_export(path, tmp_path / "out.json", "pc-1")
    assert path.read_bytes() == before

