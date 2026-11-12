"""The guard against a REAL MySQL server: the test database
field_survey_test (tests/real_mysql.py - never field_survey).

The other guard tests use an in-memory stand-in. These run the same rule
through the real driver, the real lock, the real transaction and the real
tables - and with TIME PASSING between two saves, which is what the
stand-in tests did not have (see test_time_between_saves_... below).

Skipped, with the reason spelled out, when the test database cannot be
used on this PC."""
import os
import time
from datetime import date

import pytest

import fsr_mysql_guard as g
import fsr_paths
import fsr_save_journal as j
import fsr_storage as s
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


def make(control, so="SO-MINE", desc="Pump"):
    data = report(control, "Receiving", date(2026, 11, 5), "WH",
                  [{"qty": 2, "unit": "Crate", "desc": desc, "po": "PO-77",
                    "cargo": "C-1", "ref": f"RCV-{control}-1-01"}], so=so)
    data["other_item_forms"] = {}
    return data


class Copy:
    """One copy of the program with its own workbook; Save and the
    catch-up exactly as the program does them (fsr_save_journal)."""

    def __init__(self, folder, db):
        (folder / "excel").mkdir(parents=True)
        (folder / "json").mkdir()
        self.book = folder / "excel" / "Field_Survey_Reports.xlsx"
        self.db = db

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
        """Minutes go by: every file of this copy looks 10 minutes old,
        each by the same amount (so nothing changes between them)."""
        for path in [*self.book.parent.glob("*.xlsx"),
                     *(self.book.parent.parent / "json").glob("*.json")]:
            info = path.stat()
            # the workbook keeps its exact time: it was not touched
            if path.suffix == ".json":
                os.utime(path, (info.st_atime - 600, info.st_mtime - 600))


@pytest.fixture
def copy(database, tmp_path, monkeypatch):
    monkeypatch.setitem(s._control_initials, "value", "ZZT")
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    database.down = False
    mine = Copy(tmp_path, database)
    control = f"{real_mysql.PREFIX}11-{next(_serial):04d}"
    assert control.startswith(real_mysql.PREFIX)
    return mine, database, control


def so_in_mysql(db, control):
    rows = db.run("SELECT so_number FROM reports WHERE control_no = %s",
                  (control,))
    return rows[0][0] if rows else None


def someone_else_changes(db, control, so="CHANGED BY SOMEONE ELSE"):
    db.run("UPDATE reports SET so_number = %s WHERE control_no = %s",
           (so, control))


# ---------- the connection itself ----------

def test_it_is_the_test_database_and_nothing_else(database):
    assert real_mysql.TEST_DATABASE == "field_survey_test"
    assert database.run("SELECT DATABASE()") == [("field_survey_test",)]
    assert database._config["database"] == "field_survey_test"


def test_the_test_login_cannot_read_the_real_database(database):
    """Whatever a test does, this login has no rights on field_survey."""
    with pytest.raises(Exception) as caught:
        database.run("SELECT COUNT(*) FROM field_survey.reports")
    assert getattr(caught.value, "errno", None) in (1142, 1044, 1146)


def test_what_is_written_reads_back_equal_in_value(copy):
    """The fingerprint kept in the ledger is taken from what MySQL returns;
    reading the same row again must give the same fingerprint."""
    mine, db, control = copy
    data = make(control, so="  Señor Ñandú 0282050  ", desc="Válvula 3\" ø")
    data["item_lists"][0]["rows"][0].update(
        {"Quantity": "1,250", "Unit Price": "0.00", "Total Price": "12.50"})
    assert mine.guard.save(data)[0] == "written"
    first = db.load_report(control)
    second = db.load_report(control)
    assert g.fingerprint(first) == g.fingerprint(second)
    assert g.same_value(data, first)
    assert mine.guard.look(data) == "identical"


# ---------- Finding 1: my own report is mine, also minutes later ----------

def test_save_then_save_again(copy):
    mine, db, control = copy
    assert mine.save(make(control))["failed"] == {}
    mine.time_passes()
    outcome = mine.save(make(control, so="EDITED BY ME"), editing=True)
    assert outcome["failed"] == {}
    assert so_in_mysql(db, control) == "EDITED BY ME"
    assert j.conflicts(mine.journal) == []


def test_save_three_times_with_time_between(copy):
    mine, db, control = copy
    mine.save(make(control))
    for number in range(3):
        mine.time_passes()
        outcome = mine.save(make(control, so=f"EDIT {number}"), editing=True)
        assert outcome["failed"] == {}
        assert so_in_mysql(db, control) == f"EDIT {number}"


def test_save_offline_then_catch_up_then_save_again(copy):
    mine, db, control = copy
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
    assert j.conflicts(mine.journal) == []


def test_replace_then_save_again(copy):
    mine, db, control = copy
    db_other = make(control, so="THE OTHER COPY'S", desc="Other goods")
    conn = db.connect()
    db.write_report(conn, db_other)
    conn.commit()
    conn.close()

    outcome = mine.save(make(control, so="MINE"))
    conflict = outcome["failed"]["mysql"].conflict
    assert conflict["kind"] == g.NOT_OWNED
    assert so_in_mysql(db, control) == "THE OTHER COPY'S"   # untouched
    (record,) = j.conflicts(mine.journal)
    mine.time_passes()

    outcome = j.resolve_replace(mine.journal, mine.stores, record["id"])
    assert outcome["failed"] == {}
    assert so_in_mysql(db, control) == "MINE"
    kept = list(mine.guard.replaced_dir.glob("*.json"))
    assert len(kept) == 1                   # the replaced version is kept
    mine.time_passes()

    outcome = mine.save(make(control, so="MINE, EDITED"), editing=True)
    assert outcome["failed"] == {}          # it is mine now: no question
    assert so_in_mysql(db, control) == "MINE, EDITED"
    assert len(list(mine.guard.replaced_dir.glob("*.json"))) == 1


def test_changed_in_mysql_by_someone_else_then_save(copy):
    mine, db, control = copy
    mine.save(make(control))
    mine.time_passes()
    someone_else_changes(db, control)

    outcome = mine.save(make(control, so="EDITED BY ME"), editing=True)

    conflict = outcome["failed"]["mysql"].conflict
    assert conflict["kind"] == g.CHANGED_ELSEWHERE
    assert "This copy of the program sent report" in conflict["text"]
    assert "changed in MySQL" in conflict["text"]
    assert "did not put there" not in conflict["text"]
    assert so_in_mysql(db, control) == "CHANGED BY SOMEONE ELSE"
    assert s.read_report(mine.book, control)[
        "general_information"]["so_number"] == "EDITED BY ME"   # local: saved
    assert len(j.conflicts(mine.journal)) == 1


def test_report_of_another_copy_is_not_overwritten(copy, tmp_path):
    mine, db, control = copy
    other = Copy(tmp_path / "other", db)
    assert other.guard.save(make(control, so="THE OTHER COPY'S"))[0] == \
        "written"
    outcome = mine.save(make(control, so="MINE"))
    assert outcome["failed"]["mysql"].conflict["kind"] == g.NOT_OWNED
    assert so_in_mysql(db, control) == "THE OTHER COPY'S"


def test_workbook_changed_outside_the_program_asks_again(copy):
    """The safety the ledger note is for: a restored or hand-edited
    workbook means the ledger is not relied on."""
    mine, db, control = copy
    mine.save(make(control))
    mine.time_passes()
    info = mine.book.stat()
    os.utime(mine.book, (info.st_atime, info.st_mtime + 90))    # "restored"

    outcome = mine.save(make(control, so="AFTER A RESTORE"), editing=True)

    conflict = outcome["failed"]["mysql"].conflict
    assert conflict["kind"] == g.NOT_OWNED
    assert "no record of having sent it" in conflict["text"]
    assert so_in_mysql(db, control) == "SO-MINE"


# ---------- the lock and the transaction on a real server ----------

def test_a_report_being_saved_by_another_copy_is_not_written(copy):
    mine, db, control = copy
    mine.save(make(control))
    holder = db.connect()                   # another copy, mid-save
    try:
        assert real_mysql.db_mysql.lock_report(holder, control) is True
        db.lock_report = lambda conn, number:             real_mysql.db_mysql.lock_report(conn, number, timeout=1)
        started = time.monotonic()
        with pytest.raises(g.MySQLBusy):
            mine.guard.save(make(control, so="WHILE LOCKED"))
        assert time.monotonic() - started < 8
        assert so_in_mysql(db, control) == "SO-MINE"
    finally:
        del db.lock_report                  # the class's own again
        real_mysql.db_mysql.unlock_report(holder, control)
        holder.close()
    # the lock is free again
    assert mine.guard.save(make(control, so="AFTER THE LOCK"))[0] == "written"


def test_a_conflict_leaves_no_half_written_report(copy):
    mine, db, control = copy
    mine.save(make(control))
    someone_else_changes(db, control)
    before = db.load_report(control)
    with pytest.raises(g.MySQLConflict):
        mine.guard.save(make(control, so="MINE", desc="Different goods"))
    assert db.load_report(control) == before
