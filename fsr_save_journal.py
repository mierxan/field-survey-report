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

Every step can be repeated safely, so running repair() twice - or having it
interrupted and run again - gives the same result as running it once.
MySQL not being reachable is normal on an offline PC: the save is complete
on this PC and only the "mysql" step waits.
"""
import copy
import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

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
# A workbook time this close after the start of a save is that save.
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
    return {
        "id": uuid.uuid4().hex,
        "control": data["control_no"],
        "started": (now or datetime.now()).isoformat(timespec="seconds"),
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

    def __init__(self, excel_path, mysql=None, required_root=None):
        self.excel_path = Path(excel_path)
        self.mysql_module = mysql
        self.required_root = required_root

    def home(self, record):
        """The workbook that holds this report."""
        if record["linked"]:
            return fsr_paths.withdrawal_workbook_path(
                self.excel_path, self.required_root)
        return self.excel_path

    # -- writes --
    def workbook(self, record):
        data = record["data"]
        if record["linked"]:
            return fsr_withdrawal.write_withdrawal_report(
                self.home(record), data, record["editing"], self.excel_path)
        return storage.write_report_to_excel(
            self.excel_path, data, record["editing"])

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
        return self.mysql_module.save_report(data)

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
                        return value.isoformat(timespec="seconds")
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
    """Put a save on record before its first write. Returns the record."""
    before = stores.stamp({"linked": bool(linked),
                           "control": data["control_no"]})
    return journal.begin(data, editing, linked,
                         steps_for(data, linked, mysql), stamp_before=before)


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
        record["stamp"] = stores.stamp(record)
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
        except Exception as error:      # noted, the other steps go on
            log.exception("Save step '%s' of %s failed", step,
                          record["control"])
            outcome["failed"][step] = error
            record["errors"][step] = str(error)
            _note(journal, record)
            continue
        steps[step] = DONE
        record["errors"].pop(step, None)
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

    if steps.get("workbook") == PENDING:
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
        if "mysql" in entry["failed"]:
            mysql = False
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
        if "mysql" in entry["failed"]:
            lines.append(f"{control}: still waiting for MySQL.")
    return lines, attention
