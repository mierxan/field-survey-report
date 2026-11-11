"""A save that stops halfway is finished later: a failure is injected after
every single write, then the repair must bring every store into agreement -
also when the repair itself is interrupted, and when it runs twice."""
import copy
import json
from datetime import date, datetime, timedelta

import pytest

import fsr_paths
import fsr_save_journal as j
import fsr_storage as s
import fsr_withdrawal
from factories import report

CONTROL = "FSR-TST-202611-0001"
STEPS = ["workbook", "incidents", "item_forms", "item_lists", "mysql"]


class Crash(BaseException):
    """The PC loses power: nothing after this line runs, nothing is caught."""


class FakeMySQL:
    def __init__(self):
        self.reports = {}
        self.down = False
        self.calls = 0

    def save_report(self, data):
        self.calls += 1
        if self.down:
            raise OSError("Can't connect to MySQL server on 'localhost'")
        self.reports[s.control_key(data["control_no"])] = copy.deepcopy(data)
        return []


class CrashingStores(j.Stores):
    """The real stores; the 'PC' dies right AFTER the named write (or
    before it, with before=True)."""

    def __init__(self, *args, crash_at=None, before=False, **kw):
        super().__init__(*args, **kw)
        self.crash_at, self.before = crash_at, before
        self.done = []

    def _step(self, name, real, *args):
        if self.crash_at == name and self.before:
            raise Crash(name)
        result = real(*args)
        self.done.append(name)
        if self.crash_at == name:
            raise Crash(name)
        return result

    def workbook(self, record):
        return self._step("workbook", super().workbook, record)

    def incidents(self, record):
        return self._step("incidents", super().incidents, record)

    def item_forms(self, record):
        return self._step("item_forms", super().item_forms, record)

    def item_lists(self, record):
        return self._step("item_lists", super().item_lists, record)

    def mysql(self, record, data):
        return self._step("mysql", super().mysql, record, data)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    (tmp_path / "excel").mkdir()
    book = tmp_path / "excel" / "Field_Survey_Reports.xlsx"
    return book, FakeMySQL()


def bad_order(control=CONTROL, so="SO-1", note="Dent on crate"):
    """A Receiving, Bad Order report: every store has something to hold."""
    data = report(control, "Receiving", date(2026, 11, 5), "WH",
                  [{"qty": 2, "unit": "Crate", "desc": "Pump", "po": "PO-77",
                    "cargo": "C-1"}], so=so,
                  condition=s.CONDITION_BAD)
    data["incident_reports"] = [{"vessel": "MV One", "lines": [note]}]
    row = {h: "" for h in s.ITEM_LINE_HEADERS}
    row.update({"Container / Truck No.": "ABC 123",
                "Description of Goods": "Pipes"})
    data["other_item_forms"] = {"Loading": [{"name": "Item List 1",
                                             "rows": [row]}]}
    return data


def start_save(book, mysql, data=None, editing=False, stores=None, **kw):
    journal = j.Journal(book)
    data = data or bad_order()
    stores = stores or CrashingStores(book, mysql=mysql, **kw)
    record = j.open_save(journal, stores, data, editing, False,
                         mysql is not None)
    return journal, record, stores


def po_master_controls(book):
    path = book.with_name(fsr_paths.PO_MASTER_NAME)
    if not path.exists():
        return []
    wb = s.load_workbook(path, data_only=True)
    return [row[0] for row in wb.active.iter_rows(min_row=2, values_only=True)
            if row and row[0]]


def state(book, mysql, control=CONTROL):
    """What each store holds for the report - compared for agreement."""
    saved = s.read_report(book, control)
    return {
        "workbook_so": saved["general_information"]["so_number"],
        "incident": [r["lines"] for r in s.load_incident_data(book, control)],
        "forms": sorted(s.load_other_item_forms(book, control)),
        "po_master": control in po_master_controls(book),
        "mysql_so": (mysql.reports[s.control_key(control)]
                     ["general_information"]["so_number"]
                     if mysql and s.control_key(control) in mysql.reports
                     else None),
        "mysql_incident": ([r["lines"] for r in mysql.reports[
            s.control_key(control)]["incident_reports"]]
            if mysql and s.control_key(control) in mysql.reports else None),
    }


AGREED = {"workbook_so": "SO-1", "incident": [["Dent on crate"]],
          "forms": ["Loading"], "po_master": True, "mysql_so": "SO-1",
          "mysql_incident": [["Dent on crate"]]}


# ---------- a save that goes through ----------

def test_complete_save_leaves_no_record(env):
    book, mysql = env
    journal, record, stores = start_save(book, mysql)
    assert [r["control"] for r in journal.pending()] == [CONTROL]
    assert set(journal.pending()[0]["steps"].values()) == {"pending"}

    outcome = j.run(journal, record, stores)

    assert outcome["failed"] == {} and outcome["result"]["control"] == CONTROL
    assert stores.done == STEPS
    assert journal.pending() == []
    assert state(book, mysql) == AGREED
    assert j.repair(j.Journal(book), j.Stores(book, mysql=mysql)) == []


def test_record_is_written_before_the_first_write(env):
    book, mysql = env
    journal, record, stores = start_save(book, mysql, crash_at="workbook",
                                         before=True)
    with pytest.raises(Crash):
        j.run(journal, record, stores)
    assert not book.exists()                       # nothing written yet
    on_file = json.loads(journal.path.read_text(encoding="utf-8"))
    assert on_file["version"] == 1
    (saved,) = on_file["saves"]
    assert saved["control"] == CONTROL
    assert saved["steps"] == {step: "pending" for step in STEPS}
    assert saved["data"]["incident_reports"][0]["lines"] == ["Dent on crate"]


def test_steps_follow_the_report():
    good = report("X-1", "Withdrawal", date(2026, 11, 5))
    assert j.steps_for(good, False, False) == [
        "workbook", "incidents", "item_forms"]
    assert j.steps_for(good, True, True) == STEPS            # PO-linked
    assert j.steps_for(bad_order(), False, False) == STEPS[:-1]


# ---------- a failure after each individual write ----------

@pytest.mark.parametrize("crash_at", STEPS)
@pytest.mark.parametrize("before", [False, True])
def test_crash_at_any_write_is_repaired_at_the_next_start(env, crash_at,
                                                          before):
    book, mysql = env
    journal, record, stores = start_save(book, mysql, crash_at=crash_at,
                                         before=before)
    with pytest.raises(Crash):
        j.run(journal, record, stores)
    assert len(j.Journal(book).pending()) == 1     # the record survived

    # "next start": new objects, only the files are left
    result = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))

    assert state(book, mysql) == AGREED
    assert j.Journal(book).pending() == []
    (entry,) = result
    assert entry["control"] == CONTROL and entry["finished"]
    assert entry["failed"] == {} and entry["state"] == ""
    assert len(s.list_saved_reports(book)) == 1    # saved once, not twice


@pytest.mark.parametrize("crash_at", STEPS)
def test_repair_twice_is_the_same_as_once(env, crash_at):
    book, mysql = env
    journal, record, stores = start_save(book, mysql, crash_at=crash_at)
    with pytest.raises(Crash):
        j.run(journal, record, stores)
    j.repair(j.Journal(book), j.Stores(book, mysql=mysql))
    files = {p: p.read_bytes() for p in book.parent.parent.rglob("*")
             if p.is_file()}
    database, calls = copy.deepcopy(mysql.reports), mysql.calls

    again = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))

    assert again == []
    assert {p: p.read_bytes() for p in book.parent.parent.rglob("*")
            if p.is_file()} == files
    assert mysql.reports == database and mysql.calls == calls


@pytest.mark.parametrize("first", STEPS)
@pytest.mark.parametrize("second", STEPS)
def test_crash_during_the_repair_itself(env, first, second):
    """Dies in the save, dies again in the repair, the third run finishes."""
    book, mysql = env
    journal, record, stores = start_save(book, mysql, crash_at=first)
    with pytest.raises(Crash):
        j.run(journal, record, stores)
    try:
        j.repair(j.Journal(book), CrashingStores(book, mysql=mysql,
                                                 crash_at=second))
    except Crash:
        pass

    j.repair(j.Journal(book), j.Stores(book, mysql=mysql))

    assert state(book, mysql) == AGREED
    assert j.Journal(book).pending() == []
    assert len(s.list_saved_reports(book)) == 1


def test_crash_while_updating_an_existing_report(env):
    """The edit that was being saved wins over the older saved version."""
    book, mysql = env
    j.run(*start_save(book, mysql))
    edited = bad_order(so="SO-EDITED", note="Crate split open")
    journal, record, stores = start_save(
        book, mysql, data=edited, editing=True, crash_at="workbook",
        before=True)
    with pytest.raises(Crash):
        j.run(journal, record, stores)
    assert state(book, mysql)["workbook_so"] == "SO-1"   # still the old one

    j.repair(j.Journal(book), j.Stores(book, mysql=mysql))

    assert state(book, mysql) == {
        **AGREED, "workbook_so": "SO-EDITED", "mysql_so": "SO-EDITED",
        "incident": [["Crate split open"]],
        "mysql_incident": [["Crate split open"]]}
    assert len(s.list_saved_reports(book)) == 1


def test_good_order_edit_removes_the_old_incident_file_on_repair(env):
    book, mysql = env
    j.run(*start_save(book, mysql))
    good = bad_order()
    good["cargo_condition"] = s.CONDITION_GOOD
    good["incident_reports"] = []
    journal, record, stores = start_save(book, mysql, data=good,
                                         editing=True, crash_at="workbook")
    with pytest.raises(Crash):
        j.run(journal, record, stores)
    assert s.load_incident_data(book, CONTROL) != []     # stale file

    j.repair(j.Journal(book), j.Stores(book, mysql=mysql))

    assert s.load_incident_data(book, CONTROL) == []
    assert s.read_report(book, CONTROL)["cargo_condition"] == s.CONDITION_GOOD


# ---------- a write that fails without a crash ----------

def test_failed_workbook_write_is_raised_and_nothing_is_kept(env,
                                                             monkeypatch):
    book, mysql = env
    journal, record, stores = start_save(book, mysql)

    def locked(*args, **kwargs):
        raise PermissionError("open in Excel")

    monkeypatch.setattr(s, "write_report_to_excel", locked)
    with pytest.raises(PermissionError):
        j.run(journal, record, stores)
    j.discard(journal, record)        # what the program does: user was told
    assert journal.pending() == [] and not book.exists()
    assert mysql.reports == {}


@pytest.mark.parametrize("step", ["incidents", "item_forms", "item_lists"])
def test_one_failing_store_does_not_stop_the_others(env, monkeypatch, step):
    book, mysql = env
    journal, record, stores = start_save(book, mysql)

    def failing(*args, **kwargs):
        raise PermissionError("in use")

    monkeypatch.setattr(stores, step, failing)
    outcome = j.run(journal, record, stores)

    assert list(outcome["failed"]) == [step]
    (left,) = journal.pending()
    assert [name for name, value in left["steps"].items()
            if value == "pending"] == [step]
    assert left["errors"] == {step: "in use"}
    assert not j.local_complete(left)
    assert mysql.reports != {}                    # the later steps ran

    (entry,) = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))
    assert entry["did"] == [step] and entry["finished"]
    assert state(book, mysql) == AGREED
    lines, attention = j.describe([entry])
    assert attention and "It was completed now" in lines[0]
    assert j.STEP_WORDS[step] in lines[0]


def test_store_that_keeps_failing_stays_on_record(env, monkeypatch):
    book, mysql = env
    journal, record, stores = start_save(book, mysql, crash_at="workbook")
    with pytest.raises(Crash):
        j.run(journal, record, stores)

    def failing(*args, **kwargs):
        raise OSError("disk full")

    real = s.save_incident_data
    monkeypatch.setattr(s, "save_incident_data", failing)
    for _ in range(2):
        (entry,) = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))
        assert entry["failed"] == {"incidents": "disk full"}
        assert entry["waiting"] == ["incidents"] and not entry["finished"]
    lines, attention = j.describe([entry])
    assert attention
    assert "could still NOT be written (disk full)" in "\n".join(lines)
    monkeypatch.setattr(s, "save_incident_data", real)   # the disk has room
    j.repair(j.Journal(book), j.Stores(book, mysql=mysql))
    assert state(book, mysql)["incident"] == [["Dent on crate"]]
    assert j.Journal(book).pending() == []


# ---------- MySQL is not reachable: normal, not an error ----------

def test_mysql_down_saves_locally_and_catches_up_later(env):
    book, mysql = env
    mysql.down = True
    journal, record, stores = start_save(book, mysql)

    outcome = j.run(journal, record, stores)

    assert list(outcome["failed"]) == ["mysql"]
    (left,) = journal.pending()
    assert j.local_complete(left)                 # this PC is complete
    local = {k: v for k, v in state(book, mysql).items()
             if not k.startswith("mysql")}
    assert local == {k: v for k, v in AGREED.items()
                     if not k.startswith("mysql")}

    # offline start: MySQL is not even tried
    calls = mysql.calls
    assert j.repair(j.Journal(book), j.Stores(book, mysql=mysql),
                    mysql=False) == []
    assert mysql.calls == calls and len(j.Journal(book).pending()) == 1

    # still down
    (entry,) = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))
    assert entry["local"] and not entry["finished"]
    lines, attention = j.describe([entry])
    assert not attention and lines == [f"{CONTROL}: still waiting for MySQL."]

    # back again
    mysql.down = False
    (entry,) = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))
    assert entry["did"] == ["mysql"] and entry["finished"]
    lines, attention = j.describe([entry])
    assert not attention and lines == [f"{CONTROL}: now also saved to MySQL."]
    assert state(book, mysql) == AGREED
    assert j.Journal(book).pending() == []


def test_absent_mysql_costs_one_attempt_not_one_per_report(env):
    book, mysql = env
    mysql.down = True
    for number in (1, 2, 3):
        j.run(*start_save(book, mysql, data=bad_order(
            f"FSR-TST-202611-000{number}", so=f"SO-{number}")))
    assert len(j.Journal(book).pending()) == 3
    mysql.calls = 0
    j.repair(j.Journal(book), j.Stores(book, mysql=mysql))
    assert mysql.calls == 1
    mysql.down = False
    j.repair(j.Journal(book), j.Stores(book, mysql=mysql))
    assert len(mysql.reports) == 3 and j.Journal(book).pending() == []


def test_no_mysql_step_without_mysql(env):
    book, _ = env
    journal, record, stores = start_save(book, None)
    assert "mysql" not in record["steps"]
    j.run(journal, record, stores)
    assert journal.pending() == []


# ---------- the report changed after the unfinished save ----------

def test_newer_save_is_never_overwritten_by_an_old_record(env):
    """Unfinished save, then the report is saved again (as an import
    does). The repair keeps the newer version in every store."""
    book, mysql = env
    journal, record, stores = start_save(book, mysql, crash_at="incidents",
                                         before=True)
    with pytest.raises(Crash):
        j.run(journal, record, stores)

    newer = bad_order(so="SO-NEWER", note="Newer incident text")
    import time
    time.sleep(1.1)
    s.write_report_to_excel(book, newer, True)
    s.save_incident_data(book, CONTROL, "SO-NEWER",
                         newer["incident_reports"])
    s.save_other_item_forms(book, CONTROL, {})

    (entry,) = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))

    assert entry["state"] == "outdated" and entry["finished"]
    now = state(book, mysql)
    assert now["workbook_so"] == "SO-NEWER"
    assert now["incident"] == [["Newer incident text"]]   # not the record's
    assert now["forms"] == []
    assert now["mysql_so"] == "SO-NEWER"                  # from the workbook
    assert now["mysql_incident"] == [["Newer incident text"]]
    lines, attention = j.describe([entry])
    assert attention and "The newer version was kept" in lines[0]
    assert j.Journal(book).pending() == []


def test_old_unwritten_record_does_not_replace_a_later_save(env):
    """The workbook write never happened, and the report was saved by
    someone else long after: the record is not applied."""
    book, mysql = env
    clock = [datetime.now() - timedelta(hours=3)]
    journal = j.Journal(book, clock=lambda: clock[0])
    data = bad_order(so="SO-STALE")
    record = j.open_save(journal, j.Stores(book, mysql=mysql), data, False,
                         False, True)
    assert record["stamp_before"] is None
    assert record["started"] < datetime.now().isoformat()
    s.write_report_to_excel(book, bad_order(so="SO-LATER"), False)

    (entry,) = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))

    assert entry["state"] == "outdated"
    assert s.read_report(book, CONTROL)["general_information"][
        "so_number"] == "SO-LATER"
    assert mysql.reports[s.control_key(CONTROL)]["general_information"][
        "so_number"] == "SO-LATER"
    assert len(s.list_saved_reports(book)) == 1


def test_report_deleted_after_the_save_is_not_brought_back(env):
    book, mysql = env
    journal, record, stores = start_save(book, mysql, crash_at="incidents",
                                         before=True)
    with pytest.raises(Crash):
        j.run(journal, record, stores)
    s.delete_reports_from_excel(book, [CONTROL])

    (entry,) = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))

    assert entry["state"] == "deleted" and entry["finished"]
    assert s.list_saved_reports(book) == [] and mysql.reports == {}
    assert s.load_incident_data(book, CONTROL) == []
    lines, attention = j.describe([entry])
    assert attention and "no longer in the Excel file" in lines[0]
    assert j.Journal(book).pending() == []


def test_new_save_of_the_same_report_replaces_its_old_record(env):
    book, mysql = env
    mysql.down = True
    j.run(*start_save(book, mysql))
    journal, record, stores = start_save(
        book, mysql, data=bad_order(so="SO-SECOND"), editing=True)
    assert [r["id"] for r in journal.pending()] == [record["id"]]
    # also when the Control # is typed in another letter case
    lower = bad_order(CONTROL.lower(), so="SO-THIRD")
    journal, record, stores = start_save(book, mysql, data=lower,
                                         editing=True)
    assert len(journal.pending()) == 1


def test_skip_leaves_the_save_in_progress_alone(env):
    book, mysql = env
    journal, record, stores = start_save(book, mysql)
    assert j.repair(journal, j.Stores(book, mysql=mysql),
                    skip={record["id"]}) == []
    assert not book.exists() and len(journal.pending()) == 1


# ---------- a new report whose number was taken meanwhile ----------

def test_repair_of_a_new_report_takes_the_next_free_number(env):
    book, mysql = env
    # another report already has the number the form was showing
    s.write_report_to_excel(book, report(
        CONTROL, "Receiving", date(2026, 11, 1), so="SO-OTHER"), False)
    journal, record, stores = start_save(book, mysql, crash_at="workbook",
                                         before=True)
    assert record["stamp_before"] is not None
    with pytest.raises(Crash):
        j.run(journal, record, stores)

    (entry,) = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))

    assert entry["finished"] and entry["control"] != CONTROL
    assert s.read_report(book, CONTROL)["general_information"][
        "so_number"] == "SO-OTHER"                 # untouched
    assert state(book, mysql, entry["control"]) == AGREED
    assert len(s.list_saved_reports(book)) == 2


# ---------- the Withdrawal workbook ----------

def test_po_linked_report_is_repaired_in_the_withdrawal_workbook(env):
    book, mysql = env
    s.write_report_to_excel(book, report(
        "FSR-TST-202611-0009", "Receiving", date(2026, 11, 1), "WH",
        [{"qty": 10, "unit": "PCS", "desc": "Valve", "po": "PO-9",
          "cargo": "C-9"}]), False)
    lookup = fsr_withdrawal.find_po(book, "PO-9")
    row = fsr_withdrawal.new_row(lookup.lines[0])
    fsr_withdrawal.set_quantity(row, 4)
    linked = report("FSR-TST-202611-0010", "Withdrawal", date(2026, 11, 6),
                    "WH", [], so="SO-WD")
    linked["item_lists"] = [{"name": "Item List 1", "rows": [row]}]
    linked["other_item_forms"] = {}
    journal = j.Journal(book)
    record = j.open_save(journal, j.Stores(book, mysql=mysql), linked,
                         False, True, True)
    with pytest.raises(Crash):
        j.run(journal, record, CrashingStores(book, mysql=mysql,
                                              crash_at="workbook"))
    home = book.with_name(fsr_paths.WITHDRAWAL_WORKBOOK_NAME)
    assert fsr_withdrawal.owns_report(book, "FSR-TST-202611-0010")

    (entry,) = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))

    assert entry["finished"] and entry["state"] == ""
    assert "FSR-TST-202611-0010" not in [
        e[0] for e in s.list_saved_reports(book)]  # not in the main workbook
    assert fsr_withdrawal.read_report(home, "FSR-TST-202611-0010")[
        "general_information"]["so_number"] == "SO-WD"
    assert book.with_name(fsr_paths.WITHDRAWN_ITEM_NAME).exists()
    assert mysql.reports[s.control_key("FSR-TST-202611-0010")][
        "general_information"]["so_number"] == "SO-WD"
    assert j.Journal(book).pending() == []


# ---------- the record file ----------

def test_record_file_lives_in_the_json_folder_of_the_workbook(env):
    book, _ = env
    assert j.journal_path(book) == book.parent.parent / "json" / \
        "Field_Survey_Reports_pending_saves.json"


@pytest.mark.parametrize("content", [
    "{not json", "[]", '{"saves": {}}', '{"saves": [1]}',
    '{"saves": [{"steps": {}}]}'])
def test_unreadable_record_file_is_reported_and_left_alone(env, content):
    book, mysql = env
    path = j.journal_path(book)
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    with pytest.raises(j.JournalError):
        j.Journal(book).pending()
    with pytest.raises(j.JournalError):
        j.Journal(book).begin(bad_order(), False, False, STEPS)
    assert path.read_text(encoding="utf-8") == content


def test_record_file_that_cannot_be_written_does_not_undo_a_save(
        env, monkeypatch):
    book, mysql = env
    journal, record, stores = start_save(book, mysql)

    def read_only(*args, **kwargs):
        raise PermissionError("read-only folder")

    monkeypatch.setattr(journal, "save", read_only)
    monkeypatch.setattr(journal, "remove", read_only)
    outcome = j.run(journal, record, stores)
    assert outcome["failed"] == {}
    assert state(book, mysql) == AGREED


def test_two_saves_seconds_apart_are_not_mistaken_for_one(env):
    """Saved, edited and saved again at once, and the second save never
    reached the workbook: the repair must write the second one."""
    book, mysql = env
    j.run(*start_save(book, mysql))
    journal, record, stores = start_save(
        book, mysql, data=bad_order(so="SO-SECOND"), editing=True,
        crash_at="workbook", before=True)
    assert record["stamp_before"] == j.Stores(book).stamp(record)
    with pytest.raises(Crash):
        j.run(journal, record, stores)
    (entry,) = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))
    assert entry["did"][0] == "workbook" and entry["state"] == ""
    assert state(book, mysql)["workbook_so"] == "SO-SECOND"


def test_report_removed_before_an_unwritten_update_is_not_brought_back(env):
    book, mysql = env
    j.run(*start_save(book, mysql))
    journal, record, stores = start_save(
        book, mysql, data=bad_order(so="SO-SECOND"), editing=True,
        crash_at="workbook", before=True)
    with pytest.raises(Crash):
        j.run(journal, record, stores)
    s.delete_reports_from_excel(book, [CONTROL])
    (entry,) = j.repair(j.Journal(book), j.Stores(book, mysql=mysql))
    assert entry["state"] == "deleted" and s.list_saved_reports(book) == []
