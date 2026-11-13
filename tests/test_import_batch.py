"""Import Master Data in one go (Phase 3): one workbook load and one save
for the whole file, and an import cut off midway leaves the data either
fully imported or not imported at all - and says which."""
import json
from datetime import date

import pytest

import fsr_import as imp
import fsr_paths
import fsr_save_journal as j
import fsr_storage as s
from factories import report


class Crash(BaseException):
    """The PC loses power: nothing after this line runs, nothing cleans up."""


def phone_report(control, so="SO-PHONE", saved="26-Oct-2026 10:00",
                 condition="Good Order", activity="Receiving"):
    data = report(control, activity, date(2026, 10, 5), "WH",
                  [{"qty": 2, "unit": "Crate", "desc": "Pump", "po": "PO-1",
                    "ref": f"RCV-{control}-1-01"}], so=so,
                  condition=condition)
    data["incident_reports"] = ([{"vessel": "MV", "lines": ["Dent"]}]
                                if condition == s.CONDITION_BAD else [])
    data["other_item_forms"] = {}
    data["last_saved"] = saved
    return data


def master(*reports, device="phone-1"):
    return json.loads(json.dumps({
        "format": imp.FORMAT, "version": 1, "device_id": device,
        "inspector": "Juan Dela Cruz", "reports": list(reports)}))


def many(count, first=1, **kw):
    return [phone_report(f"FSR-JDC-202610-{n:04d}", so=f"SO-{n}", **kw)
            for n in range(first, first + count)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    (tmp_path / "excel").mkdir()
    (tmp_path / "json").mkdir()
    book = tmp_path / "excel" / "Field_Survey_Reports.xlsx"
    s.write_report_to_excel(book, report(
        "FSR-MPR-202610-0001", "Receiving", date(2026, 10, 1), so="ON-PC"),
        False)
    return book


class Counts:
    """Workbook loads and writes, and save-record writes, per file."""

    def __init__(self, monkeypatch, book):
        from openpyxl.reader import excel
        from openpyxl.workbook import workbook
        self.loads, self.writes, self.records = [], [], 0
        real_read, real_save = excel.ExcelReader.read, workbook.Workbook.save
        real_json = s.write_json_atomic
        counts = self

        def read(reader, *args, **kwargs):
            counts.loads.append(str(getattr(reader.archive, "filename", "")))
            return real_read(reader, *args, **kwargs)

        def save(wb, filename, *args, **kwargs):
            counts.writes.append(str(filename))
            return real_save(wb, filename, *args, **kwargs)

        def write_json(path, data):
            if str(path) == str(j.journal_path(book)):
                counts.records += 1
            return real_json(path, data)

        monkeypatch.setattr(excel.ExcelReader, "read", read)
        monkeypatch.setattr(workbook.Workbook, "save", save)
        monkeypatch.setattr(s, "write_json_atomic", write_json)

    def of(self, names, name):
        return sum(1 for n in names if name in n)


def run_import(book, data, mysql=False):
    journal = j.Journal(book)
    stores = j.Stores(book)
    return imp.import_master_data(book, data, journal=journal, stores=stores,
                                  mysql=mysql)


def numbers(book):
    return sorted(entry[0] for entry in s.list_saved_reports(book))


# ---------- one load, one save ----------

@pytest.mark.parametrize("count", [1, 50, 200])
def test_import_reads_and_writes_the_workbook_once(env, monkeypatch, count):
    book = env
    counts = Counts(monkeypatch, book)
    summary = run_import(book, master(*many(count, activity="Withdrawal")))
    assert len(summary["added"]) == count
    assert counts.of(counts.writes, "Field_Survey_Reports") == 1
    assert counts.of(counts.loads, "Field_Survey_Reports") == 2  # check+write
    assert counts.records <= 2              # on record, then ticked off
    assert len(numbers(book)) == count + 1


def test_receiving_import_rebuilds_po_master_once(env, monkeypatch):
    book = env
    counts = Counts(monkeypatch, book)
    run_import(book, master(*many(30)))
    assert counts.of(counts.writes, "PO_Master") == 1
    assert counts.of(counts.writes, "Withdrawn_Item") == 1
    # the rebuild reads the main workbook once more - not once per report
    assert counts.of(counts.loads, "Field_Survey_Reports") == 3
    po = s.load_workbook(book.with_name(fsr_paths.PO_MASTER_NAME),
                         data_only=True)
    listed = {row[0] for row in po.active.iter_rows(min_row=2,
                                                    values_only=True)}
    assert "FSR-JDC-202610-0030" in listed


def test_import_keeps_what_made_it_safe(env, tmp_path):
    """Validation before any change, one backup, the import record, the
    case-insensitive Control # check, renumbering of taken numbers."""
    book = env
    before = book.read_bytes()
    bad = master(*many(3))
    bad["reports"][2]["general_information"]["so_number"] = ""
    file_path = tmp_path / "FSR_Master_Data_bad.json"
    file_path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(imp.MasterDataError, match="Report 3"):
        imp.read_master_file(file_path)     # the whole file, before writing
    assert book.read_bytes() == before
    assert j.Journal(book).pending() == []

    file = master(phone_report("fsr-mpr-202610-0001", so="PHONE, SAME NO."),
                  *many(2))
    summary = run_import(book, file)
    assert summary["backup"] and len(list(book.parent.glob(
        "*_before_import_*"))) == 1
    (old, new), = summary["renumbered"]        # number taken, any case
    assert old == "fsr-mpr-202610-0001" and new != "FSR-MPR-202610-0001"
    assert s.read_report(book, "FSR-MPR-202610-0001")[
        "general_information"]["so_number"] == "ON-PC"   # untouched
    again = run_import(book, file)              # sending it again
    assert again["added"] == [] and len(again["unchanged"]) == 3
    assert summary["added"] and len(numbers(book)) == 4


def test_the_same_report_twice_in_one_file_is_one_report(env):
    book = env
    first = phone_report("FSR-JDC-202610-0007", so="EARLIER")
    later = phone_report("fsr-jdc-202610-0007", so="LATER",
                         saved="27-Oct-2026 10:00")
    summary = run_import(book, master(first, later))
    assert summary["added"] == ["FSR-JDC-202610-0007"]
    assert s.read_report(book, "FSR-JDC-202610-0007")[
        "general_information"]["so_number"] == "LATER"
    assert len(numbers(book)) == 2


def test_import_record_matches_what_the_workbook_shows(env):
    """The import record keeps each report's Last Saved as the workbook
    shows it (that is how a later import sees whether the PC copy was
    edited) - now taken from the planned time, not by reading back."""
    book = env
    run_import(book, master(*many(3)))
    shown = imp._last_saved_by_control(book)
    for entry in imp.load_ledger(book).values():
        assert entry["pc_saved"] == shown[entry["control"]]
    # an update on the phone is then taken, an edit on the PC protects
    file = master(*many(3, saved="28-Oct-2026 09:00"))
    assert len(run_import(book, file)["updated"]) == 3


def test_incident_and_item_form_files_are_written(env):
    book = env
    run_import(book, master(*many(2, condition=s.CONDITION_BAD)))
    for number in (1, 2):
        control = f"FSR-JDC-202610-{number:04d}"
        assert [r["lines"] for r in s.load_incident_data(book, control)] == [
            ["Dent"]]


# ---------- cut off midway ----------

def test_cut_off_before_the_workbook_write_imports_nothing(env, monkeypatch):
    book = env
    before = book.read_bytes()

    def power_cut(*args, **kwargs):
        raise Crash()

    with pytest.MonkeyPatch.context() as cut:
        cut.setattr(s, "write_reports_to_excel", power_cut)
        # a real power cut: the program cannot clean up its record
        cut.setattr(j.Journal, "discard_batch", lambda self, r: None)
        with pytest.raises(Crash):
            run_import(book, master(*many(20)))
    assert len(j.Journal(book).pending()) == 20       # on record

    # next start
    result = j.repair(j.Journal(book), j.Stores(book))
    lines, attention = j.describe(result)

    assert book.read_bytes() == before
    assert j.Journal(book).pending() == []
    assert imp.load_ledger(book) == {}
    assert attention and len(lines) == 1
    assert "NOTHING was imported" in lines[0] and "20 report(s)" in lines[0]
    # importing again now brings all of them in, once
    assert len(run_import(book, master(*many(20)))["added"]) == 20
    assert len(numbers(book)) == 21


def test_write_that_fails_leaves_no_record_behind(env, monkeypatch):
    """Excel has the file open: the import says so and nothing is on
    record (nothing to finish later)."""
    book = env

    def in_use(*args, **kwargs):
        raise PermissionError("in use")

    monkeypatch.setattr(s, "write_reports_to_excel", in_use)
    with pytest.raises(PermissionError):
        run_import(book, master(*many(5)))
    assert j.Journal(book).pending() == []


@pytest.mark.parametrize("cut_at", ["side_files", "ledger", "lists",
                                    "final_record"])
def test_cut_off_after_the_workbook_write_is_completed(env, cut_at):
    book = env
    calls = {"n": 0}

    def cut(real):
        def run(*args, **kwargs):
            calls["n"] += 1
            if cut_at != "side_files" or calls["n"] == 8:
                raise Crash()
            return real(*args, **kwargs)
        return run

    monkeypatch = pytest.MonkeyPatch()     # undone below, on its own
    if cut_at == "side_files":
        monkeypatch.setattr(imp, "write_side_files",
                            cut(imp.write_side_files))
    elif cut_at == "ledger":
        monkeypatch.setattr(imp, "record_imports", cut(imp.record_imports))
    elif cut_at == "lists":
        monkeypatch.setattr(j.Stores, "item_lists", cut(j.Stores.item_lists))
    else:
        def last_record_write_dies(self, records):
            raise Crash()               # everything done, not ticked off
        monkeypatch.setattr(j.Journal, "save_many", last_record_write_dies)
    try:
        with pytest.raises(Crash):
            run_import(book, master(*many(20, condition=s.CONDITION_BAD)))
    finally:
        monkeypatch.undo()
    assert len(numbers(book)) == 21             # the workbook holds them

    rebuilt = []
    real_sync = j.fsr_withdrawal.sync_item_lists
    with pytest.MonkeyPatch.context() as watch:
        watch.setattr(j.fsr_withdrawal, "sync_item_lists",
                      lambda path: rebuilt.append(path) or real_sync(path))
        result = j.repair(j.Journal(book), j.Stores(book))
    lines, attention = j.describe(result)

    assert len(rebuilt) <= 1                    # once, not once per report
    assert j.Journal(book).pending() == []
    assert len(numbers(book)) == 21             # not one more
    assert len(imp.load_ledger(book)) == 20     # all on the import record
    for number in range(1, 21):
        control = f"FSR-JDC-202610-{number:04d}"
        assert s.load_incident_data(book, control)[0]["lines"] == ["Dent"]
    assert attention and len(lines) == 1
    assert "Everything was imported" in lines[0]
    # sending the file again changes nothing
    again = run_import(book, master(*many(20, condition=s.CONDITION_BAD)))
    assert again["added"] == [] and len(again["unchanged"]) == 20


def test_imported_reports_wait_for_mysql_in_the_record(env):
    book = env
    run_import(book, master(*many(4)), mysql=True)
    waiting = j.waiting_for_mysql(j.Journal(book))
    assert len(waiting) == 4
    assert all(j.local_complete(r) for r in waiting)
