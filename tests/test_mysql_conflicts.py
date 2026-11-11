"""Two copies of the program, each with its own workbook, one MySQL
database. For every way a report reaches MySQL - Save, the catch-up, Import
Master Data and Sync to MySQL - four cases: a new number, an owned unchanged
report, an owned report changed in MySQL by someone else, and a report this
copy does not own. Plus the three decisions and the renumbering."""
import json
from datetime import date

import pytest

import fsr_import
import fsr_mysql_guard as g
import fsr_paths
import fsr_renumber
import fsr_save_journal as j
import fsr_storage as s
import fsr_withdrawal
from factories import report
from fake_mysql import FakeServer
from test_import import fresh, master_file, phone_report

REAL = "FSR-MPR-202611-0001"


def make(control=REAL, so="SO-MINE", activity="Receiving", note=None):
    data = report(control, activity, date(2026, 11, 5), "WH",
                  [{"qty": 2, "unit": "Crate", "desc": "Pump", "po": "PO-77",
                    "cargo": "C-1", "ref": f"RCV-{control}-1-01"}], so=so,
                  condition=s.CONDITION_BAD if note else "Good Order")
    data["incident_reports"] = [{"vessel": "MV One", "lines": [note]}] \
        if note else []
    data["other_item_forms"] = {}
    return data


class Copy:
    """One copy of the program: its own folder, workbook, ledger, record."""

    def __init__(self, folder, server, user="Tester"):
        self.folder = folder
        (folder / "excel").mkdir(parents=True)
        (folder / "json").mkdir()
        self.book = folder / "excel" / "Field_Survey_Reports.xlsx"
        self.server = server
        self.db = server.client()
        self.user = user

    def use(self, monkeypatch):
        monkeypatch.setattr(fsr_paths, "DATA_ROOT", self.folder)
        monkeypatch.setattr(fsr_paths, "JSON_DIR", self.folder / "json")
        monkeypatch.setattr(fsr_paths, "EXCEL_DIR", self.folder / "excel")
        return self

    @property
    def guard(self):
        return g.Guard(self.db, self.book, user=self.user)

    @property
    def journal(self):
        return j.Journal(self.book)

    @property
    def stores(self):
        return j.Stores(self.book, mysql=self.db, guard=self.guard)

    def save(self, data, editing=False):
        """What the program's Save does."""
        guard = self.guard
        guard.before_local_write()
        record = j.open_save(self.journal, self.stores, data, editing, False,
                             True)
        outcome = j.run(self.journal, record, self.stores)
        guard.after_local_write()
        return outcome, record

    def catch_up(self):
        return j.repair(self.journal, self.stores)

    def local(self, control=REAL):
        return s.read_report(self.book, control)[
            "general_information"]["so_number"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setitem(s._control_initials, "value", "MPR")
    server = FakeServer()
    mine = Copy(tmp_path / "mine", server).use(monkeypatch)
    return mine, server


def in_mysql(server, control=REAL):
    found = server.get(control)
    return found["general_information"]["so_number"] if found else None


# =====================================================================
# the demonstration from Part 1, now as it must be
# =====================================================================

def ten_real_reports(server):
    for number in range(1, 11):
        server.put(make(f"FSR-MPR-202611-{number:04d}", so=f"REAL-{number}"))


def test_save_from_an_empty_copy_no_longer_overwrites_the_real_report(world):
    mine, server = world
    ten_real_reports(server)
    control = s.generate_control_number(mine.book)
    assert control == REAL                  # its own workbook is empty

    outcome, record = mine.save(make(control, so="TEST FROM THE COPY"))

    assert in_mysql(server) == "REAL-1"     # the real 0001 is untouched
    assert isinstance(outcome["failed"]["mysql"], g.MySQLConflict)
    assert mine.local() == "TEST FROM THE COPY"     # saved on this PC
    assert len(server.reports) == 10 and server.writes == []
    (waiting,) = j.conflicts(mine.journal)
    assert waiting["conflict"]["kind"] == g.NOT_OWNED


def test_catch_up_no_longer_overwrites_and_never_deletes(world):
    mine, server = world
    ten_real_reports(server)
    server.down = True
    mine.save(make(REAL, so="SAVED WHILE OFFLINE"))
    server.down = False

    (entry,) = mine.catch_up()

    assert in_mysql(server) == "REAL-1" and len(server.reports) == 10
    assert entry["conflict"] and not entry["finished"] and entry["local"]
    for number in range(2, 11):
        assert in_mysql(server, f"FSR-MPR-202611-{number:04d}") == \
            f"REAL-{number}"
    assert len(j.conflicts(mine.journal)) == 1


def test_repair_with_nothing_on_record_touches_nothing(world):
    mine, server = world
    ten_real_reports(server)
    before = dict(server.reports)
    assert mine.catch_up() == []
    assert server.reports == before and server.writes == []


# =====================================================================
# Save
# =====================================================================

def test_save_new_number(world):
    mine, server = world
    outcome, _ = mine.save(make())
    assert outcome["failed"] == {} and in_mysql(server) == "SO-MINE"
    assert mine.journal.pending() == [] and mine.guard.owns(REAL)


def test_save_owned_unchanged(world):
    mine, server = world
    mine.save(make())
    outcome, _ = mine.save(make(so="EDITED"), editing=True)
    assert outcome["failed"] == {} and in_mysql(server) == "EDITED"
    assert mine.journal.pending() == []


def test_save_owned_but_changed_in_mysql_by_someone_else(world):
    mine, server = world
    mine.save(make())
    server.put(make(so="CHANGED BY ANOTHER COPY"))

    outcome, _ = mine.save(make(so="EDITED"), editing=True)

    assert outcome["failed"]["mysql"].conflict["kind"] == g.CHANGED_ELSEWHERE
    assert in_mysql(server) == "CHANGED BY ANOTHER COPY"
    assert mine.local() == "EDITED"         # condition 6: local work goes on
    (waiting,) = j.conflicts(mine.journal)
    assert j.local_complete(waiting)


def test_save_report_not_owned(world):
    mine, server = world
    server.put(make(so="THE REAL REPORT"))
    outcome, _ = mine.save(make(so="MINE", note="My incident"))
    assert outcome["failed"]["mysql"].conflict["kind"] == g.NOT_OWNED
    assert in_mysql(server) == "THE REAL REPORT"
    # every local store was written although MySQL was refused
    assert mine.local() == "MINE"
    assert s.load_incident_data(mine.book, REAL)[0]["lines"] == [
        "My incident"]
    assert list(outcome["failed"]) == ["mysql"]


def test_identical_report_is_saved_without_a_question(world):
    mine, server = world
    server.put(make(so="SAME"))
    outcome, _ = mine.save(make(so="SAME"))
    assert outcome["failed"] == {} and mine.journal.pending() == []
    assert server.writes == [] and mine.guard.owns(REAL)


# =====================================================================
# the catch-up
# =====================================================================

def offline(mine, server, data, editing=False):
    server.down = True
    outcome, record = mine.save(data, editing)
    assert list(outcome["failed"]) == ["mysql"]
    server.down = False
    return record


def test_catch_up_new_number(world):
    mine, server = world
    offline(mine, server, make())
    (entry,) = mine.catch_up()
    assert entry["did"] == ["mysql"] and entry["finished"]
    assert in_mysql(server) == "SO-MINE" and mine.journal.pending() == []


def test_catch_up_owned_unchanged(world):
    mine, server = world
    mine.save(make())
    offline(mine, server, make(so="EDITED OFFLINE"), editing=True)
    (entry,) = mine.catch_up()
    assert entry["finished"] and not entry["conflict"]
    assert in_mysql(server) == "EDITED OFFLINE"


def test_catch_up_owned_but_changed_by_someone_else(world):
    mine, server = world
    mine.save(make())
    offline(mine, server, make(so="EDITED OFFLINE"), editing=True)
    server.put(make(so="CHANGED BY ANOTHER COPY"))

    (entry,) = mine.catch_up()

    assert entry["conflict"] and not entry["finished"]
    assert in_mysql(server) == "CHANGED BY ANOTHER COPY"
    (waiting,) = j.conflicts(mine.journal)
    assert waiting["conflict"]["kind"] == g.CHANGED_ELSEWHERE
    lines, attention = j.describe([entry])
    assert "NOT sent to MySQL" in lines[0] and "your decision" in lines[0]
    assert not attention                     # no box at every start


def test_catch_up_report_not_owned(world):
    mine, server = world
    offline(mine, server, make(so="MINE"))
    server.put(make(so="THE REAL REPORT"))
    (entry,) = mine.catch_up()
    assert entry["conflict"] and in_mysql(server) == "THE REAL REPORT"
    # asking again and again changes nothing and loses nothing
    for _ in range(3):
        mine.catch_up()
    assert in_mysql(server) == "THE REAL REPORT" and server.writes == []
    assert len(j.conflicts(mine.journal)) == 1


def test_a_conflict_does_not_stop_the_other_reports_catching_up(world):
    mine, server = world
    server.down = True
    mine.save(make(REAL, so="MINE"))
    mine.save(make("FSR-MPR-202611-0002", so="SECOND"))
    mine.save(make("FSR-MPR-202611-0003", so="THIRD"))
    server.down = False
    server.put(make(REAL, so="THE REAL REPORT"))

    entries = mine.catch_up()

    assert in_mysql(server, "FSR-MPR-202611-0002") == "SECOND"
    assert in_mysql(server, "FSR-MPR-202611-0003") == "THIRD"
    assert in_mysql(server) == "THE REAL REPORT"
    assert sum(e["conflict"] for e in entries) == 1
    assert len(mine.journal.pending()) == 1


# =====================================================================
# Import Master Data
# =====================================================================

def do_import(mine, *reports):
    data = fresh(master_file(*reports))
    guard = mine.guard
    guard.before_local_write()
    summary = fsr_import.import_master_data(mine.book, data)
    guard.after_local_write()
    result = j.send_to_mysql(mine.journal, guard, summary["saved_reports"])
    return summary, result


def test_import_new_number(world):
    mine, server = world
    summary, result = do_import(mine, phone_report("FSR-ABC-202610-0001"))
    assert result["written"] == ["FSR-ABC-202610-0001"]
    assert in_mysql(server, "FSR-ABC-202610-0001") == "SO-PHONE"
    assert j.conflicts(mine.journal) == []


def test_import_update_of_an_owned_unchanged_report(world):
    mine, server = world
    do_import(mine, phone_report("FSR-ABC-202610-0001", so="FIRST"))
    summary, result = do_import(mine, phone_report(
        "FSR-ABC-202610-0001", so="CHANGED ON THE PHONE",
        saved="27-Oct-2026 09:00"))
    assert summary["updated"] == ["FSR-ABC-202610-0001"]
    assert result["written"] == ["FSR-ABC-202610-0001"]
    assert in_mysql(server, "FSR-ABC-202610-0001") == "CHANGED ON THE PHONE"


def test_import_update_of_a_report_changed_in_mysql_by_someone_else(world):
    mine, server = world
    do_import(mine, phone_report("FSR-ABC-202610-0001", so="FIRST"))
    server.put(make("FSR-ABC-202610-0001", so="CHANGED BY ANOTHER COPY"))

    summary, result = do_import(mine, phone_report(
        "FSR-ABC-202610-0001", so="CHANGED ON THE PHONE",
        saved="27-Oct-2026 09:00"))

    assert summary["updated"] == ["FSR-ABC-202610-0001"]   # workbook: yes
    assert result["written"] == []
    assert in_mysql(server, "FSR-ABC-202610-0001") == \
        "CHANGED BY ANOTHER COPY"
    (waiting,) = j.conflicts(mine.journal)
    assert waiting["conflict"]["kind"] == g.CHANGED_ELSEWHERE
    assert waiting["local_done"] and waiting["control"] == \
        "FSR-ABC-202610-0001"


def test_import_number_that_mysql_holds_from_another_copy(world):
    """Free in this workbook, so the import keeps the phone's number - but
    MySQL has another report under it."""
    mine, server = world
    server.put(make("FSR-ABC-202610-0001", so="ANOTHER COPY'S REPORT"))

    summary, result = do_import(mine, phone_report("FSR-ABC-202610-0001"),
                                phone_report("FSR-ABC-202610-0002",
                                             so="SECOND"))

    assert summary["added"] == ["FSR-ABC-202610-0001", "FSR-ABC-202610-0002"]
    assert result["written"] == ["FSR-ABC-202610-0002"]    # the rest goes on
    assert in_mysql(server, "FSR-ABC-202610-0001") == \
        "ANOTHER COPY'S REPORT"
    assert [c["control"] for _, c in result["conflicts"]] == [
        "FSR-ABC-202610-0001"]
    assert len(j.conflicts(mine.journal)) == 1
    assert s.read_report(mine.book, "FSR-ABC-202610-0001")[
        "general_information"]["so_number"] == "SO-PHONE"


# =====================================================================
# Sync to MySQL
# =====================================================================

def workbook_reports(mine):
    return s.read_all_reports(mine.book)


def test_sync_preview_and_default_run(world):
    mine, server = world
    server.down = True
    for number, so in ((1, "NEW"), (2, "OWNED"), (3, "CHANGED"),
                       (4, "NOT OWNED"), (5, "SAME")):
        mine.save(make(f"FSR-MPR-202611-000{number}", so=so))
    server.down = False
    for record in mine.journal.pending():       # start from a clean record
        mine.journal.remove(record)
    guard = mine.guard
    guard.save(make("FSR-MPR-202611-0002", so="OWNED, OLDER"))
    guard.save(make("FSR-MPR-202611-0003", so="OLDER"))
    server.put(make("FSR-MPR-202611-0003", so="CHANGED BY ANOTHER COPY"))
    server.put(make("FSR-MPR-202611-0004", so="THE REAL REPORT"))
    server.put(make("FSR-MPR-202611-0005", so="SAME"))
    writes_before = len(server.writes)

    plan = guard.plan(workbook_reports(mine))            # the preview

    assert len(server.writes) == writes_before           # nothing written
    assert sorted(r["control_no"][-1] for r in plan["new"]) == ["1"]
    assert sorted(r["control_no"][-1] for r in plan["update"]) == ["2"]
    assert sorted(r["control_no"][-1] for r in plan["identical"]) == ["5"]
    assert sorted((r["control_no"][-1], c["kind"]) for r, c in plan[
        "conflicts"]) == [("3", g.CHANGED_ELSEWHERE), ("4", g.NOT_OWNED)]

    # the default run: nothing ticked
    result = j.send_to_mysql(mine.journal, guard, workbook_reports(mine))

    assert sorted(result["written"]) == ["FSR-MPR-202611-0001",
                                         "FSR-MPR-202611-0002"]
    assert in_mysql(server, "FSR-MPR-202611-0002") == "OWNED"
    assert in_mysql(server, "FSR-MPR-202611-0003") == \
        "CHANGED BY ANOTHER COPY"
    assert in_mysql(server, "FSR-MPR-202611-0004") == "THE REAL REPORT"
    assert len(j.conflicts(mine.journal)) == 2
    assert not mine.guard.replaced_dir.exists()

    # ticking one: only that one is replaced, and its old version is kept
    result = j.send_to_mysql(mine.journal, guard, workbook_reports(mine),
                             replace=["FSR-MPR-202611-0004"])
    assert result["written"] == ["FSR-MPR-202611-0004"]
    assert in_mysql(server, "FSR-MPR-202611-0004") == "NOT OWNED"
    assert in_mysql(server, "FSR-MPR-202611-0003") == \
        "CHANGED BY ANOTHER COPY"
    assert len(list(mine.guard.replaced_dir.glob("*.json"))) == 1
    assert [r["control"] for r in j.conflicts(mine.journal)] == [
        "FSR-MPR-202611-0003"]


def test_sync_from_an_empty_workbook_writes_nothing(world):
    mine, server = world
    ten_real_reports(server)
    plan = mine.guard.plan([])
    assert plan == {"new": [], "identical": [], "update": [], "conflicts": []}
    j.send_to_mysql(mine.journal, mine.guard, [])
    assert len(server.reports) == 10 and server.writes == []


def test_first_run_with_ten_existing_reports_asks_nothing(world):
    """The workbook and MySQL hold the same ten reports, saved before this
    fix existed: no ledger."""
    mine, server = world
    for number in range(1, 11):
        data = make(f"FSR-MPR-202611-{number:04d}", so=f"REAL-{number}")
        data["item_lists"][0]["rows"][0]["Unit Price"] = "0.00"
        s.write_report_to_excel(mine.book, data, False)
        server.put(data)                        # MySQL shows it as "0"
    assert not mine.guard.path.exists()

    adopted = mine.guard.adopt_identical(workbook_reports(mine))

    assert len(adopted) == 10 and server.writes == []
    plan = mine.guard.plan(workbook_reports(mine))
    assert len(plan["identical"]) == 10 and plan["conflicts"] == []
    # editing one afterwards goes straight through
    edited = s.read_report(mine.book, "FSR-MPR-202611-0003")
    edited["general_information"]["so_number"] = "REAL-3 EDITED"
    edited["other_item_forms"] = {}
    outcome, _ = mine.save(edited, editing=True)
    assert outcome["failed"] == {}
    assert in_mysql(server, "FSR-MPR-202611-0003") == "REAL-3 EDITED"


# =====================================================================
# the three decisions
# =====================================================================

def conflict_for(mine, server, so="MINE", note="My incident"):
    server.put(make(so="THE REAL REPORT"))
    mine.save(make(so=so, note=note))
    (waiting,) = j.conflicts(mine.journal)
    return waiting


def test_keep_mysql_writes_nothing_and_closes_the_conflict(world):
    mine, server = world
    waiting = conflict_for(mine, server)

    j.resolve_keep(mine.journal, waiting["id"])

    assert in_mysql(server) == "THE REAL REPORT" and server.writes == []
    assert mine.journal.pending() == []
    assert mine.local() == "MINE"               # my report stays on this PC
    assert not mine.guard.replaced_dir.exists()
    assert mine.catch_up() == []                # and is not sent later


def test_replace_is_deliberate_and_keeps_the_replaced_version(world):
    mine, server = world
    waiting = conflict_for(mine, server)

    outcome = j.resolve_replace(mine.journal, mine.stores, waiting["id"])

    assert outcome["failed"] == {} and in_mysql(server) == "MINE"
    assert mine.journal.pending() == []
    (kept,) = mine.guard.replaced_dir.glob("*.json")
    record = json.loads(kept.read_text(encoding="utf-8"))
    assert record["report"]["general_information"]["so_number"] == \
        "THE REAL REPORT"
    assert record["replaced_by"] == "Tester" and record["control_no"] == REAL
    assert (mine.guard.replaced_dir / "replaced_log.csv").exists()


def test_a_replace_decision_is_never_left_standing(world):
    """If the replacement cannot be done now, the decision is dropped: it
    must be made again, it is never carried out later on its own."""
    mine, server = world
    waiting = conflict_for(mine, server)
    server.down = True
    outcome = j.resolve_replace(mine.journal, mine.stores, waiting["id"])
    assert "mysql" in outcome["failed"]
    (still,) = mine.journal.pending()
    assert "decision" not in still
    server.down = False
    mine.catch_up()
    assert in_mysql(server) == "THE REAL REPORT"    # not replaced silently


def test_renumber_changes_the_report_everywhere_on_this_pc(world):
    mine, server = world
    # another report of mine refers to the one that will be renumbered
    waiting = conflict_for(mine, server)
    assert s.read_report(mine.book, REAL)["item_lists"][0]["rows"][0][
        "Receiving Ref"] == f"RCV-{REAL}-1-01"
    s.save_other_item_forms(mine.book, REAL, {"Loading": [{
        "name": "Item List 1", "rows": [{h: "" for h in s.ITEM_LINE_HEADERS}
                                        | {"Receiving Ref":
                                           f"RCV-{REAL}-1-01"}]}]})
    from warehouse import store
    side = store.SideStore(mine.book)
    side.set_case_status(REAL, "Open", "Clerk", "damaged crate")
    new = fsr_renumber.next_free(mine.book, REAL, server.client(
    ).control_numbers())
    assert new == "FSR-MPR-202611-0002"

    outcome = j.resolve_renumber(
        mine.journal, mine.stores, waiting["id"], new,
        lambda old, number: fsr_renumber.renumber_report(mine.book, old,
                                                         number))

    assert outcome["failed"] == {} and mine.journal.pending() == []
    # MySQL: theirs untouched, mine under the new number
    assert in_mysql(server) == "THE REAL REPORT"
    assert in_mysql(server, new) == "MINE"
    # the workbook
    assert [e[0] for e in s.list_saved_reports(mine.book)] == [new]
    moved = s.read_report(mine.book, new)
    assert moved["general_information"]["so_number"] == "MINE"
    assert moved["item_lists"][0]["rows"][0]["Receiving Ref"] == \
        f"RCV-{new}-1-01"
    # the incident file and the item forms file
    assert moved["incident_reports"][0]["lines"] == ["My incident"]
    assert not s.incident_json_path(mine.book, REAL).exists()
    assert json.loads(s.incident_json_path(mine.book, new).read_text(
        encoding="utf-8"))["control_no"] == new
    forms = s.load_other_item_forms(mine.book, new)
    assert forms["Loading"][0]["rows"][0]["Receiving Ref"] == \
        f"RCV-{new}-1-01"
    assert not s.other_item_forms_path(mine.book, REAL).exists()
    # PO_Master and the warehouse side file
    wb = s.load_workbook(mine.book.with_name(fsr_paths.PO_MASTER_NAME),
                         data_only=True)
    controls = {row[0] for row in wb.active.iter_rows(min_row=2,
                                                      values_only=True)}
    assert controls == {new}
    assert new in store.SideStore(mine.book).case_statuses()
    assert REAL not in [e["control_no"] for e in store.SideStore(
        mine.book).data["case_status"]]
    # this copy now owns the new number
    assert mine.guard.owns(new)


def test_renumber_follows_withdrawals_that_point_at_the_report(world):
    mine, server = world
    s.write_report_to_excel(mine.book, make(REAL, so="RECEIVED"), False)
    lookup = fsr_withdrawal.find_po(mine.book, "PO-77")
    row = fsr_withdrawal.new_row(lookup.lines[0])
    fsr_withdrawal.set_quantity(row, 1)
    linked = report("FSR-MPR-202611-0002", "Withdrawal", date(2026, 11, 6),
                    "WH", [], so="SO-WD")
    linked["item_lists"] = [{"name": "Item List 1", "rows": [row]}]
    book = mine.book.with_name(fsr_paths.WITHDRAWAL_WORKBOOK_NAME)
    fsr_withdrawal.write_withdrawal_report(book, linked, False, mine.book)
    before = fsr_withdrawal.read_report(book, "FSR-MPR-202611-0002")[
        "item_lists"][0]["rows"][0]
    assert before[fsr_withdrawal.SOURCE_CONTROL_HEADER] == REAL

    fsr_renumber.renumber_report(mine.book, REAL, "FSR-MPR-202611-0009")

    after = fsr_withdrawal.read_report(book, "FSR-MPR-202611-0002")[
        "item_lists"][0]["rows"][0]
    assert after[fsr_withdrawal.SOURCE_CONTROL_HEADER] == \
        "FSR-MPR-202611-0009"
    assert after["Receiving Ref"] == before["Receiving Ref"].replace(
        REAL, "FSR-MPR-202611-0009")
    assert fsr_withdrawal.find_po(mine.book, "PO-77").lines   # still linked


def test_renumber_refuses_a_number_that_is_taken_here(world):
    mine, _ = world
    s.write_report_to_excel(mine.book, make(REAL), False)
    s.write_report_to_excel(mine.book, make("FSR-MPR-202611-0002"), False)
    with pytest.raises(fsr_renumber.RenumberError, match="already used"):
        fsr_renumber.renumber_report(mine.book, REAL, "fsr-mpr-202611-0002")
    with pytest.raises(fsr_renumber.RenumberError, match="not in this PC"):
        fsr_renumber.renumber_report(mine.book, "FSR-XXX-1", "FSR-XXX-2")
    with pytest.raises(fsr_renumber.RenumberError, match="must differ"):
        fsr_renumber.renumber_report(mine.book, REAL, REAL.lower())
    assert [e[0] for e in s.list_saved_reports(mine.book)] == [
        "FSR-MPR-202611-0002", REAL]


def test_next_free_number_avoids_both_places(world):
    mine, server = world
    s.write_report_to_excel(mine.book, make(REAL), False)
    taken = ["FSR-MPR-202611-0002", "FSR-MPR-202611-0003",
             "FSR-ABC-202611-0009"]
    assert fsr_renumber.next_free(mine.book, REAL, taken) == \
        "FSR-MPR-202611-0004"


# =====================================================================
# two copies, one database
# =====================================================================

def test_two_copies_do_not_overwrite_each_other(world, tmp_path,
                                                monkeypatch):
    mine, server = world
    mine.save(make(REAL, so="FROM THE FIRST COPY"))

    other = Copy(tmp_path / "other", server, "Other").use(monkeypatch)
    assert s.generate_control_number(other.book) == REAL    # blind
    outcome, _ = other.save(make(REAL, so="FROM THE SECOND COPY"))

    assert "mysql" in outcome["failed"]
    assert in_mysql(server) == "FROM THE FIRST COPY"
    assert other.local() == "FROM THE SECOND COPY"
    # the second copy takes the next number that is free in both places
    (waiting,) = j.conflicts(other.journal)
    new = fsr_renumber.next_free(other.book, REAL,
                                 other.db.control_numbers())
    j.resolve_renumber(other.journal, other.stores, waiting["id"], new,
                       lambda old, number: fsr_renumber.renumber_report(
                           other.book, old, number))
    assert in_mysql(server) == "FROM THE FIRST COPY"
    assert in_mysql(server, new) == "FROM THE SECOND COPY"
    assert len(server.reports) == 2
