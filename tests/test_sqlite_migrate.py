"""Moving a workbook into its database (fsr_sqlite_migrate): the backup,
the comparison, what makes the program stay on the workbook, an export
changed outside the program, the way back, the MySQL ledger, and Master
Data files between the previous version (workbook) and this one.

Invented data in temporary folders only."""
import json
import shutil
from datetime import date, datetime

import pytest
from openpyxl import load_workbook

import fsr_db_location as location
import fsr_import
import fsr_master_export
import fsr_mysql_guard
import fsr_paths
import fsr_sqlite_export as export
import fsr_sqlite_migrate as migrate
import fsr_sqlite_store as sq
import fsr_storage
import fsr_store
from factories import report

WHEN = datetime(2026, 11, 13, 10, 0, 0, 125000)
NOW = datetime(2026, 11, 13, 12, 0, 0)


def receiving(control, so="SO-M", qty=4, condition="Good Order"):
    data = report(control, "Receiving", date(2026, 11, 5), "WH-M",
                  [{"qty": qty, "unit": "Crate", "desc": "Pump", "po": "PO-M",
                    "cargo": "C-1"}], so=so, condition=condition)
    data["other_item_forms"] = {}
    return data


def withdrawal(control, ref, qty):
    data = report(control, "Withdrawal", date(2026, 11, 6), "WH-M",
                  [{"qty": qty, "unit": "Crate", "desc": "Pump", "po": "PO-M",
                    "ref": ref}], so="SO-W")
    data["item_lists"][0]["rows"][0].update({
        "PO Line No": "1", "Source Control #": "", "Received Quantity": "4"})
    data["other_item_forms"] = {}
    return data


@pytest.fixture
def book(tmp_path):
    """A workbook with two reports (one Bad Order with its incident file)
    and a PO-linked Withdrawal report in the Withdrawal workbook."""
    path = tmp_path / "Field_Survey_Reports.xlsx"
    store = fsr_store.ExcelStore(path)
    store.write_report(receiving("FSR-MIG-202611-0001"), False, WHEN)
    store.write_report(receiving("FSR-MIG-202611-0002", so="SO-BAD",
                                 condition="Bad Order"), False, WHEN)
    store.save_incidents("FSR-MIG-202611-0002", "SO-BAD",
                         [{"vessel": "MV", "lines": ["Torn bag"]}])
    store.write_withdrawal_report(
        withdrawal("FSR-MIG-202611-0003", "RCV-FSR-MIG-202611-0001-1-01", 1),
        False, WHEN)
    return path


def aside(book, label):
    """The database of `book` set aside (in the databases' folder)."""
    db = location.default_db_path(book)
    return db.with_name(f"{db.name}.{label}_20261113_120000")


def files_of(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                  if p.is_file())


# ---------- the move ----------

def test_the_reports_move_in_and_everything_is_backed_up_first(book):
    before = {p: p.read_bytes() for p in (
        book, book.with_name(fsr_paths.WITHDRAWAL_WORKBOOK_NAME))}
    result = migrate.migrate(book, now=NOW)
    assert result.status == "migrated", result.message
    assert result.details["reports"] == (2, 1)
    assert "3 report(s) were moved" in result.message
    folder = book.parent / "Backups" / "before_sqlite_20261113_120000"
    assert result.details["backup"] == str(folder)
    copied = files_of(folder)
    assert "Field_Survey_Reports.xlsx" in copied
    assert fsr_paths.WITHDRAWAL_WORKBOOK_NAME in copied
    assert "json/Incident Reports/FSR-MIG-202611-0002.json" in copied
    assert not [c for c in copied if c.startswith("export_check")]
    for path, data in before.items():           # the copies are unchanged
        assert (folder / path.name).read_bytes() == data
    store = fsr_store.open_store(book)
    assert store.kind == "sqlite"
    # the database is in the databases' folder (Local AppData), never next
    # to the workbook; the Excel files are written from it at once and
    # carry its id
    assert store.db_path.parent == location.database_dir()
    assert not location.legacy_db_path(book).exists()
    for path in before:
        assert location.workbook_identity(path) == store.database_id
    assert [r[0] for r in store.list_reports()] == ["FSR-MIG-202611-0002",
                                                    "FSR-MIG-202611-0001"]
    assert store.read_report("FSR-MIG-202611-0002")["incident_reports"][0][
        "lines"] == ["Torn bag"]
    assert store.withdrawal_numbers() == ["FSR-MIG-202611-0003"]
    # the files as they are count as the export: not changed outside
    assert export.changed_outside(store) == []
    assert export.is_current(store)
    # once is enough
    assert migrate.migrate(book).status == "active"


def test_a_new_pc_starts_with_an_empty_database(tmp_path):
    path = tmp_path / "Field_Survey_Reports.xlsx"
    assert migrate.migrate(path).status == "new"
    store = fsr_store.open_store(path)
    assert store.kind == "sqlite" and store.list_reports() == []
    store.write_report(receiving("FSR-MIG-202611-0001"), False, WHEN)
    export.write_export(store)
    assert fsr_storage.read_report(path, "FSR-MIG-202611-0001")[
        "general_information"]["so_number"] == "SO-M"
    assert not path.with_name(fsr_paths.WITHDRAWAL_WORKBOOK_NAME).exists()


def test_any_difference_keeps_the_workbook_and_says_what(book, monkeypatch):
    real = sq.load_header

    def damaged(text):
        values = real(text)
        if values.get("Control #") == "FSR-MIG-202611-0001":
            values["SO Number"] = "SO-WRONG"
        return values
    monkeypatch.setattr(sq, "load_header", damaged)
    before = book.read_bytes()
    result = migrate.migrate(book, now=NOW)
    assert result.status == "kept"
    assert "were not the same" in result.message
    assert "FSR-MIG-202611-0001" in result.message
    assert "SO-WRONG" in result.message and "'SO-M'" in result.message
    assert fsr_store.open_store(book).kind == "excel"     # as before
    assert book.read_bytes() == before
    assert not sq.is_active(book)
    assert aside(book, "not_used").exists()
    # not tried again while the workbook is the same ...
    monkeypatch.setattr(sq, "load_header", real)
    assert migrate.migrate(book).status == "skipped"
    # ... but once it changed
    fsr_store.ExcelStore(book).write_report(receiving("FSR-MIG-202611-0009"),
                                            False, WHEN)
    assert migrate.migrate(book).status == "migrated"


def test_a_difference_in_the_export_keeps_the_workbook(book, monkeypatch):
    real = export.main_workbook

    def wrong(headers, rows, *more):
        wb = real(headers, rows, *more)
        wb["Item List"]["D2"] = "changed"
        return wb
    monkeypatch.setattr(export, "main_workbook", wrong)
    result = migrate.migrate(book)
    assert result.status == "kept"
    assert 'sheet "Item List", row 2' in result.message
    assert fsr_store.open_store(book).kind == "excel"


def test_a_sheet_the_program_did_not_make_keeps_the_workbook(book):
    wb = load_workbook(book)
    wb.create_sheet("My notes")["A1"] = "keep me"
    wb.save(book)
    result = migrate.migrate(book)
    assert result.status == "kept"
    assert "My notes" in result.message
    assert fsr_store.open_store(book).kind == "excel"


def test_cells_beside_the_columns_keep_the_workbook(book):
    wb = load_workbook(book)
    wb["Remarks"]["H2"] = "a note beside the table"
    wb.save(book)
    result = migrate.migrate(book)
    assert result.status == "kept" and "to the right" in result.message


def test_two_reports_with_one_number_keep_the_workbook(book):
    wb = load_workbook(book)
    ws = wb["Reports"]
    ws.append([c.value for c in ws[2]])
    wb.save(book)
    result = migrate.migrate(book)
    assert result.status == "kept" and "used by two reports" in result.message


def test_a_workbook_open_in_excel_is_tried_again_later(book, monkeypatch):
    def in_use(*args, **kwargs):
        raise PermissionError("in use")
    monkeypatch.setattr(migrate, "read_rows", in_use)
    result = migrate.migrate(book)
    assert result.status == "kept" and "open in another program" in \
        result.message
    assert fsr_store.open_store(book).kind == "excel"


def test_an_older_layout_moves_with_its_values(tmp_path):
    """A workbook of an earlier version: no Item List Form / Last Saved
    columns, the old "UOM" heading."""
    path = tmp_path / "Field_Survey_Reports.xlsx"
    store = fsr_store.ExcelStore(path)
    store.write_report(receiving("FSR-202610-0001"), False, WHEN)
    wb = load_workbook(path)
    ws = wb["Reports"]
    for name in ("Last Saved", "Item List Form"):
        column = [c.value for c in ws[1]].index(name) + 1
        ws.delete_cols(column)
    for table in list(ws.tables):
        del ws.tables[table]
    items = wb["Item List"]
    for cell in items[1]:
        if cell.value == "Packaging":
            cell.value = "UOM"
    for table in list(items.tables):
        del items.tables[table]
    wb.save(path)
    before = fsr_store.ExcelStore(path).read_all_reports()
    assert migrate.migrate(path).status == "migrated"
    assert fsr_store.open_store(path).read_all_reports() == before


# ---------- the MySQL ledger keeps its trust ----------

def test_a_current_mysql_ledger_stays_current(book):
    guard = fsr_mysql_guard.Guard(None, book)
    with guard.local_write():
        fsr_store.ExcelStore(book).write_report(
            receiving("FSR-MIG-202611-0004"), False, WHEN)
    assert guard.path.exists() and not guard.is_stale()
    assert migrate.migrate(book).status == "migrated"
    assert not guard.is_stale()                  # now about the database
    store = fsr_store.open_store(book)
    with guard.local_write():
        store.write_report(receiving("FSR-MIG-202611-0005"), False, WHEN)
    assert not guard.is_stale()
    export.write_export(store)                   # the export changes ...
    assert not guard.is_stale()                  # ... the ledger is fine
    store.write_report(receiving("FSR-MIG-202611-0006"), False, WHEN)
    assert guard.is_stale()          # a write the guard was not told about


def test_a_stale_ledger_stays_stale(book):
    guard = fsr_mysql_guard.Guard(None, book)
    with guard.local_write():
        fsr_store.ExcelStore(book).write_report(
            receiving("FSR-MIG-202611-0004"), False, WHEN)
    fsr_store.ExcelStore(book).write_report(       # outside the guard
        receiving("FSR-MIG-202611-0005"), False, WHEN)
    assert guard.is_stale()
    ledger = json.loads(guard.path.read_text(encoding="utf-8"))
    ledger["reports"] = {"fsr-mig-202611-0001": {"fingerprint": "x"}}
    guard.path.write_text(json.dumps(ledger), encoding="utf-8")
    assert migrate.migrate(book).status == "migrated"
    # emptied for good: nothing it said before is relied on
    assert guard.ledger()["reports"] == {}
    assert json.loads(guard.path.read_text(encoding="utf-8"))["reports"] == {}


def test_without_mysql_no_ledger_is_made(book):
    migrate.migrate(book)
    assert not fsr_mysql_guard.Guard(None, book).path.exists()


# ---------- an export changed outside the program ----------

def edit_in_excel(path, sheet, cell, value):
    wb = load_workbook(path)
    wb[sheet][cell] = value
    wb.save(path)


def so_column(path):
    wb = load_workbook(path, read_only=True)
    header = next(wb["Reports"].iter_rows(max_row=1, values_only=True))
    return "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[header.index("SO Number")]


def test_a_changed_export_is_never_overwritten(book):
    migrate.migrate(book)
    store = fsr_store.open_store(book)
    edit_in_excel(book, "Reports", f"{so_column(book)}2", "SO-EDITED")
    edited = book.read_bytes()
    with pytest.raises(export.ChangedOutside):
        export.write_export(store)
    assert book.read_bytes() == edited


def test_changed_while_the_database_did_not_change_is_taken(book):
    """As when the previous version was used again on the export, or the
    file was edited in Excel: the file is the newer one."""
    migrate.migrate(book)
    store = fsr_store.open_store(book)
    export.write_export(store)
    # the previous version saves a new report into the export
    import os
    os.replace(store.db_path, store.db_path.with_name("hidden.sqlite3"))
    fsr_store.ExcelStore(book).write_report(
        receiving("FSR-MIG-202611-0007", so="SO-OLD-VERSION"), False, WHEN)
    os.replace(store.db_path.with_name("hidden.sqlite3"), store.db_path)
    result = migrate.reconcile(book, now=NOW)
    assert result.status == "taken", result.message
    assert "taken as it is now" in result.message
    store = fsr_store.open_store(book)
    assert store.kind == "sqlite"
    assert store.read_report("FSR-MIG-202611-0007")["general_information"][
        "so_number"] == "SO-OLD-VERSION"
    assert aside(book, "replaced").exists()
    assert migrate.reconcile(book).status == "unchanged"


def test_changed_while_the_database_changed_too_loses_nothing(book):
    migrate.migrate(book)
    store = fsr_store.open_store(book)
    export.write_export(store)
    store.write_report(receiving("FSR-MIG-202611-0008", so="SO-IN-DB"),
                       False, WHEN)                 # not exported yet
    other = fsr_store.ExcelStore(book)           # someone edits the file
    other.write_report(receiving("FSR-MIG-202611-0001", so="SO-EDITED"),
                       True, WHEN)
    other.write_report(receiving("FSR-MIG-202611-0009", so="SO-IN-FILE"),
                       False, WHEN)
    result = migrate.reconcile(book, now=NOW)
    assert result.status == "merged"
    assert result.details["added"] == ["FSR-MIG-202611-0009"]
    assert result.details["differing"] == ["FSR-MIG-202611-0001"]
    assert "were NOT taken" in result.message
    kept = book.with_name(
        "Field_Survey_Reports (changed outside 20261113_120000).xlsx")
    assert kept.exists()
    assert fsr_storage.read_report(kept, "FSR-MIG-202611-0001")[
        "general_information"]["so_number"] == "SO-EDITED"
    store = fsr_store.open_store(book)
    so = {c: store.read_report(c)["general_information"]["so_number"]
          for c in ("FSR-MIG-202611-0001", "FSR-MIG-202611-0008",
                    "FSR-MIG-202611-0009")}
    assert so == {"FSR-MIG-202611-0001": "SO-M",
                  "FSR-MIG-202611-0008": "SO-IN-DB",
                  "FSR-MIG-202611-0009": "SO-IN-FILE"}
    # the export is written again and holds all of it
    assert export.changed_outside(store) == []
    assert {r[0] for r in fsr_storage.list_saved_reports(book)} >= set(so)


# ---------- the way back ----------

def test_back_to_the_workbook_with_every_report_saved_since(book):
    migrate.migrate(book)
    store = fsr_store.open_store(book)
    store.write_report(receiving("FSR-MIG-202611-0010", so="SO-SINCE"),
                       False, WHEN)
    store.write_withdrawal_report(
        withdrawal("FSR-MIG-202611-0011", "RCV-FSR-MIG-202611-0010-1-01", 2),
        False, WHEN)
    result = migrate.use_excel_again(book, now=NOW)
    assert result.status == "retired", result.message
    assert fsr_store.open_store(book).kind == "excel"
    old = fsr_store.ExcelStore(book)          # what the previous version reads
    assert old.read_report("FSR-MIG-202611-0010")["general_information"][
        "so_number"] == "SO-SINCE"
    assert "FSR-MIG-202611-0011" in old.withdrawal_numbers()
    assert aside(book, "retired").exists()
    # the previous version saves in it as always
    old.write_report(receiving("FSR-MIG-202611-0012"), False, WHEN)
    # and this version moves it in again, with that report
    assert migrate.migrate(book).status == "migrated"
    assert "FSR-MIG-202611-0012" in fsr_store.open_store(book).control_numbers()


def test_the_way_back_waits_for_a_changed_export(book):
    migrate.migrate(book)
    edit_in_excel(book, "Reports", "B2", "SO-EDITED")
    result = migrate.use_excel_again(book)
    assert result.status == "kept" and "Start the program once" in \
        result.message
    assert sq.is_active(book)


# ---------- Master Data between the previous version and this one ----------

def test_master_data_from_this_version_into_the_previous_one(book, tmp_path):
    migrate.migrate(book)
    target = tmp_path / "new.json"
    assert fsr_master_export.write_export(book, target, "new-pc") == 3
    owner = tmp_path / "owner" / "data.xlsx"
    owner.parent.mkdir()
    summary = fsr_import.import_master_data(
        owner, fsr_import.read_master_file(target))  # owner still on Excel
    assert sorted(summary["added"]) == ["FSR-MIG-202611-0001",
                                        "FSR-MIG-202611-0002",
                                        "FSR-MIG-202611-0003"]
    assert fsr_store.open_store(owner).kind == "excel"
    new = fsr_store.open_store(book)
    old = fsr_store.ExcelStore(owner)
    for control in ("FSR-MIG-202611-0001", "FSR-MIG-202611-0002"):
        assert old.read_report(control) == {
            **new.read_report(control),
            "incident_reports": old.read_report(control)["incident_reports"]}
    assert old.read_report("FSR-MIG-202611-0002")["incident_reports"][0][
        "lines"] == ["Torn bag"]


def test_master_data_from_the_previous_version_into_this_one(book, tmp_path):
    site = tmp_path / "site" / "data.xlsx"
    site.parent.mkdir()
    fsr_store.ExcelStore(site).write_report(
        receiving("FSR-SIT-202611-0001", so="SO-SITE"), False, WHEN)
    target = tmp_path / "old.json"
    fsr_master_export.write_export(site, target, "old-pc")  # previous version
    migrate.migrate(book)
    data = fsr_import.read_master_file(target)
    summary = fsr_store.open_store(book).import_master_data(data)
    assert summary["added"] == ["FSR-SIT-202611-0001"]
    assert summary["backup"].endswith(".sqlite3")
    store = fsr_store.open_store(book)
    assert store.read_report("FSR-SIT-202611-0001")["general_information"][
        "so_number"] == "SO-SITE"
    assert store.import_master_data(data)["unchanged"] == \
        ["FSR-SIT-202611-0001"]


# ---------- the daily backup of the database ----------

def test_the_daily_backup_copies_the_database(book):
    migrate.migrate(book)
    store = fsr_store.open_store(book)
    result = store.backup_before_save(14)
    copy = result["created"]
    assert copy.name == f"Field_Survey_Reports_backup_{date.today():%Y%m%d}" \
                        ".sqlite3"
    copied = sq.SqliteStore(book, db_path=copy)
    assert copied.list_reports() == store.list_reports()
    assert store.backup_before_save(14)["created"] is None   # once a day


def test_demo_reset_refuses_real_reports_in_the_database(book):
    migrate.migrate(book)
    store = fsr_store.open_store(book)
    with pytest.raises(fsr_store.StoreRefused):
        store.delete_reports(["FSR-MIG-202611-0001"])
    assert len(store.list_reports()) == 2
    (book.parent / fsr_store.DEMO_MARKER).write_text("test data")
    with pytest.raises(fsr_store.StoreRefused):
        store.delete_reports(["FSR-MIG-202611-0001"])
    store.write_report(receiving("TEST-0001"), True, WHEN)
    assert store.delete_reports(["TEST-0001"]) == 1


def test_the_copy_in_the_backup_folder_is_never_migrated_into(book):
    """Backups hold the files unchanged - also after later saves."""
    result = migrate.migrate(book, now=NOW)
    folder = result.details["backup"]
    store = fsr_store.open_store(book)
    store.write_report(receiving("FSR-MIG-202611-0013"), False, WHEN)
    export.write_export(store)
    copy = fsr_storage.list_saved_reports(
        shutil.os.path.join(folder, book.name))
    assert "FSR-MIG-202611-0013" not in [r[0] for r in copy]


def test_two_moves_in_the_same_second_keep_both_backups(book):
    assert migrate.migrate(book, now=NOW).status == "migrated"
    assert migrate.use_excel_again(book, now=NOW).status == "retired"
    result = migrate.migrate(book, now=NOW)
    assert result.status == "migrated", result.message
    assert result.details["backup"].endswith("before_sqlite_20261113_120000_2")
    assert len(list((book.parent / "Backups").glob("before_sqlite_*"))) == 2


def test_a_save_in_excel_during_the_move_is_not_lost(book, monkeypatch):
    """Someone saves the workbook in Excel while the reports are being
    moved: the move is not finished, the workbook stays in use."""
    real = migrate.compare_stores

    def meanwhile(excel, sql):
        found = real(excel, sql)
        fsr_store.ExcelStore(book).write_report(
            receiving("FSR-MIG-202611-0020", so="SO-DURING"), False, WHEN)
        return found
    monkeypatch.setattr(migrate, "compare_stores", meanwhile)
    result = migrate.migrate(book)
    assert result.status == "kept"
    assert "changed while the reports were being moved" in result.message
    assert fsr_store.open_store(book).kind == "excel"
    assert "FSR-MIG-202611-0020" in fsr_store.open_store(
        book).control_numbers()
    monkeypatch.setattr(migrate, "compare_stores", real)
    assert migrate.migrate(book).status == "migrated"      # next start
    assert "FSR-MIG-202611-0020" in fsr_store.open_store(
        book).control_numbers()


def test_the_read_once_copy_is_never_handed_to_a_write(book):
    with migrate._read_once([book]):
        first = fsr_storage.load_workbook(book, data_only=True)
        assert fsr_storage.load_workbook(book, data_only=True) is first
        assert fsr_storage.load_workbook(book) is not first
    assert fsr_storage.load_workbook(book, data_only=True) is not first


def test_a_formula_typed_into_the_workbook_keeps_the_workbook(book):
    wb = load_workbook(book)
    ws = wb["Item List"]
    ws.cell(row=ws.max_row + 1, column=7, value="=SUM(G2:G3)")
    wb.save(book)
    result = migrate.migrate(book)
    assert result.status == "kept"
    assert "formula" in result.message and "Item List!G" in result.message
    assert fsr_store.open_store(book).kind == "excel"
