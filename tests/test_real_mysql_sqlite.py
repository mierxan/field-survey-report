"""The overwrite guard against the REAL test database field_survey_test
(tests/real_mysql.py - never field_survey), with the reports in the SQLite
database (Phase 5). The same rules as tests/test_real_mysql.py, and the
step that is new: a copy that sent its reports to MySQL while they were in
the workbook, then moved them into the database, still owns them.

Skipped, with the reason spelled out, when the test database cannot be
used on this PC."""
import os
from datetime import date

import pytest

import fsr_mysql_guard as g
import fsr_paths
import fsr_save_journal as j
import fsr_sqlite_migrate as migrate
import fsr_storage as s
import fsr_store
import real_mysql
from factories import report


@pytest.fixture(scope="module")
def database():
    try:
        db = real_mysql.open_database()
    except real_mysql.NotAvailable as why:
        pytest.skip(f"{real_mysql.SKIP_PREFIX}: {why}")
    db.remove_test_rows()
    yield db
    db.down = False
    db.remove_test_rows()


_serial = iter(range(1, 10_000))


def make(control, so="SO-MINE"):
    data = report(control, "Receiving", date(2026, 11, 5), "WH",
                  [{"qty": 2, "unit": "Crate", "desc": "Pump", "po": "PO-77",
                    "cargo": "C-1", "ref": f"RCV-{control}-1-01"}], so=so)
    data["other_item_forms"] = {}
    return data


class Copy:
    """One copy of the program; Save and the catch-up exactly as the
    program does them (fsr_save_journal), on whichever store the workbook
    has (the workbook first, the database after migrate())."""

    def __init__(self, folder, db):
        (folder / "excel").mkdir(parents=True)
        (folder / "json").mkdir()
        self.book = folder / "excel" / "Field_Survey_Reports.xlsx"
        self.db = db

    @property
    def store(self):
        return fsr_store.open_store(self.book)

    @property
    def guard(self):
        return g.Guard(self.db, self.book, user="Tester")

    @property
    def journal(self):
        return j.Journal(self.book)

    @property
    def stores(self):
        return j.Stores(self.book, mysql=self.db, guard=self.guard)

    def save(self, data, editing=False):
        record = j.open_save(self.journal, self.stores, data, editing,
                             False, True)
        return j.run(self.journal, record, self.stores)

    def time_passes(self):
        """Minutes go by: the JSON files look 10 minutes old; the workbook
        and the database keep their exact time (they were not touched)."""
        for path in (self.book.parent.parent / "json").glob("*.json"):
            info = path.stat()
            os.utime(path, (info.st_atime - 600, info.st_mtime - 600))


@pytest.fixture
def copy(database, tmp_path, monkeypatch):
    monkeypatch.setitem(s._control_initials, "value", "ZZT")
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    database.down = False
    mine = Copy(tmp_path, database)
    control = f"{real_mysql.PREFIX}12-{next(_serial):04d}"
    assert control.startswith(real_mysql.PREFIX)
    return mine, database, control


def so_in_mysql(db, control):
    rows = db.run("SELECT so_number FROM reports WHERE control_no = %s",
                  (control,))
    return rows[0][0] if rows else None


def test_sent_from_the_workbook_moved_in_then_edited(copy):
    """The step Phase 5 adds: no false conflict after the move."""
    mine, db, control = copy
    assert mine.store.kind == "excel"
    assert mine.save(make(control))["failed"] == {}
    assert so_in_mysql(db, control) == "SO-MINE"
    mine.time_passes()
    assert migrate.migrate(mine.book).status == "migrated"
    assert mine.store.kind == "sqlite"
    assert not mine.guard.is_stale()
    mine.time_passes()
    outcome = mine.save(make(control, so="EDITED AFTER THE MOVE"),
                        editing=True)
    assert outcome["failed"] == {}
    assert so_in_mysql(db, control) == "EDITED AFTER THE MOVE"
    assert mine.store.read_report(control)["general_information"][
        "so_number"] == "EDITED AFTER THE MOVE"
    assert j.conflicts(mine.journal) == []
    assert j.waiting_for_mysql(mine.journal) == []


def test_save_then_save_again_on_the_database(copy):
    mine, db, control = copy
    migrate.migrate(mine.book)                      # a new PC: empty
    assert mine.store.kind == "sqlite"
    assert mine.save(make(control))["failed"] == {}
    for number in range(3):
        mine.time_passes()
        outcome = mine.save(make(control, so=f"EDIT {number}"), editing=True)
        assert outcome["failed"] == {}
        assert so_in_mysql(db, control) == f"EDIT {number}"
    assert j.conflicts(mine.journal) == []


def test_offline_then_catch_up_on_the_database(copy):
    mine, db, control = copy
    migrate.migrate(mine.book)
    db.down = True
    outcome = mine.save(make(control, so="SAVED OFFLINE"))
    assert db.is_unreachable(outcome["failed"]["mysql"])
    db.down = False
    assert so_in_mysql(db, control) is None
    mine.time_passes()
    (entry,) = j.repair(mine.journal, mine.stores)         # MySQL is back
    assert entry["did"] == ["mysql"] and entry["finished"]
    assert so_in_mysql(db, control) == "SAVED OFFLINE"
    mine.time_passes()
    outcome = mine.save(make(control, so="EDITED AFTER CATCH-UP"),
                        editing=True)
    assert outcome["failed"] == {}
    assert so_in_mysql(db, control) == "EDITED AFTER CATCH-UP"


def test_another_copys_report_is_not_overwritten(copy, tmp_path):
    mine, db, control = copy
    migrate.migrate(mine.book)
    other = Copy(tmp_path / "other", db)
    assert other.guard.save(make(control, so="THE OTHER COPY'S"))[0] == \
        "written"
    outcome = mine.save(make(control, so="MINE"))
    assert outcome["failed"]["mysql"].conflict["kind"] == g.NOT_OWNED
    assert so_in_mysql(db, control) == "THE OTHER COPY'S"
    assert len(j.conflicts(mine.journal)) == 1


def test_a_restored_database_asks_again(copy):
    """A database put back from a backup (its file changed outside the
    program): the ledger is not relied on, as after restoring a workbook."""
    mine, db, control = copy
    migrate.migrate(mine.book)
    mine.save(make(control))
    mine.time_passes()
    db_file = mine.store.db_path
    info = db_file.stat()
    os.utime(db_file, (info.st_atime, info.st_mtime + 90))     # "restored"
    outcome = mine.save(make(control, so="AFTER A RESTORE"), editing=True)
    conflict = outcome["failed"]["mysql"].conflict
    assert conflict["kind"] == g.NOT_OWNED
    assert so_in_mysql(db, control) == "SO-MINE"


def test_the_export_does_not_make_the_ledger_look_stale(copy):
    """The Excel export is written in the background, outside the guard:
    the next save is still this copy's own."""
    import fsr_sqlite_export
    mine, db, control = copy
    migrate.migrate(mine.book)
    mine.save(make(control))
    fsr_sqlite_export.write_export(mine.store)
    mine.time_passes()
    outcome = mine.save(make(control, so="AFTER THE EXPORT"), editing=True)
    assert outcome["failed"] == {}
    assert so_in_mysql(db, control) == "AFTER THE EXPORT"
