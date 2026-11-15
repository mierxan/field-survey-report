"""Import Master Data: reports from the Android app into the Excel file."""
import json
import os
from datetime import date

import pytest

import fsr_import as imp
import fsr_storage as s
from factories import report


def phone_report(control="FSR-202610-0001", so="SO-PHONE", saved="26-Oct-2026 10:00"):
    data = report(control, "Receiving", date(2026, 10, 5), "WH",
                  [{"qty": 2, "unit": "Crate", "desc": "Pump",
                    "ref": f"RCV-{control}-1-01"}], so=so)
    data["declared_goods"] = []
    data["other_important_remarks"] = ["Phone remark"]
    data["findings_and_remarks"] = ["Phone detail"]
    data["last_saved"] = saved
    return data


def test_a_renumbered_phone_report_keeps_its_inspectors_initials(tmp_path):
    book = tmp_path / "data.xlsx"
    s.write_report_to_excel(book, phone_report("FSR-JDC-202611-0001", so="ON-PC"), False)
    summary = imp.import_master_data(book, fresh(master_file(phone_report("FSR-JDC-202611-0001"))))
    (old, new), = summary["renumbered"]
    assert old == "FSR-JDC-202611-0001"
    assert new.startswith("FSR-JDC-") and new.endswith("-0002")


def master_file(*reports, device="phone-1", inspector="Juan Dela Cruz"):
    return {"format": imp.FORMAT, "version": 1, "device_id": device,
            "inspector": inspector, "reports": list(reports),
            "master_lists": {"supplier_list": ["New Co", "old co"]}}


def fresh(data):
    return json.loads(json.dumps(data))


@pytest.fixture
def book(tmp_path):
    return tmp_path / "data.xlsx"


def test_new_report_keeps_phone_number_and_everything_reads_back(book):
    summary = imp.import_master_data(book, fresh(master_file(phone_report())))
    assert summary["added"] == ["FSR-202610-0001"]
    back = s.read_report(book, "FSR-202610-0001")
    assert back["general_information"]["so_number"] == "SO-PHONE"
    assert back["other_important_remarks"] == ["Phone remark"]
    assert back["item_lists"][0]["rows"][0]["Description of Goods"] == "Pump"
    assert imp.imported_inspector(book, "FSR-202610-0001") == "Juan Dela Cruz"


def test_sending_the_same_file_again_changes_nothing(book):
    imp.import_master_data(book, fresh(master_file(phone_report())))
    before = book.read_bytes()
    summary = imp.import_master_data(book, fresh(master_file(phone_report())))
    assert summary["unchanged"] == ["FSR-202610-0001"]
    assert summary["added"] == [] and summary["backup"] is None
    assert book.read_bytes() == before


def test_taken_number_is_renumbered_and_existing_report_untouched(book):
    s.write_report_to_excel(book, phone_report(so="SO-ON-PC"), False)
    summary = imp.import_master_data(book, fresh(master_file(phone_report())))
    (old, new), = summary["renumbered"]
    assert old == "FSR-202610-0001" and new != old
    assert s.read_report(book, old)["general_information"]["so_number"] == "SO-ON-PC"
    moved = s.read_report(book, new)
    assert moved["general_information"]["so_number"] == "SO-PHONE"
    assert moved["item_lists"][0]["rows"][0]["Receiving Ref"] == f"RCV-{new}-1-01"
    assert summary["backup"] and os.path.exists(summary["backup"])


def test_two_phones_with_one_number_both_arrive(book):
    imp.import_master_data(book, fresh(master_file(phone_report(so="A"), device="a")))
    imp.import_master_data(book, fresh(master_file(phone_report(so="B"), device="b")))
    assert len(s.read_all_reports(book)) == 2


def test_change_on_phone_updates_the_same_report(book):
    imp.import_master_data(book, fresh(master_file(phone_report())))
    edited = phone_report(so="SO-EDITED", saved="27-Oct-2026 09:00")
    summary = imp.import_master_data(book, fresh(master_file(edited)))
    assert summary["updated"] == ["FSR-202610-0001"]
    reports = s.read_all_reports(book)
    assert len(reports) == 1
    assert reports[0]["general_information"]["so_number"] == "SO-EDITED"


def test_update_summary_has_every_previous_and_imported_detail(book):
    original = phone_report()
    imp.import_master_data(book, fresh(master_file(original)))

    edited = phone_report(so="SO-EDITED", saved="27-Oct-2026 09:00")
    edited["declared_goods"] = [{
        "description": "Cooling tower components",
        "quantity": "11", "packaging": "Pcs",
    }]
    edited["findings_and_remarks"] = []
    summary = imp.import_master_data(book, fresh(master_file(edited)))

    assert [entry["control"] for entry in summary["changes"]] == [
        "FSR-202610-0001"]
    changes = {entry["path"]: (entry["previous"], entry["imported"])
               for entry in summary["changes"][0]["fields"]}
    assert changes[("general_information", "so_number")] == (
        "SO-PHONE", "SO-EDITED")
    assert changes[("declared_goods", "count")] == ("0", "1")
    assert changes[("declared_goods", 0, "description")] == (
        "(not present)", "Cooling tower components")
    assert changes[("findings_and_remarks", "count")] == ("1", "0")
    assert changes[("findings_and_remarks", 0)] == (
        "Phone detail", "(not present)")
    assert changes[("last_saved",)] == (
        "26-Oct-2026 10:00", "27-Oct-2026 09:00")


def test_changes_of_a_report_sent_twice_show_the_copy_that_is_saved(book):
    imp.import_master_data(book, fresh(master_file(phone_report())))
    first = phone_report(so="SO-FIRST-COPY", saved="27-Oct-2026 09:00")
    later = phone_report(so="SO-LATER-COPY", saved="27-Oct-2026 10:00")
    summary = imp.import_master_data(book, fresh(master_file(first, later)))

    assert s.read_report(book, "FSR-202610-0001")[
        "general_information"]["so_number"] == "SO-LATER-COPY"
    (entry,) = summary["changes"]
    changes = {field["path"]: (field["previous"], field["imported"])
               for field in entry["fields"]}
    assert changes[("general_information", "so_number")] == (
        "SO-PHONE", "SO-LATER-COPY")


def test_changes_of_several_updated_reports_each_compare_their_own(book):
    one = phone_report("FSR-202610-0001", so="SO-ONE")
    two = phone_report("FSR-202610-0002", so="SO-TWO")
    imp.import_master_data(book, fresh(master_file(one, two)))

    summary = imp.import_master_data(book, fresh(master_file(
        phone_report("FSR-202610-0001", so="SO-ONE-EDITED",
                     saved="27-Oct-2026 09:00"),
        phone_report("FSR-202610-0002", so="SO-TWO-EDITED",
                     saved="27-Oct-2026 09:00"))))

    by_control = {
        entry["control"]: {field["path"]: (field["previous"], field["imported"])
                           for field in entry["fields"]}
        for entry in summary["changes"]}
    assert by_control["FSR-202610-0001"][
        ("general_information", "so_number")] == ("SO-ONE", "SO-ONE-EDITED")
    assert by_control["FSR-202610-0002"][
        ("general_information", "so_number")] == ("SO-TWO", "SO-TWO-EDITED")


def test_report_changes_records_edited_added_and_removed_rows():
    changes = imp.report_changes(
        {"rows": [{"Container": "A", "Packaging": "7x40"}],
         "remarks": ["Old detail"]},
        {"rows": [{"Container": "A", "Packaging": "1x40"},
                  {"Container": "B", "Packaging": "1x40"}],
         "remarks": []})
    by_path = {entry["path"]: (entry["previous"], entry["imported"])
               for entry in changes}
    assert by_path[("rows", "count")] == ("1", "2")
    assert by_path[("rows", 0, "Packaging")] == ("7x40", "1x40")
    assert by_path[("rows", 1, "Container")] == (
        "(not present)", "B")
    assert by_path[("remarks", "count")] == ("1", "0")
    assert by_path[("remarks", 0)] == ("Old detail", "(not present)")


def test_update_follows_a_renumbered_report(book):
    s.write_report_to_excel(book, phone_report(so="SO-ON-PC"), False)
    first = imp.import_master_data(book, fresh(master_file(phone_report())))
    _, new = first["renumbered"][0]
    edited = phone_report(so="SO-EDITED", saved="27-Oct-2026 09:00")
    summary = imp.import_master_data(book, fresh(master_file(edited)))
    assert summary["updated"] == [new]
    assert s.read_report(book, new)["general_information"]["so_number"] == "SO-EDITED"
    assert s.read_report(book, "FSR-202610-0001")["general_information"]["so_number"] == "SO-ON-PC"


def test_edit_on_pc_is_not_overwritten(book):
    imp.import_master_data(book, fresh(master_file(phone_report())))
    on_pc = s.read_report(book, "FSR-202610-0001")
    on_pc["general_information"]["so_number"] = "EDITED-ON-PC"
    s.write_report_to_excel(book, on_pc, True)
    edited = phone_report(so="SO-EDITED", saved="27-Oct-2026 09:00")
    summary = imp.import_master_data(book, fresh(master_file(edited)))
    assert summary["conflicts"] == ["FSR-202610-0001"]
    assert s.read_report(book, "FSR-202610-0001")["general_information"]["so_number"] == "EDITED-ON-PC"


def test_report_deleted_on_pc_does_not_come_back(book):
    imp.import_master_data(book, fresh(master_file(phone_report(), phone_report("FSR-202610-0002"))))
    s.delete_reports_from_excel(book, ["FSR-202610-0001"])
    edited = phone_report(so="SO-EDITED", saved="27-Oct-2026 09:00")
    summary = imp.import_master_data(book, fresh(master_file(edited)))
    assert summary["deleted_here"] == ["FSR-202610-0001"]
    assert [r["control_no"] for r in s.read_all_reports(book)] == ["FSR-202610-0002"]


def test_incident_and_other_forms_are_stored(book):
    bad = phone_report()
    bad["cargo_condition"] = s.CONDITION_BAD
    bad["incident_reports"] = [{"vessel": "MV One", "lines": ["Dent"]}]
    row = {h: "" for h in s.ITEM_LINE_HEADERS}
    row.update({"Container / Truck No.": "ABC 123", "Description of Goods": "Pipes"})
    bad["other_item_forms"] = {"Loading": [{"name": "Item List 1", "rows": [row]}]}
    imp.import_master_data(book, fresh(master_file(bad)))
    back = s.read_report(book, "FSR-202610-0001")
    assert back["incident_reports"][0]["lines"] == ["Dent"]
    forms = s.load_other_item_forms(book, "FSR-202610-0001")
    assert forms["Loading"][0]["rows"][0]["Container / Truck No."] == "ABC 123"


@pytest.mark.parametrize("content, message", [
    ("not json", "could not be read"),
    ('{"format": "other"}', "not a Field Survey"),
    ('{"format": "fsr-master-data", "version": 99, "device_id": "x", "reports": []}', "version 99"),
    ('{"format": "fsr-master-data", "version": 1, "reports": []}', "which phone"),
])
def test_bad_files_are_refused(tmp_path, content, message):
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(imp.MasterDataError, match=message):
        imp.read_master_file(path)


def test_report_with_invalid_date_refuses_the_whole_file(tmp_path):
    bad = phone_report()
    bad["general_information"]["inspection_date"] = "soon"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(master_file(bad)), encoding="utf-8")
    with pytest.raises(imp.MasterDataError, match="invalid Inspection Date"):
        imp.read_master_file(path)


def test_new_master_names_ignore_case(tmp_path):
    lists = {"supplier_list": ["Old Co"]}
    new = imp.new_master_names(master_file(), lists)
    assert new == {"supplier_list": ["New Co"]}
    imp.add_master_names(new, lists)
    assert lists["supplier_list"] == ["New Co", "Old Co"]


ANDROID_FILE = (
    r"C:\Users\rojom\AndroidStudioProjects\FieldSurveyReport"
    r"\app\build\test-exports\master_data.json")


@pytest.mark.skipif(not os.path.exists(ANDROID_FILE),
                    reason="needs the file written by the Android unit tests")
def test_file_written_by_the_android_code(book):
    data = imp.read_master_file(ANDROID_FILE)
    summary = imp.import_master_data(book, data)
    assert len(summary["added"]) == 2
    back = s.read_report(book, summary["added"][0])
    assert back["cargo_condition"] == s.CONDITION_BAD
    assert back["goods_types"]["new"] and back["goods_types"]["others_text"] == "Tools"
    assert back["item_lists"][0]["rows"][0]["Weights"] == "1,000 KG"
    assert back["item_lists"][0]["rows"][0]["UOM"] == "PCS"
    assert back["incident_reports"][0]["lines"] == ["Dent on crate"]
    assert back["inspection_schedule"]["commenced_time"] == "0800H"
    assert back["general_information"]["supplier"] == "ABB <PTE> & Co"
    assert "Loading" in s.load_other_item_forms(book, summary["added"][0])


# ---------- the imported data is never changed (renumbering works on a copy) ----------

def two_taken_numbers(book):
    """The owner's PC already has the phone's two numbers."""
    for control, so in (("FSR-202610-0001", "OWNER-1"), ("FSR-202610-0002", "OWNER-2")):
        s.write_report_to_excel(book, phone_report(control, so=so), False)


def test_renumbering_does_not_change_the_imported_data(book):
    two_taken_numbers(book)
    data = fresh(master_file(phone_report("FSR-202610-0001", so="PH-1"),
                             phone_report("FSR-202610-0002", so="PH-2")))
    untouched = fresh(data)
    summary = imp.import_master_data(book, data)
    assert data == untouched                        # numbers and Receiving Refs kept
    pairs = summary["renumbered"]
    assert [old for old, _ in pairs] == ["FSR-202610-0001", "FSR-202610-0002"]
    new_numbers = [new for _, new in pairs]
    assert len(set(new_numbers)) == 2
    assert not {"FSR-202610-0001", "FSR-202610-0002"} & set(new_numbers)
    assert [r["control_no"] for r in summary["saved_reports"]] == new_numbers
    for (_old, new), so in zip(pairs, ("PH-1", "PH-2")):
        moved = s.read_report(book, new)
        assert moved["general_information"]["so_number"] == so
        assert moved["item_lists"][0]["rows"][0]["Receiving Ref"] == f"RCV-{new}-1-01"


def test_the_same_data_object_imported_twice_adds_nothing(book):
    two_taken_numbers(book)
    data = fresh(master_file(phone_report("FSR-202610-0001", so="PH-1"),
                             phone_report("FSR-202610-0002", so="PH-2")))
    first = imp.import_master_data(book, data)
    before = book.read_bytes()
    again = imp.import_master_data(book, data)      # same object, not re-read
    assert again["added"] == [] and again["updated"] == []
    assert sorted(again["unchanged"]) == sorted(first["added"])
    assert book.read_bytes() == before
    assert len(s.list_saved_reports(book)) == 4


def test_owner_reports_are_not_modified_by_an_import(book):
    two_taken_numbers(book)
    owner_before = {c: s.read_report(book, c) for c in ("FSR-202610-0001", "FSR-202610-0002")}
    data = fresh(master_file(phone_report("FSR-202610-0001", so="PH-1"),
                             phone_report("FSR-202610-0002", so="PH-2")))
    imp.import_master_data(book, data)
    imp.import_master_data(book, data)
    for control, before in owner_before.items():
        assert s.read_report(book, control) == before
