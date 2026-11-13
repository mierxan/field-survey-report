"""Where the reports database lives (fsr_db_location, Phase 5): never next
to the workbook, never in a synchronised folder or on a network drive; a
workbook that is moved or renamed finds its database by the id it carries;
a copy gets its own; a database still next to the workbook is moved; an
Excel file written by ANOTHER database (another PC sharing the folder) is
never taken over this PC's. Invented data in temporary folders."""
import json
import shutil
from datetime import date, datetime

import pytest

import fsr_db_location as location
import fsr_mysql_guard
import fsr_paths
import fsr_sqlite_export as export
import fsr_sqlite_migrate as migrate
import fsr_sqlite_store as sq
import fsr_storage
import fsr_store
from factories import report

WHEN = datetime(2026, 11, 14, 9, 0, 0)
NOW = datetime(2026, 11, 14, 12, 0, 0)


def receiving(control, so="SO-L", condition="Good Order"):
    data = report(control, "Receiving", date(2026, 11, 5), "WH",
                  [{"qty": 2, "unit": "Box", "desc": "Pump",
                    "ref": f"RCV-{control}-1-01"}], so=so,
                  condition=condition)
    data["other_item_forms"] = {}
    return data


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """The program's data folders and a databases' folder of its own."""
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "data" / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "data" / "excel")
    monkeypatch.setenv("FSR_DATABASE_DIR", str(tmp_path / "LocalAppData"))
    (tmp_path / "data" / "excel").mkdir(parents=True)
    (tmp_path / "data" / "json").mkdir()
    return tmp_path


def workbook(folder, controls=("FSR-LOC-202611-0001",), bad=()):
    folder.mkdir(parents=True, exist_ok=True)
    book = folder / "Field_Survey_Reports.xlsx"
    store = fsr_store.ExcelStore(book)
    for control in controls:
        store.write_report(receiving(
            control, condition="Bad Order" if control in bad else
            "Good Order"), False, WHEN)
        if control in bad:
            store.save_incidents(control, "SO-L",
                                 [{"vessel": "MV", "lines": ["Wet box"]}])
    return book


def controls_of(book):
    return [r[0] for r in fsr_store.open_store(book).list_reports()]


# ---------- the folder ----------

def test_the_folder_of_the_databases():
    assert location.database_dir({"FSR_DATABASE_DIR": r"D:\t",
                                  "FSR_HOME": r"D:\h",
                                  "LOCALAPPDATA": r"C:\L"}) == \
        location.Path(r"D:\t")
    assert location.database_dir({"FSR_HOME": r"D:\h",
                                  "LOCALAPPDATA": r"C:\L"}) == \
        location.Path(r"D:\h\LocalAppData\FieldSurveyReport\Databases")
    assert location.database_dir({"LOCALAPPDATA": r"C:\L"}) == \
        location.Path(r"C:\L\FieldSurveyReport\Databases")


def test_a_workbook_on_a_network_drive_has_its_database_on_this_pc(dirs):
    share = r"\\server\share\FSR\Field_Survey_Reports.xlsx"
    assert location.is_network(share)
    db = location.default_db_path(share)
    assert db.parent == location.database_dir()
    assert db.name.startswith("Field_Survey_Reports-")
    assert not location.is_network(db)


def test_a_workbook_on_a_network_drive_moves_in_like_any_other(
        dirs, monkeypatch):
    book = workbook(dirs / "share")
    monkeypatch.setattr(location, "_drive_type", lambda path: (
        location.DRIVE_REMOTE if "share" in str(path) else 3))
    assert location.is_network(book)
    assert migrate.migrate(book).status == "migrated"
    store = fsr_store.open_store(book)
    assert store.db_path.parent == location.database_dir()
    assert not location.legacy_db_path(book).exists()


# ---------- synchronised folders ----------

def test_onedrive_dropbox_and_cloud_folders_are_found(tmp_path, monkeypatch):
    onedrive = tmp_path / "OneDrive"
    (onedrive / "Documents").mkdir(parents=True)
    env = {"OneDrive": str(onedrive)}
    assert location.sync_tool(onedrive / "Documents" / "x.xlsx", env) == \
        "OneDrive"
    assert location.folder_problem(onedrive / "Documents", env) == \
        f"{onedrive / 'Documents'} is synchronised by OneDrive"
    appdata = tmp_path / "AppData"
    (appdata / "Dropbox").mkdir(parents=True)
    box = tmp_path / "Dropbox (Firm)"
    box.mkdir()
    (appdata / "Dropbox" / "info.json").write_text(json.dumps(
        {"business": {"path": str(box)}}), encoding="utf-8")
    assert location.sync_tool(box / "data", {"APPDATA": str(appdata)}) == \
        "Dropbox"
    plain = tmp_path / "plain"
    plain.mkdir()
    assert location.sync_tool(plain, {}) is None
    monkeypatch.setattr(location, "_attributes", lambda path: (
        0x80000 if path == plain else 0x10))                 # "pinned"
    assert location.sync_tool(plain / "x.xlsx", {}) == \
        "a cloud synchronisation service"


def test_a_synchronised_folder_for_the_databases_keeps_the_workbook(
        dirs, monkeypatch):
    book = workbook(dirs / "data" / "excel")
    monkeypatch.setenv("OneDrive", str(dirs))           # all of it synced
    result = migrate.migrate(book)
    assert result.status == "kept"
    assert "synchronised by OneDrive" in result.message
    assert fsr_store.open_store(book).kind == "excel"
    assert not list(location.database_dir().glob("*.sqlite3"))


def test_a_database_found_in_a_synchronised_folder_goes_back(dirs,
                                                            monkeypatch):
    book = workbook(dirs / "data" / "excel")
    assert migrate.migrate(book).status == "migrated"
    fsr_store.open_store(book).write_report(
        receiving("FSR-LOC-202611-0002", so="SO-SINCE"), False, WHEN)
    monkeypatch.setenv("OneDrive", str(dirs))     # synchronised from now on
    result = migrate.migrate(book, now=NOW)
    assert result.status == "returned", result.message
    assert "synchronised by OneDrive" in result.message
    assert fsr_store.open_store(book).kind == "excel"
    assert "FSR-LOC-202611-0002" in fsr_store.ExcelStore(
        book).control_numbers()                  # nothing lost


# ---------- a database still next to the workbook ----------

def put_next_to_workbook(book):
    """As the first Phase 5 builds left it: the database and its export
    note next to the workbook / in the JSON folder."""
    store = fsr_store.open_store(book)
    legacy = location.legacy_db_path(book)
    shutil.move(store.db_path, legacy)
    note = export.state_path(store)
    shutil.move(note, export.legacy_state_path(book))
    location.forget(store.db_path)
    return legacy


def test_a_database_next_to_the_workbook_moves_to_local_appdata(
        dirs, monkeypatch):
    book = workbook(dirs / "data" / "excel",
                    ("FSR-LOC-202611-0001", "FSR-LOC-202611-0002"),
                    bad=("FSR-LOC-202611-0002",))
    assert migrate.migrate(book).status == "migrated"
    guard = fsr_mysql_guard.Guard(None, book)
    with guard.local_write():            # MySQL in use: a current ledger
        fsr_store.open_store(book).write_report(
            receiving("FSR-LOC-202611-0003"), False, WHEN)
    export.write_export(fsr_store.open_store(book))   # (the window does it)
    before = fsr_store.open_store(book).read_all_reports()
    legacy = put_next_to_workbook(book)
    monkeypatch.setenv("OneDrive", str(dirs))
    monkeypatch.setenv("FSR_DATABASE_DIR",
                       str(dirs.parent / (dirs.name + "_local")))
    with guard.local_write():
        pass                             # the ledger is about the old file
    assert sq.is_active(book) and fsr_store.open_store(book).db_path == legacy
    result = migrate.migrate(book, now=NOW)
    assert result.status == "moved", result.message
    assert "a folder that OneDrive synchronises" in result.message
    store = fsr_store.open_store(book)
    assert store.db_path.parent == location.database_dir()
    assert store.read_all_reports() == before
    assert not legacy.exists()
    assert legacy.with_name(
        f"{legacy.name}.moved_to_local_20261114_120000").exists()
    assert export.is_current(store)                  # the note came along
    assert not guard.is_stale()                      # MySQL still trusts it


def test_a_database_that_cannot_be_moved_is_used_where_it_is(dirs,
                                                            monkeypatch):
    book = workbook(dirs / "data" / "excel")
    migrate.migrate(book)
    legacy = put_next_to_workbook(book)
    with monkeypatch.context() as failing:
        failing.setattr(migrate, "compare_stores",
                        lambda a, b: ["report X differs"])
        result = migrate.migrate(book)
    assert result.status == "kept_legacy"
    assert "used where it is" in result.message
    assert fsr_store.open_store(book).db_path == legacy
    assert controls_of(book) == ["FSR-LOC-202611-0001"]
    assert not list(location.database_dir().glob("*.moving"))
    assert migrate.migrate(book).status == "moved"   # tried again


# ---------- a workbook in a new place ----------

def test_a_renamed_workbook_finds_its_database(dirs):
    book = workbook(dirs / "data" / "excel", bad=("FSR-LOC-202611-0001",))
    migrate.migrate(book)
    store = fsr_store.open_store(book)
    database_id = store.database_id
    guard = fsr_mysql_guard.Guard(None, book)
    with guard.local_write():
        pass                                         # a MySQL ledger exists
    renamed = book.with_name("Reports_2026.xlsx")
    book.rename(renamed)
    result = migrate.migrate(renamed, now=NOW)
    assert result.status == "relinked", result.message
    assert "goes on using its reports database" in result.message
    moved = fsr_store.open_store(renamed)
    assert moved.database_id == database_id and moved.db_path == store.db_path
    assert controls_of(renamed) == ["FSR-LOC-202611-0001"]
    # the records named after the workbook came along (the MySQL ledger)
    assert fsr_mysql_guard.Guard(None, renamed).path.exists()
    assert moved.read_report("FSR-LOC-202611-0001")["incident_reports"][0][
        "lines"] == ["Wet box"]
    assert migrate.migrate(renamed).status == "active"


def test_a_moved_folder_finds_its_database_and_its_files(dirs):
    book = workbook(dirs / "data" / "excel", bad=("FSR-LOC-202611-0001",))
    migrate.migrate(book)
    database_id = fsr_store.open_store(book).database_id
    new_place = dirs / "moved" / "excel"
    new_place.mkdir(parents=True)
    for name in (book.name, fsr_paths.WITHDRAWAL_WORKBOOK_NAME):
        if (book.parent / name).exists():
            shutil.move(book.parent / name, new_place / name)
    book = new_place / book.name
    result = migrate.migrate(book, now=NOW)
    assert result.status == "relinked", result.message
    assert "copied from its old JSON folder" in result.message
    store = fsr_store.open_store(book)
    assert store.database_id == database_id
    report_ = store.read_report("FSR-LOC-202611-0001")
    assert report_["incident_reports"][0]["lines"] == ["Wet box"]
    store.write_report(receiving("FSR-LOC-202611-0002"), False, WHEN)
    export.write_export(store)
    assert "FSR-LOC-202611-0002" in [
        r[0] for r in fsr_storage.list_saved_reports(book)]


def test_a_copy_gets_its_own_database(dirs):
    book = workbook(dirs / "data" / "excel")
    migrate.migrate(book)
    original_id = fsr_store.open_store(book).database_id
    copy = dirs / "usb" / book.name
    copy.parent.mkdir()
    shutil.copy2(book, copy)
    result = migrate.migrate(copy)
    assert result.status == "migrated"
    assert "is a copy of" in result.message
    mine = fsr_store.open_store(copy)
    assert mine.database_id != original_id
    assert fsr_store.open_store(book).database_id == original_id
    assert location.workbook_identity(copy) == mine.database_id


def test_a_lost_list_of_databases_is_not_a_lost_database(dirs):
    book = workbook(dirs / "data" / "excel")
    migrate.migrate(book)
    database_id = fsr_store.open_store(book).database_id
    (location.database_dir() / location.INDEX_NAME).unlink()
    assert sq.is_active(book)                   # found by its usual name
    renamed = book.with_name("Renamed.xlsx")
    book.rename(renamed)
    result = migrate.migrate(renamed)           # found inside the database
    assert result.status == "relinked"
    assert fsr_store.open_store(renamed).database_id == database_id


# ---------- two PCs that synchronise the same folder ----------

def test_an_excel_file_from_another_pcs_database_is_never_taken(dirs):
    book = workbook(dirs / "data" / "excel")
    migrate.migrate(book)
    mine = fsr_store.open_store(book)
    mine_id = mine.database_id
    # another PC: its own database for the same workbook, a report of its
    # own, and its export arrives here through OneDrive
    other_pc = dirs / "other_pc"
    other_book = workbook(other_pc, ())
    shutil.copy2(book, other_book)
    assert migrate.migrate(other_book).status == "migrated"
    theirs = fsr_store.open_store(other_book)
    assert theirs.database_id != mine_id
    theirs.write_report(receiving("FSR-OTH-202611-0009", so="SO-OTHER-PC"),
                        False, WHEN)
    export.write_export(theirs)
    shutil.copy2(other_book, book)               # the sync overwrites ours
    assert export.is_current(mine)               # nothing changed here
    result = migrate.reconcile(book, now=NOW)
    assert result.status == "merged", result.message
    assert result.details["foreign"] is True
    assert "ANOTHER copy of the program" in result.message
    assert "Two PCs must not use one Excel file" in result.message
    store = fsr_store.open_store(book)
    assert store.database_id == mine_id          # ours was kept
    assert "FSR-OTH-202611-0009" in store.control_numbers()   # added
    assert "FSR-LOC-202611-0001" in store.control_numbers()
    assert location.workbook_identity(book) == mine_id
