"""MySQL in the background (Phase 3): the sender, one connection per round,
and what a program closed (or a PC losing power) in the middle of a send
leaves behind. With the in-memory FakeServer; the same rule against the
real test database is in test_real_mysql.py."""
import threading
import time
from datetime import date

import pytest

import db_mysql
import fsr_mysql_guard as g
import fsr_paths
import fsr_save_journal as j
from factories import report
from fake_mysql import FakeServer


class Crash(BaseException):
    """The PC loses power: nothing after this line runs."""


def make(control="FSR-MPR-202611-0001", so="SO-MINE"):
    data = report(control, "Receiving", date(2026, 11, 5), "WH",
                  [{"qty": 2, "unit": "Crate", "desc": "Pump",
                    "ref": f"RCV-{control}-1-01"}], so=so)
    data["other_item_forms"] = {}
    return data


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    (tmp_path / "excel").mkdir()
    (tmp_path / "json").mkdir()
    book = tmp_path / "excel" / "Field_Survey_Reports.xlsx"
    server = FakeServer()
    return book, server


class Counting:
    """The FakeDB of one copy, counting its connections."""

    def __init__(self, server):
        self.db = server.client()
        self.connections = 0
        real = self.db.connect

        def connect(config=None):
            self.connections += 1
            return real(config)
        self.db.connect = connect


def save_locally(book, db, data, editing=False):
    """What the program's Save does now: everything on this PC, MySQL's
    step left open for the sender."""
    guard = g.Guard(db, book)
    stores = j.Stores(book, mysql=db, guard=guard)
    journal = j.Journal(book)
    record = j.open_save(journal, stores, data, editing, False, True)
    j.run(journal, record, stores, mysql=False)
    return record


def round_(book, db, with_conflicts=False):
    """One background round: one connection for every waiting report."""
    guard = g.Guard(db, book)
    stores = j.Stores(book, mysql=db, guard=guard)
    conn = db.connect()
    try:
        stores.connection = conn
        return j.send_waiting(j.Journal(book), stores, with_conflicts,
                              db_mysql.is_unreachable)
    finally:
        conn.close()


def so_in(server, control="FSR-MPR-202611-0001"):
    found = server.get(control)
    return found["general_information"]["so_number"] if found else None


# ---------- the save does not send; the round does ----------

def test_save_leaves_the_mysql_step_open_and_writes_nothing_there(env):
    book, server = env
    db = Counting(server)
    record = save_locally(book, db.db, make())
    assert db.connections == 0 and server.writes == []
    (waiting,) = j.waiting_for_mysql(j.Journal(book))
    assert waiting["id"] == record["id"]
    assert j.local_complete(waiting)


def test_one_connection_for_every_report_of_a_round(env):
    book, server = env
    db = Counting(server)
    for number in range(1, 6):
        save_locally(book, db.db, make(f"FSR-MPR-202611-{number:04d}"))
    result = round_(book, db.db)
    assert db.connections == 1
    assert len(result["sent"]) == 5 and result["away"] is None
    assert j.Journal(book).pending() == []          # all ticked off
    assert len(server.writes) == 5


def test_round_without_mysql_reports_away_and_keeps_everything(env):
    book, server = env
    save_locally(book, server.client(), make())
    server.down = True
    with pytest.raises(OSError):
        round_(book, server.client())
    server.down = False
    assert len(j.waiting_for_mysql(j.Journal(book))) == 1
    round_(book, server.client())
    assert so_in(server) == "SO-MINE"


def test_a_server_lost_in_the_middle_ends_the_round(env, monkeypatch):
    book, server = env
    db = server.client()
    for number in range(1, 4):
        save_locally(book, db, make(f"FSR-MPR-202611-{number:04d}"))
    real = db.write_report
    calls = []

    def lost_after_one(conn, data):
        calls.append(data["control_no"])
        if len(calls) == 2:
            error = OSError("Lost connection to MySQL server")
            error.errno = 2013
            raise error
        return real(conn, data)

    monkeypatch.setattr(db, "write_report", lost_after_one)
    result = round_(book, db)
    assert result["sent"] == ["FSR-MPR-202611-0001"]
    assert result["away"] is not None and len(calls) == 2  # not tried on
    assert len(j.waiting_for_mysql(j.Journal(book))) == 2


def test_a_newer_save_during_a_send_is_never_overwritten(env, monkeypatch):
    """The record being sent is replaced by a newer save of the same report
    while the send runs: the newer record stays open and is sent next."""
    book, server = env
    db = server.client()
    save_locally(book, db, make(so="FIRST"))
    real = db.write_report

    def newer_save_meanwhile(conn, data):
        save_locally(book, db, make(so="SECOND"), editing=True)
        monkeypatch.setattr(db, "write_report", real)
        return real(conn, data)

    monkeypatch.setattr(db, "write_report", newer_save_meanwhile)
    round_(book, db)
    assert so_in(server) == "FIRST"
    (left,) = j.waiting_for_mysql(j.Journal(book))
    assert left["data"]["general_information"]["so_number"] == "SECOND"
    round_(book, db)
    assert so_in(server) == "SECOND"
    assert j.Journal(book).pending() == []


def test_a_conflict_in_a_round_is_noted_and_nothing_is_written(env):
    book, server = env
    other = make(so="THE OTHER COPY'S")
    other["general_information"]["consignee"] = "Somebody else"
    server.put(other)
    save_locally(book, server.client(), make())
    result = round_(book, server.client())
    (record, conflict, new) = result["conflicts"][0]
    assert new and conflict["kind"] == g.NOT_OWNED
    assert so_in(server) == "THE OTHER COPY'S" and server.writes == []
    (waiting,) = j.conflicts(j.Journal(book))
    assert waiting["id"] == record["id"]
    # a later round leaves it alone: only a decision closes it
    assert round_(book, server.client())["conflicts"] == []
    # ... except at start (with_conflicts), in case MySQL became equal
    server.put(make())
    assert round_(book, server.client(), with_conflicts=True)["sent"] == [
        "FSR-MPR-202611-0001"]
    assert j.conflicts(j.Journal(book)) == []


# ---------- closed, or power lost, while sending ----------

@pytest.mark.parametrize("where", ["before_commit", "after_commit",
                                   "after_ledger"])
def test_power_lost_while_sending_gives_a_correct_result(env, where):
    """The PC loses power in the middle of a send. At the next start the
    round sends again; the guard finds MySQL without the report (it was
    never committed: written now) or equal to it (nothing written, now this
    copy's own). Never twice, never a conflict, nothing lost."""
    book, server = env
    db = server.client()
    save_locally(book, db, make(so="SENT WHEN THE POWER WENT"))
    patch = pytest.MonkeyPatch()        # undone on its own, below

    if where == "before_commit":
        real = db.write_report

        def die(conn, data):
            real(conn, data)
            raise Crash()               # the connection drops: rollback
        patch.setattr(db, "write_report", die)
    elif where == "after_commit":
        def die(self, control_no, report_in_mysql, adopted=False):
            raise Crash()               # committed, ledger not written
        patch.setattr(g.Guard, "_remember", die)
    else:
        def die(journal, record_id):
            raise Crash()               # ledger written, record not ticked
        patch.setattr(j, "finish_mysql", die)

    guard = g.Guard(db, book)
    stores = j.Stores(book, mysql=db, guard=guard)
    conn = db.connect()
    stores.connection = conn
    with pytest.raises(Crash):
        j.send_waiting(j.Journal(book), stores)
    conn.close()                        # MySQL drops the connection
    patch.undo()
    writes_before = list(server.writes)

    # next start: new objects, only the files and MySQL are left
    result = round_(book, server.client(), with_conflicts=True)

    assert result["conflicts"] == [] and result["errors"] == []
    assert result["sent"] == ["FSR-MPR-202611-0001"]
    assert so_in(server) == "SENT WHEN THE POWER WENT"
    assert j.Journal(book).pending() == []
    assert g.Guard(server.client(), book).owns("FSR-MPR-202611-0001")
    if where == "before_commit":
        assert server.writes == ["FSR-MPR-202611-0001"]   # written now
    else:
        assert server.writes == writes_before             # not twice
    # and the next edit is this copy's own: updated, no question
    save_locally(book, db, make(so="EDITED AFTERWARDS"), editing=True)
    assert round_(book, server.client())["sent"] == ["FSR-MPR-202611-0001"]
    assert so_in(server) == "EDITED AFTERWARDS"


def test_window_and_sender_share_the_ledger_without_false_conflicts(env):
    """The window writes the workbook (and renews the ledger's note of it)
    while the sender checks reports. The sender must never see the
    workbook newer than the note - that made own reports look foreign."""
    book, server = env
    db = server.client()
    for number in range(1, 4):
        save_locally(book, db, make(f"FSR-MPR-202611-{number:04d}"))
    round_(book, db)
    stop = threading.Event()
    problems = []

    def sender():
        while not stop.is_set():
            for number in range(1, 4):
                control = f"FSR-MPR-202611-{number:04d}"
                try:
                    g.Guard(db, book).save(make(control, so="SENDER"))
                except g.MySQLConflict as error:
                    problems.append(str(error))
                except g.MySQLBusy:
                    pass

    thread = threading.Thread(target=sender, daemon=True)
    thread.start()
    try:
        for number in range(8):             # the window saving meanwhile
            save_locally(book, db, make(so=f"WINDOW {number}"),
                         editing=True)
            time.sleep(0.01)
    finally:
        stop.set()
        thread.join()
    assert problems == []


def test_record_is_read_by_the_window_while_the_sender_writes_it(env):
    """Found in Phase 3: on Windows the sender's write of the save record
    failed with "Access is denied" while the window was reading the record
    (for the "waiting for MySQL" count), and the whole round was lost."""
    book, server = env
    for number in range(1, 31):
        save_locally(book, server.client(), make(f"FSR-MPR-202611-{number:04d}"))
    stop = threading.Event()
    errors = []

    def window_reading():
        while not stop.is_set():
            try:
                j.waiting_for_mysql(j.Journal(book))
            except Exception as error:      # recorded
                errors.append(error)

    thread = threading.Thread(target=window_reading, daemon=True)
    thread.start()
    try:
        result = round_(book, server.client())
    finally:
        stop.set()
        thread.join()
    assert errors == []
    assert len(result["sent"]) == 30 and j.Journal(book).pending() == []

