"""The MySQL guard: a copy never overwrites a report it does not own.
Several copies share one FakeServer, each with its own workbook folder."""
import csv
import json
import os
import time
from datetime import date

import pytest

import fsr_mysql_guard as g
import fsr_paths
import fsr_storage as s
from factories import report
from fake_mysql import FakeServer

REAL = "FSR-MPR-202611-0001"


def make(control=REAL, so="SO-MINE", price="0.00", qty=2):
    data = report(control, "Receiving", date(2026, 11, 5), "WH",
                  [{"qty": qty, "unit": "Crate", "desc": "Pump",
                    "po": "PO-77", "cargo": "C-1"}], so=so)
    data["item_lists"][0]["rows"][0]["Unit Price"] = price
    data["other_item_forms"] = {}
    return data


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    (tmp_path / "excel").mkdir()
    book = tmp_path / "excel" / "Field_Survey_Reports.xlsx"
    server = FakeServer()
    return book, server, g.Guard(server.client(), book, user="Test Owner")


def so_in(server, control=REAL):
    return server.get(control)["general_information"]["so_number"]


# ---------- the four cases ----------

def test_new_number_is_written_and_remembered(env):
    book, server, guard = env
    assert guard.look(make()) == "new"
    assert guard.save(make()) == ("written", [])
    assert so_in(server) == "SO-MINE"
    assert guard.owns(REAL)
    ledger = json.loads(guard.path.read_text(encoding="utf-8"))
    assert list(ledger["reports"]) == [REAL.casefold()]
    assert ledger["copy_id"] and "SO-MINE" not in guard.path.read_text()


def test_owned_unchanged_report_is_updated(env):
    book, server, guard = env
    guard.save(make())
    assert guard.look(make(so="SO-EDITED")) == "update"
    assert guard.save(make(so="SO-EDITED")) == ("written", [])
    assert so_in(server) == "SO-EDITED"
    assert guard.save(make(so="SO-AGAIN"))[0] == "written"   # still mine


def test_owned_report_changed_in_mysql_by_someone_else_is_a_conflict(env):
    book, server, guard = env
    guard.save(make())
    server.put(make(so="CHANGED BY ANOTHER COPY"))

    with pytest.raises(g.MySQLConflict) as caught:
        guard.save(make(so="SO-EDITED"))

    conflict = caught.value.conflict
    assert conflict["kind"] == g.CHANGED_ELSEWHERE
    assert "changed in MySQL by another copy" in conflict["text"]
    assert conflict["mine"]["so_number"] == "SO-EDITED"
    assert conflict["theirs"]["so_number"] == "CHANGED BY ANOTHER COPY"
    assert any("so_number" in line for line in conflict["differences"])
    assert so_in(server) == "CHANGED BY ANOTHER COPY"     # nothing written
    assert server.writes == [REAL]                        # only the first


def test_report_this_copy_does_not_own_is_a_conflict(env):
    book, server, guard = env
    server.put(make(so="THE REAL REPORT"))

    with pytest.raises(g.MySQLConflict) as caught:
        guard.save(make(so="TEST FROM THE COPY"))

    assert caught.value.conflict["kind"] == g.NOT_OWNED
    assert "did not put there" in str(caught.value)
    assert so_in(server) == "THE REAL REPORT" and server.writes == []
    assert not guard.owns(REAL)
    assert not guard.replaced_dir.exists()


# ---------- condition 4: identical in value ----------

def test_identical_in_value_is_adopted_without_writing(env):
    """'0.00' here and '0' in MySQL are the same report."""
    book, server, guard = env
    server.put(make(so="SAME", price="0.00"))
    assert server.get(REAL)["item_lists"][0]["rows"][0]["Unit Price"] == "0"

    assert guard.look(make(so="SAME", price="0.00")) == "identical"
    assert guard.save(make(so="SAME", price="0.00")) == ("identical", [])

    assert server.writes == [] and guard.owns(REAL)
    assert guard.save(make(so="SAME, EDITED"))[0] == "written"   # now mine


@pytest.mark.parametrize("mine, theirs", [
    ("0.00", "0"), ("5", "5.000"), ("1,250.50", "1250.5"), ("", None),
    ("  12 ", "12"),
])
def test_display_only_differences_are_equal(mine, theirs):
    a, b = make(price=mine), make(price=theirs)
    assert g.same_value(a, b) and g.fingerprint(a) == g.fingerprint(b)


def test_other_display_only_differences():
    a, b = make(), make()
    a["general_information"]["consignee"] = "  ACME Corp "
    b["general_information"]["consignee"] = "ACME Corp"
    a["declared_goods"] = [{"description": "Pump", "quantity": "2.0",
                            "packaging": "Crate"}]
    b["declared_goods"] = [{"description": "Pump", "quantity": "2",
                            "packaging": "Crate"}]
    a["incident_reports"] = []
    b.pop("incident_reports")
    a["other_item_forms"] = {"Loading": []}       # MySQL does not keep it
    b["last_saved"] = "10-Nov-2026 07:26"
    b["incident_error"] = ""
    assert g.same_value(a, b)


@pytest.mark.parametrize("change", [
    lambda r: r["general_information"].update(so_number="so-mine"),   # case
    lambda r: r["documents_used"].update(dr_number="0282050"),
    lambda r: r["item_lists"][0]["rows"][0].update(Quantity="3"),
    lambda r: r["item_lists"][0]["rows"].append(dict(
        r["item_lists"][0]["rows"][0])),
    lambda r: r.update(cargo_condition="Bad Order"),
    lambda r: r["findings_and_remarks"].append("New remark"),
])
def test_real_differences_are_not_equal(change):
    a, b = make(), make()
    b["documents_used"]["dr_number"] = "282050"
    a["documents_used"]["dr_number"] = "282050"
    change(a)
    assert not g.same_value(a, b)
    assert g.differences(a, b)


def test_first_run_adopts_ten_existing_reports_without_questions(env):
    """The workbook and MySQL hold the same ten reports; no ledger yet."""
    book, server, guard = env
    mine = []
    for number in range(1, 11):
        data = make(f"FSR-MPR-202611-{number:04d}", so=f"REAL-{number}",
                    price="0.00")
        mine.append(data)
        server.put(data)
    assert not guard.path.exists()

    adopted = guard.adopt_identical(mine)

    assert len(adopted) == 10 and server.writes == []
    plan = guard.plan(mine)
    assert len(plan["identical"]) == 10 and plan["conflicts"] == []
    # editing one of them later needs no question
    assert guard.save(make("FSR-MPR-202611-0003", so="REAL-3 edited"))[
        0] == "written"
    # a report that differs is NOT adopted
    server.put(make("FSR-MPR-202611-0011", so="SOMEONE ELSE'S"))
    assert guard.adopt_identical(
        [make("FSR-MPR-202611-0011", so="MINE")]) == []
    assert not guard.owns("FSR-MPR-202611-0011")


# ---------- condition 3: the ledger ----------

def write_and_change_elsewhere(guard, server):
    guard.save(make())
    guard.save(make("FSR-MPR-202611-0002", so="SECOND"))


@pytest.mark.parametrize("damage", ["missing", "garbage", "wrong_shape",
                                    "older_than_workbook"])
def test_missing_or_damaged_ledger_never_overwrites(env, damage):
    book, server, guard = env
    write_and_change_elsewhere(guard, server)
    if damage == "missing":
        guard.path.unlink()
    elif damage == "garbage":
        guard.path.write_text("{not json", encoding="utf-8")
    elif damage == "wrong_shape":
        guard.path.write_text(json.dumps({"reports": {"x": 1}}),
                              encoding="utf-8")
    else:
        book.write_bytes(b"restored from a backup")
        os.utime(book, (time.time() + 60, time.time() + 60))
        assert guard.is_stale()

    assert not guard.owns(REAL)
    with pytest.raises(g.MySQLConflict) as caught:       # asks, never writes
        guard.save(make(so="EDITED"))
    assert caught.value.conflict["kind"] == g.NOT_OWNED
    assert so_in(server) == "SO-MINE"
    # an identical report is still adopted silently
    assert guard.save(make("FSR-MPR-202611-0002", so="SECOND")) == (
        "identical", [])


def test_stale_ledger_is_emptied_before_the_programs_own_write(env):
    """Otherwise the program's own workbook write would make an old ledger
    look current again."""
    book, server, guard = env
    write_and_change_elsewhere(guard, server)
    book.write_bytes(b"restored from a backup")
    os.utime(book, (time.time() + 60, time.time() + 60))

    guard.before_local_write()              # the program is about to save
    os.utime(book, None)
    guard.after_local_write()               # ... and has saved

    assert not guard.is_stale()             # current again - but empty
    assert not guard.owns(REAL)
    with pytest.raises(g.MySQLConflict):
        guard.save(make(so="EDITED"))


def test_ledger_follows_the_workbook_in_normal_use(env):
    book, server, guard = env
    for round_no in range(3):
        guard.before_local_write()
        book.write_bytes(b"saved by the program %d" % round_no)
        guard.after_local_write()
        assert not guard.is_stale()
        assert guard.save(make(so=f"SAVE {round_no}"))[0] in (
            "written", "identical")
    assert guard.owns(REAL)


def test_offline_save_then_catch_up_needs_no_question(env):
    """Saved locally while MySQL was away: the workbook is newer than the
    last MySQL write, but the ledger was kept current by the program."""
    book, server, guard = env
    guard.before_local_write()
    book.write_bytes(b"1")
    guard.after_local_write()
    guard.save(make())
    time.sleep(0.05)
    guard.before_local_write()
    book.write_bytes(b"2 - saved while MySQL was away")
    guard.after_local_write()
    assert guard.save(make(so="SENT LATER"))[0] == "written"


# ---------- condition 1 and 2: the deliberate replace ----------

def test_replace_keeps_the_replaced_version_and_logs_it(env):
    book, server, guard = env
    server.put(make(so="THE REAL REPORT", qty=7))

    assert guard.save(make(so="MINE"), g.REPLACE)[0] == "written"

    assert so_in(server) == "MINE" and guard.owns(REAL)
    kept = sorted(guard.replaced_dir.glob("*.json"))
    assert len(kept) == 1 and kept[0].name.startswith(REAL + "_")
    record = json.loads(kept[0].read_text(encoding="utf-8"))
    assert record["report"]["general_information"]["so_number"] == \
        "THE REAL REPORT"
    assert record["report"]["item_lists"][0]["rows"][0]["Quantity"] == "7"
    assert record["replaced_by"] == "Test Owner"
    assert record["control_no"] == REAL and record["copy_id"]
    assert record["copy_workbook"] == str(book) and record["computer"]
    assert record["replaced_at"] and record["reason"] == g.NOT_OWNED
    with open(guard.replaced_dir / "replaced_log.csv", newline="",
              encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 1 and rows[0]["control_no"] == REAL
    assert rows[0]["replaced_by"] == "Test Owner"
    assert rows[0]["kept_as"] == kept[0].name
    assert rows[0]["copy_workbook"] == str(book)


def test_nothing_is_replaced_when_the_old_version_cannot_be_kept(
        env, monkeypatch):
    book, server, guard = env
    server.put(make(so="THE REAL REPORT"))

    def no_room(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(s, "write_json_atomic", no_room)
    with pytest.raises(OSError, match="disk full"):
        guard.save(make(so="MINE"), g.REPLACE)
    assert so_in(server) == "THE REAL REPORT" and server.writes == []


def test_a_replaced_version_can_be_put_back(env):
    book, server, guard = env
    server.put(make(so="THE REAL REPORT"))
    guard.save(make(so="MINE"), g.REPLACE)
    (first,) = guard.replaced_dir.glob("*.json")

    assert guard.put_back(first) == REAL

    assert so_in(server) == "THE REAL REPORT"
    kept = sorted(guard.replaced_dir.glob("*.json"))
    assert len(kept) == 2                 # "MINE" was kept before going back
    assert any(json.loads(k.read_text(encoding="utf-8"))["report"][
        "general_information"]["so_number"] == "MINE" for k in kept)
    with pytest.raises(ValueError, match="not a kept MySQL report"):
        guard.put_back(guard.path)


def test_replace_is_not_needed_and_keeps_nothing_for_an_owned_report(env):
    book, server, guard = env
    guard.save(make())
    guard.save(make(so="EDITED"))
    assert not guard.replaced_dir.exists()


# ---------- condition 5: check and write together ----------

def test_two_copies_saving_at_the_same_moment_cannot_both_pass(env,
                                                               tmp_path):
    book, server, guard = env
    other_book = tmp_path / "other" / "Field_Survey_Reports.xlsx"
    other_book.parent.mkdir()
    other = g.Guard(server.client(), other_book, user="Other copy")
    real_write = guard.db.write_report
    seen = {}

    def write_while_the_other_copy_tries(conn, data):
        # the first copy is between its check and its write: the second
        # copy now tries the very same number
        with pytest.raises(g.MySQLBusy):
            other.save(make(so="FROM THE OTHER COPY"))
        seen["other_was_refused"] = True
        return real_write(conn, data)

    guard.db.write_report = write_while_the_other_copy_tries
    assert guard.save(make(so="FIRST"))[0] == "written"
    assert seen == {"other_was_refused": True}
    assert so_in(server) == "FIRST" and server.writes == [REAL]
    assert server.locks == {}                   # released afterwards

    # afterwards the second copy is checked against what is there now
    with pytest.raises(g.MySQLConflict):
        other.save(make(so="FROM THE OTHER COPY"))
    assert so_in(server) == "FIRST"


def test_lock_is_released_after_a_conflict_and_after_an_error(env):
    book, server, guard = env
    server.put(make(so="THEIRS"))
    with pytest.raises(g.MySQLConflict):
        guard.save(make())
    assert server.locks == {}

    def broken(conn, data):
        raise RuntimeError("Data too long for column")

    guard.db.write_report = broken
    with pytest.raises(RuntimeError):
        guard.save(make("FSR-MPR-202611-0009"))
    assert server.locks == {} and server.get("FSR-MPR-202611-0009") is None
    assert not guard.owns("FSR-MPR-202611-0009")


def test_check_and_write_use_one_connection(env):
    book, server, guard = env
    guard.save(make())
    assert guard.db.connections == 1


# ---------- many at once (Import, Sync) ----------

def test_plan_sorts_reports_without_writing(env):
    book, server, guard = env
    guard.save(make("FSR-MPR-202611-0002", so="OWNED"))
    guard.save(make("FSR-MPR-202611-0003", so="OWNED, THEN CHANGED"))
    server.put(make("FSR-MPR-202611-0003", so="CHANGED BY ANOTHER"))
    server.put(make("FSR-MPR-202611-0004", so="NOT MINE"))
    server.put(make("FSR-MPR-202611-0005", so="SAME"))
    before = dict(server.reports)

    plan = guard.plan([
        make("FSR-MPR-202611-0001", so="NEW"),
        make("FSR-MPR-202611-0002", so="OWNED, EDITED HERE"),
        make("FSR-MPR-202611-0003", so="MINE"),
        make("FSR-MPR-202611-0004", so="MINE"),
        make("FSR-MPR-202611-0005", so="SAME")])

    assert [r["control_no"][-4:] for r in plan["new"]] == ["0001"]
    assert [r["control_no"][-4:] for r in plan["update"]] == ["0002"]
    assert [r["control_no"][-4:] for r in plan["identical"]] == ["0005"]
    assert [(r["control_no"][-4:], c["kind"]) for r, c in plan[
        "conflicts"]] == [("0003", g.CHANGED_ELSEWHERE),
                          ("0004", g.NOT_OWNED)]
    assert server.reports == before and len(server.writes) == 2


def test_save_many_writes_what_is_safe_and_only_ticked_conflicts(env):
    book, server, guard = env
    server.put(make("FSR-MPR-202611-0004", so="NOT MINE"))
    server.put(make("FSR-MPR-202611-0006", so="NOT MINE EITHER"))
    reports = [make("FSR-MPR-202611-0001", so="NEW"),
               make("FSR-MPR-202611-0004", so="MINE"),
               make("FSR-MPR-202611-0006", so="MINE TOO")]

    result = guard.save_many(reports)

    assert result["written"] == ["FSR-MPR-202611-0001"]
    assert [c["control"] for _, c in result["conflicts"]] == [
        "FSR-MPR-202611-0004", "FSR-MPR-202611-0006"]
    assert so_in(server, "FSR-MPR-202611-0004") == "NOT MINE"

    ticked = guard.save_many(reports, replace=["fsr-mpr-202611-0004"])
    assert ticked["written"] == ["FSR-MPR-202611-0004"]
    assert ticked["identical"] == ["FSR-MPR-202611-0001"]
    assert so_in(server, "FSR-MPR-202611-0004") == "MINE"
    assert so_in(server, "FSR-MPR-202611-0006") == "NOT MINE EITHER"
    assert len(list(guard.replaced_dir.glob("*.json"))) == 1


def test_nothing_is_ever_deleted(env):
    book, server, guard = env
    for number in range(1, 6):
        server.put(make(f"FSR-MPR-202611-{number:04d}", so=f"R{number}"))
    guard.plan([])
    guard.save_many([])
    guard.adopt_identical([])
    guard.save(make("FSR-MPR-202611-0009"))
    assert len(server.reports) == 6


def test_taken_tells_a_new_report_to_pick_another_number(env):
    book, server, guard = env
    server.put(make(so="THEIRS"))
    assert guard.taken(REAL) and not guard.taken("FSR-MPR-202611-0002")
    guard.save(make("FSR-MPR-202611-0002"))
    assert not guard.taken("FSR-MPR-202611-0002")       # my own


def test_stand_in_without_the_guarded_interface_still_works(env):
    """Older tests use a stand-in that only has save_report()."""
    book, _, _ = env

    class Simple:
        saved = []

        def save_report(self, data):
            self.saved.append(data["control_no"])
            return ["note"]

    guard = g.Guard(Simple(), book)
    assert guard.save(make()) == ("written", ["note"])
    assert guard.save_many([make()])["written"] == [REAL]
    assert guard.taken(REAL) is False
