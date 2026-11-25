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


# ---------- the whole file, both workbooks, and when it must stop ----------

def withdrawal_book(tmp_path):
    """A Receiving report in the main workbook and a PO-linked Withdrawal
    report (its own workbook) taking 1 of its 2 crates."""
    import fsr_store
    path = tmp_path / "data.xlsx"
    store = fsr_store.ExcelStore(path)
    receiving = report("FSR-202611-0001", "Receiving", date(2026, 11, 1),
                       "WH", [{"qty": 2, "unit": "Crate", "desc": "Pump",
                               "po": "PO-7", "cargo": "C-1",
                               "ref": "RCV-FSR-202611-0001-1-01"}],
                       so="SO-R")
    store.write_report(receiving, False)
    taken = report("FSR-202611-0002", "Withdrawal", date(2026, 11, 3), "WH",
                   [{"qty": 1, "unit": "Crate", "desc": "Pump", "po": "PO-7",
                     "ref": "RCV-FSR-202611-0001-1-01"}], so="SO-W")
    taken["other_item_forms"] = {}
    store.write_withdrawal_report(taken, False)
    return path


def test_the_file_holds_both_workbooks_and_nothing_else(tmp_path):
    path = withdrawal_book(tmp_path)
    target = tmp_path / "out.json"
    assert export.write_export(path, target, "pc-9", "Ben", LISTS) == 2
    data = json.loads(target.read_text(encoding="utf-8"))
    assert set(data) == {"format", "version", "device_id", "inspector",
                         "exported_at", "master_lists", "reports",
                         "case_status"}
    assert data["version"] == fsr_import.SUPPORTED_VERSION
    assert data["exported_at"][:4].isdigit() and "T" in data["exported_at"]
    assert data["case_status"] == []
    by_number = {r["control_no"]: r for r in data["reports"]}
    assert sorted(by_number) == ["FSR-202611-0001", "FSR-202611-0002"]
    assert by_number["FSR-202611-0001"]["general_information"][
        "so_number"] == "SO-R"
    taken = by_number["FSR-202611-0002"]
    assert taken["inspection_schedule"]["activity"] == "Withdrawal"
    assert taken["general_information"]["so_number"] == "SO-W"
    row = taken["item_lists"][0]["rows"][0]
    assert row["Receiving Ref"] == "RCV-FSR-202611-0001-1-01"
    assert str(row["Quantity"]) == "1"
    # each report carries when it was last saved; no error notes left in
    assert all(r["last_saved"] for r in data["reports"])
    assert not any("incident_error" in r for r in data["reports"])

    # and the owner's import takes both, each into its own workbook
    owner = tmp_path / "owner"
    owner.mkdir()
    summary = fsr_import.import_master_data(owner / "data.xlsx",
                                            fsr_import.read_master_file(target))
    assert sorted(summary["added"]) == ["FSR-202611-0001", "FSR-202611-0002"]


def test_a_damaged_side_file_stops_the_export(tmp_path):
    from warehouse.store import side_file_path
    path = saved_book(tmp_path)
    side = side_file_path(path)
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text("{not json", encoding="utf-8")
    target = tmp_path / "out.json"
    with pytest.raises(export.MasterExportError, match="cannot be read"):
        export.write_export(path, target, "pc-1")
    assert not target.exists()


def test_the_command_line_writes_the_same_file(tmp_path, monkeypatch,
                                               capsys):
    import runpy
    import sys
    path = saved_book(tmp_path)
    lists = tmp_path / "master_list.json"
    lists.write_text(json.dumps(LISTS), encoding="utf-8")
    target = tmp_path / "cli.json"
    monkeypatch.setattr(sys, "argv", [
        "fsr_master_export.py", str(path), "--device", "pc-cli",
        "--inspector", "Cy", "--out", str(target),
        "--master-list", str(lists)])
    runpy.run_path(export.__file__, run_name="__main__")
    assert capsys.readouterr().out.strip() == \
        f"1 report(s) written to {target}"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert (data["device_id"], data["inspector"]) == ("pc-cli", "Cy")
    assert data["master_lists"]["supplier_list"] == ["Site Supplier"]
    assert [r["control_no"] for r in data["reports"]] == ["FSR-202611-0001"]


# ---------- only the chosen reports (owner's request, 25 November 2026) ----------

def test_saved_reports_lists_both_workbooks(tmp_path):
    path = withdrawal_book(tmp_path)
    rows = export.saved_reports(path)
    assert [(r[0], r[5]) for r in rows] == [
        ("FSR-202611-0002", "withdrawal"), ("FSR-202611-0001", "report")]
    assert rows[0][1] == "SO-W" and rows[1][1] == "SO-R"


def test_only_the_chosen_po_linked_withdrawal_is_exported(tmp_path):
    path = withdrawal_book(tmp_path)
    target = tmp_path / "one.json"
    # the Control # is found whatever its letter case or outer spaces
    assert export.write_export(path, target, "pc-9", "Ben", LISTS,
                               [" fsr-202611-0002 "]) == 1
    data = json.loads(target.read_text(encoding="utf-8"))
    (only,) = data["reports"]
    assert only["control_no"] == "FSR-202611-0002"
    assert only["inspection_schedule"]["activity"] == "Withdrawal"
    assert only["last_saved"]
    assert data["master_lists"]["supplier_list"] == ["Site Supplier"]

    # the owner adds that one report and nothing else
    owner = tmp_path / "owner"
    owner.mkdir()
    summary = fsr_import.import_master_data(owner / "data.xlsx",
                                            fsr_import.read_master_file(target))
    assert summary["added"] == ["FSR-202611-0002"]


def test_a_later_export_of_one_report_removes_nothing_at_the_owner(tmp_path):
    path = withdrawal_book(tmp_path)
    everything = tmp_path / "all.json"
    one = tmp_path / "one.json"
    export.write_export(path, everything, "pc-9")
    export.write_export(path, one, "pc-9", controls=["FSR-202611-0001"])
    owner = tmp_path / "owner"
    owner.mkdir()
    book = owner / "data.xlsx"
    fsr_import.import_master_data(book, fsr_import.read_master_file(everything))
    summary = fsr_import.import_master_data(book,
                                            fsr_import.read_master_file(one))
    assert not summary["added"]
    import fsr_store
    store = fsr_store.open_store(book)
    have = {r[0] for r in store.list_reports()} | set(
        store.withdrawal_numbers())
    assert have == {"FSR-202611-0001", "FSR-202611-0002"}


def test_chosen_reports_carry_only_their_case_statuses(tmp_path):
    path = saved_book(tmp_path)
    other = report("FSR-202611-0009", "Receiving", date(2026, 11, 2), "WH",
                   [{"qty": 1, "unit": "Box", "desc": "Valve"}])
    s.write_report_to_excel(path, other, False)
    SideStore(path).set_case_status("FSR-202611-0001", "Open", user="U")
    SideStore(path).set_case_status("FSR-202611-0009", "Resolved", user="U")
    data = export.build_export(path, "pc-1", controls=["FSR-202611-0009"])
    assert [r["control_no"] for r in data["reports"]] == ["FSR-202611-0009"]
    assert [e["control_no"] for e in data["case_status"]] == [
        "FSR-202611-0009"]


def test_a_damaged_incident_of_another_report_does_not_stop_it(tmp_path):
    path = saved_book(tmp_path)
    other = report("FSR-202611-0009", "Receiving", date(2026, 11, 2), "WH",
                   [{"qty": 1, "unit": "Box", "desc": "Valve"}])
    s.write_report_to_excel(path, other, False)
    s.incident_json_path(path, "FSR-202611-0001").write_text(
        "{broken", encoding="utf-8")
    data = export.build_export(path, "pc-1", controls=["FSR-202611-0009"])
    assert [r["control_no"] for r in data["reports"]] == ["FSR-202611-0009"]
    with pytest.raises(export.MasterExportError):
        export.build_export(path, "pc-1", controls=["FSR-202611-0001"])


def test_a_chosen_report_that_is_gone_stops_the_export(tmp_path):
    path = saved_book(tmp_path)
    target = tmp_path / "out.json"
    with pytest.raises(export.MasterExportError, match="FSR-202611-0404"):
        export.write_export(path, target, "pc-1",
                            controls=["FSR-202611-0001", "FSR-202611-0404"])
    with pytest.raises(export.MasterExportError, match="No report"):
        export.write_export(path, target, "pc-1", controls=[])
    assert not target.exists()


def test_the_command_line_exports_chosen_reports(tmp_path, monkeypatch,
                                                 capsys):
    import runpy
    import sys
    path = withdrawal_book(tmp_path)
    target = tmp_path / "cli.json"
    monkeypatch.setattr(sys, "argv", [
        "fsr_master_export.py", str(path), "--device", "pc-cli",
        "--out", str(target), "--report", "FSR-202611-0002"])
    runpy.run_path(export.__file__, run_name="__main__")
    assert capsys.readouterr().out.strip() == \
        f"1 report(s) written to {target}"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert [r["control_no"] for r in data["reports"]] == ["FSR-202611-0002"]


def test_the_file_name_says_what_is_in_it():
    import fsr_master_export_ui as ui
    day = date(2026, 11, 25)
    assert ui.file_name("MY PC", None, day) == \
        "FSR_Master_Data_MY_PC_2026-11-25.json"
    assert ui.file_name("pc", ["FSR-MPR-202611-0069"], day) == \
        "FSR_Master_Data_pc_FSR-MPR-202611-0069_2026-11-25.json"
    assert ui.file_name("pc", ["A", "B", "C"], day) == \
        "FSR_Master_Data_pc_3_reports_2026-11-25.json"
