"""A save that stops halfway can be finished later.

Saving one report writes several stores, one after another:

  workbook     the report in the Excel workbook (main or Withdrawal)
  incidents    the incident text of a Bad Order report   (JSON)
  item_forms   the lines of the other Item List forms    (JSON)
  item_lists   PO_Master.xlsx and Withdrawn_Item.xlsx    (rebuilt)
  mysql        the copy in the MySQL database            (Owner edition)

Before the first write a RECORD of the save is put into

  <JSON folder of the workbook>/<workbook name>_pending_saves.json

with the whole report and the state of every step. Each finished step is
ticked off; the record is removed when all are done. A record that is still
there - the PC lost power, a file was open in Excel, MySQL was not reachable
- is finished by repair() at the next start or the next save.

Which store is right when they disagree
  * The WORKBOOK is the source of truth for everything it holds.
  * Incident text and other-form lines exist only in their JSON files, so
    for those the record (the report as the user saved it) is used - but
    only while the workbook still holds that same save. If the report was
    saved again since (an import, say), the record is out of date: its
    JSON steps are dropped and nothing newer is overwritten.
  * PO_Master / Withdrawn_Item and MySQL are always derived from the
    workbook, never the other way round.

How a save is recognised in the workbook
  Every save chooses its Last Saved time BEFORE it writes ("stamp_planned",
  to the millisecond - as exact as Excel keeps a time) and the workbook
  write uses exactly that time. So the time is the save's own mark:
    the workbook holds that time   -> it holds this save
    it holds an earlier time       -> the older version: the save was
                                      never written, repair writes it
    it holds a later time          -> the report was saved again since
  No guessing by "close in time" is involved. (Records written before this
  rule have no "stamp_planned"; for them the earlier rule is kept.)

Every step can be repeated safely, so running repair() twice - or having it
interrupted and run again - gives the same result as running it once.
MySQL not being reachable is normal on an offline PC: the save is complete
on this PC and only the "mysql" step waits.

MySQL conflicts
  The MySQL step goes through fsr_mysql_guard: it never overwrites a report
  in MySQL that this copy of the program does not own. When MySQL holds a
  different report under the number, the step stays open with the conflict
  noted in the record ("conflict"). Such records are the list of waiting
  conflicts; resolve_keep / resolve_replace / resolve_renumber carry out
  the user's decision. Nothing local is ever held up by a conflict.
"""
import copy
import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import fsr_mysql_guard
import fsr_paths
import fsr_storage as storage
import fsr_withdrawal

log = logging.getLogger("fsr")

VERSION = 1
STEPS = ("workbook", "incidents", "item_forms", "item_lists", "mysql")
LOCAL_STEPS = STEPS[:-1]
PENDING, DONE = "pending", "done"
OUTDATED = "outdated"        # dropped: the report was saved again since
SETTLED = (DONE, OUTDATED)
# Excel keeps a time to the millisecond: two times this close are equal.
SAME_TIME = timedelta(milliseconds=1.5)
# Only for records without "stamp_planned" (written before that rule):
# a workbook time this close after the start of a save is that save.
OWN_SAVE_WINDOW = timedelta(seconds=120)
CLOCK_SLACK = timedelta(seconds=2)

STEP_WORDS = {
    "workbook": "the Excel file",
    "incidents": "the incident report file",
    "item_forms": "the lines of the other Item List forms",
    "item_lists": "PO_Master and Withdrawn_Item",
    "mysql": "MySQL",
}


class JournalError(ValueError):
    """The record file cannot be read; it was left as it is."""


def journal_path(excel_path):
    excel_path = Path(excel_path)
    return (fsr_paths.json_dir_for_workbook(excel_path)
            / f"{excel_path.stem}_pending_saves.json")


def new_record(data, editing, linked, steps, stamp_before=None, now=None):
    """The record of one save (see the module text)."""
    now = now or datetime.now()
    planned = now.replace(microsecond=now.microsecond // 1000 * 1000)
    return {
        "id": uuid.uuid4().hex,
        "control": data["control_no"],
        "started": now.isoformat(timespec="seconds"),
        # the Last Saved time this save writes: its mark in the workbook
        "stamp_planned": planned.isoformat(timespec="milliseconds"),
        "editing": bool(editing),
        "linked": bool(linked),
        "steps": {step: PENDING for step in steps},
        "stamp_before": stamp_before,
        "stamp": None,
        "errors": {},
        "data": copy.deepcopy(data),
    }


def steps_for(data, linked, mysql):
    """The steps one save has, in order."""
    steps = ["workbook", "incidents", "item_forms"]
    activity = (data.get("inspection_schedule") or {}).get("activity")
    if linked or storage.same_key(activity, "Receiving"):
        steps.append("item_lists")
    if mysql:
        steps.append("mysql")
    return steps


def words(steps):
    return ", ".join(STEP_WORDS[step] for step in steps)


# ---------------------------------------------------------------------
# the record file
# ---------------------------------------------------------------------

class Journal:
    def __init__(self, excel_path, clock=None):
        self.excel_path = Path(excel_path)
        self.path = journal_path(excel_path)
        self._now = clock or datetime.now

    def load(self):
        """[records], oldest first. [] when there is no file."""
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                document = json.load(file)
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as error:
            raise JournalError(
                f"The record of unfinished saves could not be read:\n"
                f"{self.path}\n{error}") from error
        saves = document.get("saves") if isinstance(document, dict) else None
        if not isinstance(saves, list) or any(
                not isinstance(r, dict) or not isinstance(r.get("steps"), dict)
                or not isinstance(r.get("data"), dict) for r in saves):
            raise JournalError(
                "The record of unfinished saves has an unknown format:\n"
                f"{self.path}")
        return saves

    def _store(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        storage.write_json_atomic(
            self.path, {"version": VERSION, "saves": records})

    def begin(self, data, editing, linked, steps, stamp_before=None):
        """Write the record of a save that is about to start. An older
        record of the same report is replaced: this save supersedes it.
        `stamp_before` is the report's Last Saved time in the workbook
        right now (None for a report that is not there yet)."""
        record = new_record(data, editing, linked, steps, stamp_before,
                            self._now())
        key = storage.control_key(record["control"])
        records = [r for r in self.load()
                   if storage.control_key(r.get("control")) != key]
        records.append(record)
        self._store(records)
        return record

    def save(self, record):
        """Write the current state of `record` (it must be on file)."""
        records = self.load()
        for index, existing in enumerate(records):
            if existing.get("id") == record["id"]:
                records[index] = record
                self._store(records)
                return
        records.append(record)
        self._store(records)

    def remove(self, record):
        records = self.load()
        left = [r for r in records if r.get("id") != record["id"]]
        if len(left) != len(records):
            self._store(left)

    def pending(self):
        return self.load()


# ---------------------------------------------------------------------
# the stores
# ---------------------------------------------------------------------

class Stores:
    """The real writes of one data folder. `mysql` is the db_mysql module
    (or None). Tests replace single methods to make a write fail."""

    def __init__(self, excel_path, mysql=None, required_root=None,
                 guard=None):
        self.excel_path = Path(excel_path)
        self.mysql_module = mysql
        self.required_root = required_root
        # fsr_mysql_guard.Guard: checks before every MySQL write. Without
        # one (older tests with a simple stand-in) the write is direct.
        self.guard = guard

    def home(self, record):
        """The workbook that holds this report."""
        if record["linked"]:
            return fsr_paths.withdrawal_workbook_path(
                self.excel_path, self.required_root)
        return self.excel_path

    # -- writes --
    def workbook(self, record):
        data = record["data"]
        extra = {}
        planned = _time(record.get("stamp_planned"))
        if planned is not None:
            extra["saved_at"] = planned
        # The MySQL ledger must belong to the workbook as THIS write leaves
        # it, before the MySQL step of the same save looks at the ledger.
        if self.guard is not None:
            self.guard.before_local_write()
        try:
            if record["linked"]:
                return fsr_withdrawal.write_withdrawal_report(
                    self.home(record), data, record["editing"],
                    self.excel_path, **extra)
            return storage.write_report_to_excel(
                self.excel_path, data, record["editing"], **extra)
        finally:
            if self.guard is not None:
                self.guard.after_local_write()

    def incidents(self, record):
        data = record["data"]
        if data.get("cargo_condition") == storage.CONDITION_BAD:
            storage.save_incident_data(
                self.excel_path, record["control"],
                data["general_information"]["so_number"],
                data.get("incident_reports") or [])
        else:
            storage.delete_incident_data(self.excel_path, record["control"])

    def item_forms(self, record):
        storage.save_other_item_forms(
            self.excel_path, record["control"],
            record["data"].get("other_item_forms") or {})

    def item_lists(self, record):
        fsr_withdrawal.sync_item_lists(self.excel_path)

    def mysql(self, record, data):
        if self.guard is None:
            return self.mysql_module.save_report(data)
        _, notes = self.guard.save(data, record.get("decision"))
        return notes

    # -- reads --
    def stamp(self, record):
        """The Last Saved time of this report in its workbook (ISO text),
        or None when the workbook or the report is not there."""
        book = self.home(record)
        sheet = (fsr_withdrawal.HEADER_SHEET if record["linked"]
                 else "Reports")
        if not Path(book).exists():
            return None
        wb = storage.load_workbook(book, read_only=True, data_only=True)
        try:
            if sheet not in wb.sheetnames:
                return None
            rows = wb[sheet].iter_rows(values_only=True)
            header = next(rows, None) or ()
            if "Last Saved" not in header:
                return None
            column = header.index("Last Saved")
            for row in rows:
                if row and storage.same_key(row[0], record["control"]):
                    value = row[column] if len(row) > column else None
                    if isinstance(value, datetime):
                        return value.isoformat(timespec="milliseconds")
                    return str(value) if value is not None else ""
            return None
        finally:
            wb.close()

    def read_back(self, record):
        """The report as the workbook (and its JSON files) hold it now."""
        if record["linked"]:
            return fsr_withdrawal.read_report(
                self.home(record), record["control"])
        return storage.read_report(self.excel_path, record["control"])


# ---------------------------------------------------------------------
# doing the steps
# ---------------------------------------------------------------------

def open_save(journal, stores, data, editing, linked, mysql):
    """Put a save on record before its first write. Returns the record.
    Nothing is read from the workbook for this: the save's own time
    ("stamp_planned") is all the repair needs."""
    return journal.begin(data, editing, linked,
                         steps_for(data, linked, mysql))


def open_local_steps(journal, control_no):
    """The steps on this PC (not the workbook itself, not MySQL) that an
    earlier, unfinished save of this report still owes. A new save of the
    report replaces that record and does these steps itself."""
    key = storage.control_key(control_no)
    try:
        records = journal.pending()
    except JournalError:
        return []
    return [step for step in LOCAL_STEPS[1:]
            if any(storage.control_key(r.get("control")) == key
                   and r["steps"].get(step) == PENDING for r in records)]


def _settled(record, steps=STEPS):
    return all(record["steps"].get(step, DONE) in SETTLED for step in steps)


def local_complete(record):
    """Everything on this PC is written (MySQL may still wait)."""
    return _settled(record, LOCAL_STEPS)


def run(journal, record, stores, mysql=True):
    """Do every pending step of `record`, in order, ticking each off.

    The workbook comes first: its failure is raised to the caller and
    nothing else is tried. Any other step that fails is noted and the rest
    go on. Returns {"result": what the workbook write returned (None when it
    was already done), "failed": {step: exception}}; the record is removed
    from the journal when no step is left."""
    outcome = {"result": None, "failed": {}}
    steps = record["steps"]

    if steps.get("workbook") == PENDING:
        outcome["result"] = result = stores.workbook(record)
        record["control"] = record["data"]["control_no"] = result["control"]
        record["editing"] = True        # from now on it is an update
        steps["workbook"] = DONE
        record["stamp"] = (record.get("stamp_planned")
                           or stores.stamp(record))
        _note(journal, record)

    data = record["data"]
    for step in ("incidents", "item_forms", "item_lists", "mysql"):
        if steps.get(step) != PENDING or (step == "mysql" and (
                not mysql or record.get("_mysql_wait"))):
            continue
        try:
            if step == "mysql":
                outcome["mysql_notes"] = stores.mysql(
                    record, record.get("_mysql_data") or data)
            else:
                getattr(stores, step)(record)
        except fsr_mysql_guard.MySQLConflict as error:
            # Not an error: MySQL holds another report under this number.
            # Nothing was written there; the user decides.
            log.info("MySQL conflict for %s: %s", record["control"], error)
            outcome["failed"][step] = error
            record["conflict"] = error.conflict
            record["errors"][step] = str(error)
            _note(journal, record)
            continue
        except Exception as error:      # noted, the other steps go on
            log.exception("Save step '%s' of %s failed", step,
                          record["control"])
            outcome["failed"][step] = error
            record["errors"][step] = str(error)
            _note(journal, record)
            continue
        steps[step] = DONE
        record["errors"].pop(step, None)
        if step == "mysql":
            record.pop("conflict", None)
            record.pop("decision", None)
        _note(journal, record)

    if _settled(record):
        _forget(journal, record)
    return outcome


def _note(journal, record):
    """Tick a step off on disk. A record file that cannot be written does
    not undo the write that just succeeded."""
    if journal is None:
        return
    try:
        journal.save({k: v for k, v in record.items()
                      if not k.startswith("_")})
    except (OSError, ValueError, TypeError):
        log.exception("The save record could not be updated")


def _forget(journal, record):
    if journal is None:
        return
    try:
        journal.remove(record)
    except (OSError, ValueError, TypeError):
        log.exception("The save record could not be cleared")


def discard(journal, record):
    """The workbook write failed and the user was told: nothing was saved,
    so there is nothing to finish later."""
    _forget(journal, record)


def _time(text):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _check_against_workbook(journal, record, stores):
    """Bring the record in line with what the workbook holds now. Returns
    a word for the report: "" (go on), "outdated" or "deleted"."""
    steps = record["steps"]
    now_stamp = stores.stamp(record)
    planned = _time(record.get("stamp_planned"))

    if planned is not None:
        outdated = _exact_check(journal, record, now_stamp, planned)
        if outdated in ("", "deleted"):
            return outdated
    elif steps.get("workbook") == PENDING:
        if now_stamp == record.get("stamp_before"):
            return ""                   # never written: repair writes it
        if now_stamp is None:           # was there before the save, gone now
            for step in steps:
                steps[step] = OUTDATED
            _note(journal, record)
            return "deleted"
        # The workbook holds another version than before this save: either
        # this save (it stopped right after the write) or a later one.
        started, saved = _time(record.get("started")), _time(now_stamp)
        if (saved is not None and started is not None
                and started - CLOCK_SLACK <= saved
                <= started + OWN_SAVE_WINDOW):
            steps["workbook"] = DONE    # written just before the stop
            record["editing"] = True
            record["stamp"] = now_stamp
            _note(journal, record)
            return ""
        outdated = True
    elif now_stamp is None:
        # The report was removed from the workbook after it was saved.
        for step in steps:
            steps[step] = OUTDATED
        _note(journal, record)
        return "deleted"
    else:
        outdated = now_stamp != record.get("stamp")

    if not outdated:
        return ""
    # Saved again since (for example by an import): the newer save wrote its
    # own JSON files. Only the derived stores are still brought up to date,
    # from the workbook.
    for step in ("workbook", "incidents", "item_forms"):
        if steps.get(step) == PENDING:
            steps[step] = OUTDATED
    if steps.get("mysql") == PENDING:
        try:
            record["_mysql_data"] = stores.read_back(record)
        except Exception:
            # Never send the out-of-date record to MySQL instead.
            log.exception("Could not read %s back", record["control"])
            record["_mysql_wait"] = True
    _note(journal, record)
    return "outdated"


def _exact_check(journal, record, now_stamp, planned):
    """The rule of the module text. Returns "" (go on), "deleted", or True
    (the workbook holds a newer save than this record)."""
    steps = record["steps"]
    saved = _time(now_stamp)
    pending = steps.get("workbook") == PENDING

    if now_stamp is None and (not pending or record["editing"]):
        # It was in the workbook and is not any more: not brought back.
        for step in steps:
            steps[step] = OUTDATED
        _note(journal, record)
        return "deleted"
    if saved is not None and abs(saved - planned) <= SAME_TIME:
        if pending:                     # written just before the stop
            steps["workbook"] = DONE
            record["editing"] = True
            record["stamp"] = record["stamp_planned"]
            _note(journal, record)
        return ""
    if pending and (not record["editing"] or saved is None
                    or saved < planned):
        # Not there, or the older version: the save was never written.
        # (A NEW report is always written: if its number now belongs to
        # another report, the write gives it the next free number.)
        return ""
    return True


def repair(journal, stores, mysql=True, skip=()):
    """Finish every unfinished save on record.

    mysql=False leaves the MySQL steps waiting (the server is not
    reachable). After the first MySQL failure the rest of the MySQL steps
    are left for next time, so an absent server costs one wait, not many.
    `skip` holds record ids to leave alone (the save going on right now).

    Returns one dictionary per record that was touched:
      control, started, finished (nothing left), local (this PC complete),
      did [steps finished now], waiting [steps still open],
      failed {step: text}, state ("", "outdated" or "deleted")."""
    report = []
    for record in journal.pending():
        if record.get("id") in skip:
            continue
        if record.get("local_done"):
            # A conflict found by Import / Sync: only MySQL is open, and
            # only a decision (or MySQL becoming equal) closes it.
            if mysql:
                outcome = _send_only(journal, record, stores)
                if "mysql" not in outcome["failed"]:
                    report.append({
                        "control": record["control"], "started":
                        record.get("started"), "failed": {}, "state": "",
                        "did": ["mysql"], "waiting": [], "finished": True,
                        "local": True, "conflict": False})
            continue
        before = dict(record["steps"])
        entry = {"control": record.get("control"),
                 "started": record.get("started"), "failed": {}, "state": ""}
        try:
            entry["state"] = _check_against_workbook(journal, record, stores)
            outcome = run(journal, record, stores, mysql=mysql)
            entry["failed"] = {s: str(e) for s, e in
                               outcome["failed"].items()}
        except Exception as error:      # the workbook step itself
            log.exception("Unfinished save of %s could not be completed",
                          record.get("control"))
            entry["failed"] = {"workbook": str(error)}
            record["errors"]["workbook"] = str(error)
            _note(journal, record)
        entry["conflict"] = bool(record.get("conflict")) and \
            record["steps"].get("mysql") == PENDING
        if "mysql" in entry["failed"] and not entry["conflict"]:
            mysql = False               # the server is away: stop asking it
        entry["control"] = record.get("control")
        entry["did"] = [s for s in STEPS if before.get(s) == PENDING
                        and record["steps"].get(s) == DONE]
        entry["waiting"] = [s for s in STEPS
                            if record["steps"].get(s) == PENDING]
        entry["finished"] = not entry["waiting"]
        entry["local"] = local_complete(record)
        if entry["did"] or entry["failed"] or entry["state"] \
                or entry["finished"]:
            report.append(entry)
    return report


# ---------------------------------------------------------------------
# MySQL conflicts: the waiting list and the three decisions
# ---------------------------------------------------------------------

def conflicts(journal):
    """The records that wait for a decision, oldest first."""
    return [r for r in journal.pending() if r.get("conflict")
            and r["steps"].get("mysql") == PENDING]


def add_conflict(journal, report, conflict, linked=False):
    """Put a conflict found outside a save (Import, Sync to MySQL) on the
    list. A record this report already has is kept and only marked."""
    key = storage.control_key(report["control_no"])
    for record in journal.pending():
        if storage.control_key(record.get("control")) == key:
            record["conflict"] = conflict
            record["steps"]["mysql"] = PENDING
            journal.save(record)
            return record
    record = new_record(report, True, linked, ["mysql"])
    record["conflict"] = conflict
    record["stamp"] = None
    record["stamp_planned"] = None      # nothing local belongs to it
    record["local_done"] = True
    journal.save(record)
    return record


def _find(journal, record_id):
    for record in journal.pending():
        if record.get("id") == record_id:
            return record
    raise KeyError(record_id)


def resolve_keep(journal, record_id):
    """Keep MySQL's report: nothing is written, the conflict is closed. The
    report stays as it is in this copy's workbook."""
    record = _find(journal, record_id)
    record["steps"]["mysql"] = OUTDATED
    record.pop("conflict", None)
    record.pop("decision", None)
    if _settled(record):
        journal.remove(record)
    else:
        journal.save(record)
    return record


def resolve_replace(journal, stores, record_id):
    """The deliberate choice: replace MySQL's report with this copy's. The
    guard keeps the replaced version first. Returns run()'s outcome."""
    record = _find(journal, record_id)
    record["decision"] = fsr_mysql_guard.REPLACE
    return _send_only(journal, record, stores)


def resolve_renumber(journal, stores, record_id, new_control, renumber):
    """Give this copy's report another number - in the workbook, its JSON
    files and the PO lists (`renumber(old, new)` does that) - and send it to
    MySQL under the new number. MySQL's report is untouched."""
    record = _find(journal, record_id)
    old = record["control"]
    renumber(old, new_control)
    record["control"] = new_control
    try:
        record["data"] = stores.read_back(record)
    except Exception:
        log.exception("Could not read %s back after renumbering",
                      new_control)
        record["data"]["control_no"] = new_control
    record["data"].setdefault("other_item_forms", {})
    record["data"].pop("incident_error", None)
    record.pop("conflict", None)
    record.pop("decision", None)
    record["renumbered_from"] = old
    journal.save(record)
    return _send_only(journal, record, stores)


def _send_only(journal, record, stores):
    """Do the MySQL step of a record whose local part is complete."""
    if record.get("local_done"):
        outcome = {"result": None, "failed": {}}
        try:
            outcome["mysql_notes"] = stores.mysql(record, record["data"])
        except fsr_mysql_guard.MySQLConflict as error:
            record["conflict"] = error.conflict
            record.pop("decision", None)
            journal.save(record)
            outcome["failed"]["mysql"] = error
            return outcome
        except Exception as error:
            record.pop("decision", None)
            journal.save(record)
            outcome["failed"]["mysql"] = error
            return outcome
        journal.remove(record)
        return outcome
    outcome = run(journal, record, stores)
    if record.get("decision") and "mysql" in outcome["failed"]:
        record.pop("decision", None)    # never keep a standing "replace"
        _note(journal, record)
    return outcome


def send_to_mysql(journal, guard, reports, replace=(), linked=()):
    """Import and Sync to MySQL: write every report the guard allows, put
    the conflicts on the waiting list. `replace`: Control #s the user
    ticked. `linked`: Control #s that live in the Withdrawal workbook.
    Returns guard.save_many()'s result."""
    result = guard.save_many(reports, replace)
    linked_keys = {storage.control_key(c) for c in linked}
    for report, conflict in result["conflicts"]:
        add_conflict(journal, report, conflict,
                     storage.control_key(report["control_no"]) in linked_keys)
    done = {storage.control_key(c)
            for c in result["written"] + result["identical"]}
    for record in conflicts(journal):       # settled by this very run
        if storage.control_key(record["control"]) in done and \
                record.get("local_done"):
            journal.remove(record)
    return result


def describe(report):
    """(lines for the user, anything needs attention?). MySQL catching up
    or still waiting is normal and is not 'attention'."""
    lines, attention = [], False
    for entry in report:
        control = entry["control"]
        when = (_time(entry.get("started")) or datetime.now()).strftime(
            "%d-%b-%Y %H:%M")
        local_done = [s for s in entry["did"] if s != "mysql"]
        local_failed = {s: t for s, t in entry["failed"].items()
                        if s != "mysql"}
        if entry["state"] == "deleted":
            lines.append(
                f"{control}: its save of {when} did not finish, and the "
                "report is no longer in the Excel file. Nothing was changed.")
            attention = True
        elif entry["state"] == "outdated":
            lines.append(
                f"{control}: its save of {when} did not finish, and the "
                "report has been saved again since then. The newer version "
                "was kept; the unfinished one was not applied.")
            attention = True
        if local_done:
            lines.append(
                f"{control}: the save of {when} had not finished. It was "
                f"completed now: {words(local_done)}.")
            attention = True
        if local_failed:
            for step, text in local_failed.items():
                lines.append(
                    f"{control}: {STEP_WORDS[step]} could still NOT be "
                    f"written ({text}). It will be tried again at the next "
                    "save or the next start.")
            attention = True
        if "mysql" in entry["did"]:
            lines.append(f"{control}: now also saved to MySQL.")
        if entry.get("conflict"):
            lines.append(f"{control}: NOT sent to MySQL - it holds a "
                         "different report under this number. Waiting for "
                         "your decision (MySQL Conflicts).")
        elif "mysql" in entry["failed"]:
            lines.append(f"{control}: still waiting for MySQL.")
    return lines, attention
