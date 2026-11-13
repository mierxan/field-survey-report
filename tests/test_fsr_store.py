"""fsr_store.ExcelStore - the one storage interface - gives exactly what
the storage functions it hands on to give (Phase 4: nothing is done
differently, only from one place)."""
from datetime import date, datetime

import pytest

import fsr_paths
import fsr_save_journal
import fsr_storage as s
import fsr_store
import fsr_withdrawal
from factories import report


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    (tmp_path / "excel").mkdir()
    (tmp_path / "json").mkdir()
    return fsr_store.ExcelStore(tmp_path / "excel" / "Field_Survey_Reports.xlsx")


def receiving(control, so="SO-1"):
    data = report(control, "Receiving", date(2026, 11, 5), "WH",
                  [{"qty": 4, "unit": "Crate", "desc": "Pump", "po": "PO-7",
                    "ref": f"RCV-{control}-1-01"}], so=so)
    data["other_item_forms"] = {}
    return data


def test_reports_round_trip_as_the_functions_do(store):
    when = datetime(2026, 11, 13, 9, 30, 0, 125000)
    result = store.write_report(receiving("FSR-MPR-202611-0001"), False,
                                when)
    assert result["control"] == "FSR-MPR-202611-0001"
    store.write_reports([(receiving("FSR-MPR-202611-0002", so="SO-2"), False,
                          None)])
    book = store.excel_path
    assert store.list_reports() == s.list_saved_reports(book)
    assert store.read_report("FSR-MPR-202611-0001") == s.read_report(
        book, "FSR-MPR-202611-0001")
    assert store.read_all_reports() == s.read_all_reports(book)
    assert store.search_index() == s.search_index_excel(book)
    assert store.next_control_number() == s.generate_control_number(book)
    assert sorted(store.control_numbers()) == [
        "FSR-MPR-202611-0001", "FSR-MPR-202611-0002"]
    assert store.next_free_number("FSR-MPR-202611-0001") not in \
        store.control_numbers()


def test_side_files_and_lists(store):
    store.write_report(receiving("FSR-MPR-202611-0001"), False)
    store.save_incidents("FSR-MPR-202611-0001", "SO-1",
                         [{"vessel": "MV", "lines": ["Dent"]}])
    assert [r["lines"] for r in store.load_incidents(
        "FSR-MPR-202611-0001")] == [["Dent"]]
    store.delete_incidents("FSR-MPR-202611-0001")
    assert store.load_incidents("FSR-MPR-202611-0001") == []
    store.save_item_forms("FSR-MPR-202611-0001", {})
    assert store.load_item_forms("FSR-MPR-202611-0001") == {}
    store.rebuild_item_lists()
    assert store.excel_path.with_name(fsr_paths.PO_MASTER_NAME).exists()
    assert store.find_po("PO-7") == fsr_withdrawal.find_po(
        store.excel_path, "PO-7")


def test_records_belong_to_the_same_workbook(store):
    assert store.save_record().path == fsr_save_journal.journal_path(
        store.excel_path)
    assert store.save_steps().excel_path == store.excel_path
    assert store.mysql_guard(None).excel_path == store.excel_path
    assert store.withdrawal_path == fsr_paths.withdrawal_workbook_path(
        store.excel_path)
    assert store.owns_withdrawal("FSR-MPR-202611-0001") is False
    assert store.withdrawal_numbers() == []
    assert store.read_all_withdrawal_reports() == []


def test_renumber_through_the_store(store):
    store.write_report(receiving("FSR-MPR-202611-0001"), False)
    store.renumber("FSR-MPR-202611-0001", "FSR-MPR-202611-0009")
    assert [r[0] for r in store.list_reports()] == ["FSR-MPR-202611-0009"]
