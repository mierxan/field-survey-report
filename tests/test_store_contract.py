"""The contract every store must keep (fsr_store).

One set of tests for any implementation of the storage interface: today's
ExcelStore, and later the SQLite store, which must pass this file
UNCHANGED - only a line in STORES is added for it. The tests use nothing
but the store's own methods (and the file of a report form only where the
contract is about files, which is said).
"""
from datetime import date, datetime

import pytest

import fsr_paths
import fsr_sqlite_store
import fsr_store
import fsr_withdrawal
from factories import report


def excel_store(folder, demo=False):
    (folder / "excel").mkdir(parents=True, exist_ok=True)
    (folder / "json").mkdir(exist_ok=True)
    if demo:
        (folder / "excel" / fsr_store.DEMO_MARKER).write_text("test data")
    return fsr_store.ExcelStore(folder / "excel" / "Field_Survey_Reports.xlsx")


STORES = {"excel": excel_store,
          "sqlite": lambda folder, demo=False: fsr_sqlite_store.new_store(
              excel_store(folder, demo).excel_path)}


@pytest.fixture(params=sorted(STORES))
def make(request, tmp_path, monkeypatch):
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    factory = STORES[request.param]
    return lambda demo=False: factory(tmp_path, demo)


@pytest.fixture
def store(make):
    return make()


def receiving(control, so="SO-1", qty=4, po="PO-7", condition="Good Order"):
    data = report(control, "Receiving", date(2026, 11, 5), "WH",
                  [{"qty": qty, "unit": "Crate", "desc": "Pump", "po": po,
                    "cargo": "C-1", "ref": f"RCV-{control}-1-01"}], so=so,
                  condition=condition)
    data["other_item_forms"] = {}
    return data


def withdrawal(control, ref, qty):
    data = report(control, "Withdrawal", date(2026, 11, 6), "WH",
                  [{"qty": qty, "unit": "Crate", "desc": "Pump", "po": "PO-7",
                    "ref": ref}], so="SO-W")
    data["other_item_forms"] = {}
    return data


def so_of(store, control):
    return store.read_report(control)["general_information"]["so_number"]


# ---------- reports ----------

def test_a_written_report_reads_back_the_same(store):
    data = receiving("FSR-MPR-202611-0001", so="SO-ROUND-TRIP")
    result = store.write_report(data, False)
    assert result["control"] == "FSR-MPR-202611-0001"
    assert result["updated"] is False
    back = store.read_report("FSR-MPR-202611-0001")
    for section in ("general_information", "inspection_schedule",
                    "documents_used"):
        for key, value in data[section].items():
            assert str(back[section][key] or "") == str(value or ""), key
    assert back["item_lists"][0]["rows"][0]["Description of Goods"] == "Pump"
    assert [r[0] for r in store.list_reports()] == ["FSR-MPR-202611-0001"]
    assert len(store.read_all_reports()) == 1


def test_writing_again_updates_and_never_duplicates(store):
    store.write_report(receiving("FSR-MPR-202611-0001"), False)
    result = store.write_report(receiving("FSR-MPR-202611-0001",
                                          so="EDITED"), True)
    assert result["updated"] is True
    assert so_of(store, "FSR-MPR-202611-0001") == "EDITED"
    assert len(store.list_reports()) == 1


def test_a_new_report_never_overwrites_one_with_its_number(store):
    store.write_report(receiving("FSR-MPR-202611-0001", so="FIRST"), False)
    result = store.write_report(receiving("fsr-mpr-202611-0001",
                                          so="SECOND"), False)
    assert result["control"] != "FSR-MPR-202611-0001"   # any letter case
    assert so_of(store, "FSR-MPR-202611-0001") == "FIRST"
    assert len(store.list_reports()) == 2


def test_the_planned_last_saved_time_is_kept_to_the_millisecond(store):
    """The save record recognises a save by this time."""
    when = datetime(2026, 11, 13, 9, 30, 15, 125000)
    store.write_report(receiving("FSR-MPR-202611-0001"), False, when)
    (row,) = store.list_reports()
    assert "2026" in str(row[4])
    assert store.save_steps().stamp({"linked": False,
                                     "control": "FSR-MPR-202611-0001"}) == \
        when.isoformat(timespec="milliseconds")


def test_several_reports_in_one_write(store):
    results = store.write_reports([
        (receiving(f"FSR-MPR-202611-{n:04d}", so=f"SO-{n}"), False, None)
        for n in range(1, 6)])
    assert [r["control"] for r in results] == [
        f"FSR-MPR-202611-{n:04d}" for n in range(1, 6)]
    assert len(store.list_reports()) == 5


def test_several_reports_are_all_or_none(store):
    store.write_report(receiving("FSR-MPR-202611-0001", so="BEFORE"), False)
    store.write_withdrawal_report(
        withdrawal("FSR-MPR-202611-0050", "RCV-FSR-MPR-202611-0001-1-01", 1),
        False)
    before = store.list_reports()
    bad = receiving("FSR-MPR-202611-0050")     # a Withdrawal report's number
    with pytest.raises(ValueError):
        store.write_reports([
            (receiving("FSR-MPR-202611-0002", so="NEW"), False, None),
            (receiving("FSR-MPR-202611-0001", so="CHANGED"), True, None),
            (bad, True, None)])                # this one fails
    assert store.list_reports() == before      # nothing of the batch
    assert so_of(store, "FSR-MPR-202611-0001") == "BEFORE"


# ---------- Control #s ----------

def test_control_numbers_cover_both_kinds_of_report(store):
    store.write_report(receiving("FSR-MPR-202611-0001"), False)
    store.write_withdrawal_report(
        withdrawal("FSR-MPR-202611-0002", "RCV-FSR-MPR-202611-0001-1-01", 1),
        False)
    numbers = sorted(store.control_numbers())
    assert numbers == ["FSR-MPR-202611-0001", "FSR-MPR-202611-0002"]
    assert store.owns_withdrawal("fsr-mpr-202611-0002")
    assert not store.owns_withdrawal("FSR-MPR-202611-0001")
    assert store.withdrawal_numbers() == ["FSR-MPR-202611-0002"]
    nxt = store.next_free_number("FSR-MPR-202611-0001")
    assert nxt not in numbers and nxt.upper() not in numbers


def test_renumber_moves_the_report_and_what_belongs_to_it(store):
    store.write_report(receiving("FSR-MPR-202611-0001",
                                 condition="Bad Order"), False)
    store.save_incidents("FSR-MPR-202611-0001", "SO-1",
                         [{"vessel": "MV", "lines": ["Dent"]}])
    store.renumber("FSR-MPR-202611-0001", "FSR-MPR-202611-0009")
    assert [r[0] for r in store.list_reports()] == ["FSR-MPR-202611-0009"]
    assert store.load_incidents("FSR-MPR-202611-0009")[0]["lines"] == [
        "Dent"]
    assert store.load_incidents("FSR-MPR-202611-0001") == []
    rows = store.read_report("FSR-MPR-202611-0009")["item_lists"][0]["rows"]
    assert rows[0]["Receiving Ref"].startswith("RCV-FSR-MPR-202611-0009-")


# ---------- PO lines ----------

def test_po_lines_and_what_is_left_after_a_withdrawal(store):
    store.write_report(receiving("FSR-MPR-202611-0001", qty=10), False)
    (line,) = store.find_po("po-7").lines      # any letter case
    assert line.remaining_qty == 10 and line.control_no == "FSR-MPR-202611-0001"
    store.write_withdrawal_report(
        withdrawal("FSR-MPR-202611-0002", line.receiving_ref, 3), False)
    (line,) = store.find_po("PO-7").lines
    assert line.remaining_qty == 7
    # a row of the Withdrawal being edited does not count against itself
    row = {"Receiving Ref": line.receiving_ref,
           fsr_withdrawal.RECEIVED_HEADER: "10"}
    assert store.remaining_quantity(row) == 7
    assert store.remaining_quantity(row, "FSR-MPR-202611-0002") == 10
    store.write_withdrawal_report(
        withdrawal("FSR-MPR-202611-0003", line.receiving_ref, 7), False)
    assert store.find_po("PO-7").lines == []   # all of it taken
    store.rebuild_item_lists()                 # PO_Master / Withdrawn_Item


# ---------- the data beside a report ----------

def test_incidents_and_item_forms(store):
    store.write_report(receiving("FSR-MPR-202611-0001"), False)
    store.save_incidents("FSR-MPR-202611-0001", "SO-1",
                         [{"vessel": "MV One", "lines": ["Dent", "Wet"]}])
    (incident,) = store.load_incidents("FSR-MPR-202611-0001")
    assert incident["lines"] == ["Dent", "Wet"]
    store.delete_incidents("FSR-MPR-202611-0001")
    assert store.load_incidents("FSR-MPR-202611-0001") == []
    store.save_item_forms("FSR-MPR-202611-0001", {})
    assert store.load_item_forms("FSR-MPR-202611-0001") == {}


# ---------- the records ----------

def test_the_save_record_belongs_to_the_store(store):
    journal = store.save_record()
    data = receiving("FSR-MPR-202611-0001")
    record = journal.begin(data, False, False, ["workbook", "mysql"])
    assert [r["id"] for r in store.save_record().pending()] == [record["id"]]
    journal.remove(record)
    assert store.save_record().pending() == []


def test_the_mysql_ledger_belongs_to_the_store(store):
    guard = store.mysql_guard(None)
    assert not guard.owns("FSR-MPR-202611-0001")
    with guard.local_write():
        store.write_report(receiving("FSR-MPR-202611-0001"), False)
    assert not guard.is_stale()


# ---------- deleting: Demo Mode data only ----------

def test_reports_are_never_deleted_from_real_data(store):
    store.write_report(receiving("FSR-MPR-202611-0001"), False)
    with pytest.raises(fsr_store.StoreRefused, match="not Demo Mode data"):
        store.delete_reports(["FSR-MPR-202611-0001"])
    with pytest.raises(fsr_store.StoreRefused):
        store.delete_reports(["TEST-REC-0001"])  # not even a TEST- number
    assert len(store.list_reports()) == 1


def test_demo_data_deletes_only_sample_reports(make):
    store = make(demo=True)
    store.write_report(receiving("TEST-REC-0001"), False)
    store.write_report(receiving("FSR-MPR-202611-0001", so="TYPED IN DEMO"),
                       False)
    with pytest.raises(fsr_store.StoreRefused, match="Only TEST-"):
        store.delete_reports(["TEST-REC-0001", "FSR-MPR-202611-0001"])
    assert len(store.list_reports()) == 2       # nothing deleted
    assert store.delete_reports(["TEST-REC-0001"]) == 1
    assert [r[0] for r in store.list_reports()] == ["FSR-MPR-202611-0001"]
