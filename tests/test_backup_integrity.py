"""Every backup is made safely and checked after it is written.

* The database (daily backup, the copy before an import) is copied with
  SQLite's own backup method - correct even while another connection
  writes - and then checked with SQLite's integrity check; a copy that fails
  is removed and the backup reported as not made.
* Plain file copies (the workbooks and JSON files before the move into the
  database; the workbook's daily backup and its copy before an import while
  the reports are still in the workbook) must hold exactly the bytes of the
  file.
Invented data in temporary folders."""
import threading
from datetime import date, datetime

import pytest

import fsr_backup
import fsr_paths
import fsr_sqlite_migrate as migrate
import fsr_sqlite_store as sq
import fsr_store
from factories import report

WHEN = datetime(2026, 11, 14, 9, 0, 0)


def receiving(control, lines=5):
    data = report(control, "Receiving", date(2026, 11, 5), "WH",
                  [{"qty": n + 1, "unit": "Box", "desc": f"Part {n}",
                    "po": "PO-1"} for n in range(lines)])
    data["other_item_forms"] = {}
    return data


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    (tmp_path / "excel").mkdir()
    store = sq.new_store(tmp_path / "excel" / "Field_Survey_Reports.xlsx")
    store.write_report(receiving("FSR-BAK-202611-0001"), False, WHEN)
    return store


def complete(path):
    """The reports of a database file - each must have all 5 lines."""
    copy = sq.SqliteStore(path.with_name("Field_Survey_Reports.xlsx"),
                          db_path=path)
    reports = copy.read_all_reports()
    return reports, [r["control_no"] for r in reports
                     if len(r["item_lists"][0]["rows"]) != 5]


def test_daily_backups_taken_while_the_program_writes(store):
    stop = threading.Event()
    written = []

    def keep_writing():
        number = 2
        while not stop.is_set():
            store.write_report(receiving(f"FSR-BAK-202611-{number:04d}"),
                               False, WHEN)
            written.append(number)
            number += 1

    writer = threading.Thread(target=keep_writing, daemon=True)
    writer.start()
    try:
        made = []
        for day in range(1, 6):                     # five days' backups
            result = fsr_backup.backup_before_save(
                store.db_path, 14, today=date(2026, 11, day),
                copy=store.copy_to)
            made.append(result["created"])
    finally:
        stop.set()
        writer.join(10)
    assert len(written) > 5                         # it really did write
    for copy in made:
        assert sq.integrity_problem(copy) is None
        reports, half_written = complete(copy)
        assert reports and half_written == []       # never half a report
    assert not list(store.excel_path.parent.glob("Backups/*.tmp"))


def test_a_copy_that_fails_its_integrity_check_is_not_kept(store,
                                                           monkeypatch):
    monkeypatch.setattr(sq, "integrity_problem",
                        lambda path: "Page 7 is never used")
    with pytest.raises(fsr_backup.BackupError, match="integrity check"):
        store.backup_before_save(14)
    folder = store.excel_path.parent / fsr_backup.FOLDER_NAME
    assert not folder.exists() or list(folder.iterdir()) == []


def test_the_integrity_check_finds_a_damaged_file(store, tmp_path):
    good = tmp_path / "good.sqlite3"
    store.copy_to(good)
    assert sq.integrity_problem(good) is None
    data = bytearray(good.read_bytes())
    page = int.from_bytes(data[16:18], "big")       # the page size
    data[page] = 0x00                # the type byte of page 2: no such type
    damaged = tmp_path / "damaged.sqlite3"
    damaged.write_bytes(bytes(data))
    assert "malformed" in sq.integrity_problem(damaged)
    junk = tmp_path / "junk.sqlite3"
    junk.write_bytes(b"this is not a database" * 100)
    assert "not a database" in sq.integrity_problem(junk)


def test_the_copy_before_an_import_is_checked(store, monkeypatch):
    import fsr_import
    before = [r[0] for r in store.list_reports()]
    monkeypatch.setattr(sq, "integrity_problem", lambda path: "damaged")
    data = {"format": fsr_import.FORMAT, "version": 1, "device_id": "phone",
            "reports": [dict(receiving("FSR-IMP-202611-0001"),
                             last_saved="01-Nov-2026 10:00")]}
    with pytest.raises(Exception, match="integrity check"):
        store.import_master_data(data)
    assert [r[0] for r in store.list_reports()] == before   # nothing in
    assert not list(store.excel_path.parent.glob("*_before_import_*"))


# ---------- the workbook (plain file copies, checked) ----------

@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    (tmp_path / "excel").mkdir()
    path = tmp_path / "excel" / "Field_Survey_Reports.xlsx"
    fsr_store.ExcelStore(path).write_report(receiving("FSR-BAK-202611-0001"),
                                            False, WHEN)
    return path


def torn_copy(source, target, *args, **kwargs):
    """A copy cut short, as when the file is written while it is copied."""
    data = open(source, "rb").read()
    open(target, "wb").write(data[: len(data) // 2])


def test_the_workbooks_daily_backup_is_checked(book, monkeypatch):
    monkeypatch.setattr(fsr_backup.shutil, "copy2", torn_copy)
    with pytest.raises(fsr_backup.BackupError, match="not the same"):
        fsr_backup.backup_before_save(book, 14)
    assert not list((book.parent / fsr_backup.FOLDER_NAME).glob("*"))


def test_the_copy_before_the_move_is_checked(book, monkeypatch):
    monkeypatch.setattr(fsr_backup.shutil, "copy2", torn_copy)
    result = migrate.migrate(book)
    assert result.status == "kept"
    assert "did not pass its check" in result.message
    assert fsr_store.open_store(book).kind == "excel"


def test_a_save_in_excel_during_the_backup_keeps_the_workbook(book,
                                                              monkeypatch):
    real = migrate.backup

    def meanwhile(*args, **kwargs):
        folder = real(*args, **kwargs)
        fsr_store.ExcelStore(book).write_report(       # saved in Excel
            receiving("FSR-BAK-202611-0002"), False, WHEN)
        return folder
    monkeypatch.setattr(migrate, "backup", meanwhile)
    result = migrate.migrate(book)
    assert result.status == "kept"
    assert "changed while the reports were being moved" in result.message
    assert fsr_store.open_store(book).kind == "excel"


def test_the_copy_before_an_import_into_the_workbook_is_checked(
        book, monkeypatch):
    import fsr_import
    monkeypatch.setattr(fsr_backup.shutil, "copy2", torn_copy)
    data = {"format": fsr_import.FORMAT, "version": 1, "device_id": "phone",
            "reports": [dict(receiving("FSR-IMP-202611-0001"),
                             last_saved="01-Nov-2026 10:00")]}
    with pytest.raises(fsr_backup.BackupError):
        fsr_store.ExcelStore(book).import_master_data(data)
    assert "FSR-IMP-202611-0001" not in fsr_store.ExcelStore(
        book).control_numbers()
