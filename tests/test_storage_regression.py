"""Regression tests of the EXISTING storage behaviour (moved unchanged into
fsr_storage.py) plus the two new Item List columns."""

import json
from datetime import date, datetime

import pytest
from openpyxl import Workbook, load_workbook

import fsr_storage as s
from factories import rec, report

YEAR = datetime.now().strftime("%Y%m")   # control numbers: FSR-YYYYMM-0001


def full_report(control="", condition="Good Order"):
    data = report(control, "Receiving", date(2026, 10, 5), "EDC-DHL Warehouse",
                  [{"cargo": "CID-1", "qty": 12, "unit": "pcs",
                    "desc": "Gate Valve", "po": "PO-77"},
                   {"qty": 3, "unit": "sets", "desc": "Bolts"}],
                  condition=condition)
    data["declared_goods"] = [{"description": "Valves", "quantity": "12 boxes",
                               "packaging": "crate"}]
    data["other_important_remarks"] = ["Remark one", "Remark two"]
    data["findings_and_remarks"] = ["Finding A"]
    data["documents_used"]["bl_awb_number"] = "BL-1"
    data["transport_details"]["vehicle_plate_number"] = "ABC 123"
    data["goods_types"]["others"] = True
    data["goods_types"]["others_text"] = "Tools"
    return data


def test_control_numbers(tmp_path):
    path = tmp_path / "Reports.xlsx"
    assert s.generate_control_number(path) == f"FSR-{YEAR}-0001"
    first = full_report(f"FSR-{YEAR}-0001")
    s.write_report_to_excel(path, first, editing=False)
    assert s.generate_control_number(path) == f"FSR-{YEAR}-0002"
    assert s.next_control_number([f"FSR-{YEAR}-0009", "x"]) == \
        f"FSR-{YEAR}-0010"
    # numbers of other months or the old yearly format do not count
    assert s.next_control_number(["FSR-190001-0042", "FSR-2026-0042"]) == \
        f"FSR-{YEAR}-0001"


def test_save_and_read_back_everything(tmp_path):
    path = tmp_path / "Reports.xlsx"
    data = full_report(f"FSR-{YEAR}-0001")
    result = s.write_report_to_excel(path, data, editing=False)
    assert result == {"control": f"FSR-{YEAR}-0001", "updated": False,
                      "goods": 1, "items": 2, "remarks": 3}
    back = s.read_report(path, f"FSR-{YEAR}-0001")
    assert back["general_information"]["so_number"] == "SO-1"
    assert back["general_information"]["inspection_date"] == "05-Oct-2026"
    assert back["inspection_schedule"]["activity"] == "Receiving"
    assert back["documents_used"]["bl_awb_number"] == "BL-1"
    assert back["transport_details"]["vehicle_plate_number"] == "ABC 123"
    assert back["declared_goods"][0]["quantity"] == "12 boxes"
    assert back["other_important_remarks"] == ["Remark one", "Remark two"]
    assert back["findings_and_remarks"] == ["Finding A"]
    assert back["goods_types"]["new"] and back["goods_types"]["others"]
    assert back["goods_types"]["others_text"] == "Tools"
    rows = back["item_lists"][0]["rows"]
    assert rows[0]["Quantity"] == "12" and rows[0]["PO Number"] == "PO-77"
    assert rows[0]["Cargo ID"] == "CID-1"
    # Receiving lines get a Receiving Ref when saved
    assert rows[0]["Receiving Ref"] == f"RCV-FSR-{YEAR}-0001-1-01"
    assert rows[1]["Receiving Ref"] == f"RCV-FSR-{YEAR}-0001-1-02"


def test_editing_updates_in_place(tmp_path):
    path = tmp_path / "Reports.xlsx"
    data = full_report(f"FSR-{YEAR}-0001")
    s.write_report_to_excel(path, data, editing=False)
    data["general_information"]["supplier"] = "New Supplier"
    data["item_lists"][0]["rows"] = data["item_lists"][0]["rows"][:1]
    result = s.write_report_to_excel(path, data, editing=True)
    assert result["updated"] is True
    assert len(s.list_saved_reports(path)) == 1
    back = s.read_report(path, f"FSR-{YEAR}-0001")
    assert back["general_information"]["supplier"] == "New Supplier"
    assert len(back["item_lists"][0]["rows"]) == 1
    # the saved Receiving Ref stays the same on later saves
    assert back["item_lists"][0]["rows"][0]["Receiving Ref"] == \
        f"RCV-FSR-{YEAR}-0001-1-01"


def test_uom_and_currency_columns_round_trip(tmp_path):
    path = tmp_path / "Reports.xlsx"
    data = full_report(f"FSR-{YEAR}-0001")
    data["item_lists"][0]["rows"][0].update(
        {"UOM": "PCS", "Currency": "JPY", "Unit Price": "1,500.00"})
    s.write_report_to_excel(path, data, editing=False)
    s.write_report_to_excel(path, data, editing=True)    # heading kept
    assert [c.value for c in load_workbook(path)["Item List"][1]] == \
        s.ITEM_SHEET_HEADERS
    row = s.read_report(path, f"FSR-{YEAR}-0001")["item_lists"][0]["rows"][0]
    assert (row["Quantity"], row["UOM"], row["Packaging"]) == \
        ("12", "PCS", "pcs")
    assert (row["Currency"], row["Unit Price"]) == ("JPY", "1,500.00")


def test_new_report_never_overwrites_existing_number(tmp_path):
    path = tmp_path / "Reports.xlsx"
    s.write_report_to_excel(path, full_report(f"FSR-{YEAR}-0001"), False)
    result = s.write_report_to_excel(path, full_report(f"FSR-{YEAR}-0001"),
                                     editing=False)
    assert result["control"] == f"FSR-{YEAR}-0002"
    assert len(s.list_saved_reports(path)) == 2


def test_withdrawal_lines_get_no_automatic_ref(tmp_path):
    path = tmp_path / "Reports.xlsx"
    data = report("FSR-X-1", "Withdrawal", date(2026, 10, 5), lines=[
        {"cargo": "CID-1", "qty": 2}])
    s.write_report_to_excel(path, data, True)
    row = s.read_report(path, "FSR-X-1")["item_lists"][0]["rows"][0]
    assert row["Receiving Ref"] == "" and row["Cargo ID"] == "CID-1"


def test_bad_order_and_incident_json(tmp_path):
    path = tmp_path / "Reports.xlsx"
    data = full_report(f"FSR-{YEAR}-0001", condition="Bad Order")
    s.write_report_to_excel(path, data, False)
    cards = [{"vessel": "V", "client": "C", "so_number": "SO-1",
              "date": "05-Oct-2026", "operation": "Receiving",
              "lines": ["Crate broken", "  ", "Wet"]}]
    written = s.save_incident_data(path, f"FSR-{YEAR}-0001", "SO-1", cards)
    assert written.exists()
    back = s.read_report(path, f"FSR-{YEAR}-0001")
    assert back["cargo_condition"] == "Bad Order"
    assert back["incident_reports"][0]["lines"] == ["Crate broken", "Wet"]
    s.delete_incident_data(path, f"FSR-{YEAR}-0001")
    assert not written.exists()


def test_reports_saved_before_the_update_still_open(tmp_path):
    """An older workbook: 'UOM' heading, no Findings / link columns."""
    path = tmp_path / "Old.xlsx"
    wb = Workbook()
    wb.remove(wb.active)
    reports = wb.create_sheet("Reports")
    reports.append(["Control #", "SO Number", "Inspection Date", "Activity",
                    "Cargo Condition"])
    reports.append(["FSR-2025-0001", "SO-OLD", datetime(2025, 3, 1),
                    "Receiving", "Good Order"])
    items = wb.create_sheet("Item List")
    items.append(["Control #", "Item List", "Line No", "Description of Goods",
                  "PO Number", "UOM", "Quantity"])
    items.append(["FSR-2025-0001", "Item List 1", 1, "Old pump", "PO-1",
                  "pcs", 4])
    wb.save(path)
    back = s.read_report(path, "FSR-2025-0001")
    row = back["item_lists"][0]["rows"][0]
    assert row["Description of Goods"] == "Old pump" and row["Quantity"] == "4"
    assert row["Cargo ID"] == "" and row["Receiving Ref"] == ""
    assert len(s.read_all_reports(path)) == 1
    # saving a new report upgrades the file and keeps the old one
    s.write_report_to_excel(path, full_report("FSR-2025-0002"), False)
    ws = load_workbook(path)["Item List"]
    assert [c.value for c in ws[1]] == s.ITEM_SHEET_HEADERS
    assert s.read_report(path, "FSR-2025-0001")["item_lists"][0]["rows"][0][
        "Packaging"] == "pcs"


def test_foreign_workbook_is_refused(tmp_path):
    path = tmp_path / "Other.xlsx"
    wb = Workbook()
    wb.active.title = "Reports"
    wb.active.append(["Something", "Else"])
    wb.save(path)
    with pytest.raises(ValueError, match="different"):
        s.list_saved_reports(path)


def test_search_index_and_list(tmp_path):
    path = tmp_path / "Reports.xlsx"
    s.write_report_to_excel(path, full_report(f"FSR-{YEAR}-0001"), False)
    index = s.search_index_excel(path)[f"FSR-{YEAR}-0001"]
    assert "BL-1" in index["bl"] and "Gate Valve" in index["description"]
    listed = s.list_saved_reports(path)
    assert listed[0][:3] == (f"FSR-{YEAR}-0001", "SO-1", "05-Oct-2026")


def test_read_all_reports_equals_read_report(tmp_path):
    path = tmp_path / "Reports.xlsx"
    for n in range(1, 4):
        s.write_report_to_excel(path, full_report(f"FSR-{YEAR}-000{n}"), True)
    bulk = {r["control_no"]: r for r in s.read_all_reports(path)}
    for control in bulk:
        assert bulk[control] == s.read_report(path, control)


def test_delete_reports_only_removes_named(tmp_path):
    path = tmp_path / "Reports.xlsx"
    for control in ("TEST-REC-0001", "FSR-2026-0001"):
        s.write_report_to_excel(path, rec(control, date(2026, 1, 1), "C", 1),
                                True)
    assert s.delete_reports_from_excel(path, ["TEST-REC-0001"]) == 1
    assert [r["control_no"] for r in s.read_all_reports(path)] == \
        ["FSR-2026-0001"]


def test_master_list_file_is_valid_json():
    data = json.loads((s.Path(__file__).resolve().parent.parent /
                       "master_list.json").read_text(encoding="utf-8"))
    for key in ("consignee_list", "supplier_list", "broker_list",
                "hauler_list", "location_list", "destination_list",
                "country_of_origin_list"):
        assert isinstance(data[key], list)


def test_date_and_time_normalisation():
    assert s.normalize_field("5-oct-2026", "date") == "05-Oct-2026"
    assert s.normalize_field("1800", "time") == "1800H"
    assert s.normalize_field("18:00", "time") == "1800H"
    assert s.normalize_field("2500", "time") is None
    assert s.goods_types_from_text(
        s.goods_types_to_text({"new": True, "others": True,
                               "others_text": "Tools; misc"}))[
        "others_text"] == "Tools; misc"
