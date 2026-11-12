"""A copy of the program never overwrites a MySQL report it does not own.

Several copies of the program (the installed one, a test copy, another PC)
may use one MySQL database while each has its own workbook. MySQL knows a
report only by its Control #, so without a check one copy would silently
replace another copy's report that happens to carry the same number.

The rule, applied to every write (Save, the catch-up after MySQL was away,
Import Master Data, Sync to MySQL):

  MySQL has no report with this number      -> write it
  MySQL's report equals mine in value       -> nothing to write; mine now
  MySQL's report is the one THIS copy wrote
     last, unchanged since                  -> update it
  anything else                             -> CONFLICT: write nothing,
                                               show both, ask

"This copy wrote it" is remembered in a small file beside the workbook's
JSON data, <workbook name>_mysql_ledger.json: for each Control # a
fingerprint of the report as MySQL held it right after this copy's write.
A missing or unreadable ledger, or one that no longer belongs to the
workbook as it is now, counts as empty - every report is then "not owned"
and is asked about (identical ones are adopted silently). It never falls
back to overwriting.

"Belongs to the workbook as it is now": the ledger notes the size and the
exact change time of the workbooks as the PROGRAM last left them
("books"). If a workbook differs from that note, something else changed it
(a restored backup, an edit in Excel) and the ledger is not relied on.
The program renews the note right after each of its own workbook writes -
before the MySQL step of that same save, which needs the ledger.

The check and the write happen together: under a MySQL lock on the Control #
and inside one transaction, so two copies saving at the same moment cannot
both pass the check.

Before a MySQL report is replaced on the user's decision, the replaced
version is kept in  <JSON folder>/MySQL Replaced/  with a line in
replaced_log.csv (who, when, which copy, which Control #). put_back()
writes such a file into MySQL again.
"""
import csv
import hashlib
import json
import logging
import socket
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import fsr_paths
import fsr_storage as storage

log = logging.getLogger("fsr")

VERSION = 1
REPLACED_FOLDER = "MySQL Replaced"
NOT_OWNED = "not_owned"                 # this copy never wrote that report
CHANGED_ELSEWHERE = "changed_elsewhere"  # it did, but MySQL's changed since
KEEP, REPLACE, RENUMBER = "keep", "replace", "renumber"

# Not part of a report's content (or not kept by MySQL at all).
IGNORED = {"incident_error", "last_saved", "entry_source", "po_source_file",
           "other_item_forms", "title"}
# Numbers are compared as numbers: "0.00" = "0", "1,250" = "1250.0".
NUMERIC_ROW_FIELDS = set(getattr(storage, "NUMERIC_ITEM_HEADERS", ())) | set(
    getattr(storage, "MONEY_ITEM_HEADERS", ())) | {"quantity"}


class MySQLConflict(Exception):
    """MySQL holds another report under this number; nothing was written."""

    def __init__(self, conflict):
        self.conflict = conflict
        super().__init__(conflict["text"])


class MySQLBusy(Exception):
    """Another copy is saving this very report right now; try later."""


# ---------------------------------------------------------------------
# equal in value
# ---------------------------------------------------------------------

def _number(text):
    try:
        return Decimal(str(text).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def canonical(value, field=None):
    """A report with everything that is only a matter of display removed:
      * outer spaces; None, "" and a missing field are the same
      * numbers in quantity and price fields: 0.00 = 0, 1,250 = 1250.0
      * an empty list / an empty incident card = none
      * Item List form "Default" = not stated
      * fields MySQL does not keep (other Item List forms, file notes)
    Letter case, leading zeros in document numbers and the order of lines
    are NOT ignored - those are real differences."""
    if isinstance(value, dict):
        out = {}
        for key in sorted(value):
            if key in IGNORED:
                continue
            if key == "item_form" and storage.item_form_name(
                    value[key]) == storage.item_form_name(None):
                continue
            item = canonical(value[key], key)
            if item not in ("", [], {}, False, None):
                out[key] = item
        return out
    if isinstance(value, (list, tuple)):
        items = [canonical(item, field) for item in value]
        return [item for item in items if item not in ("", {}, [], None)]
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if field in NUMERIC_ROW_FIELDS and text:
        number = _number(text)
        if number is not None:
            return format(number.normalize(), "f")
    return text


def same_value(mine, theirs):
    return canonical(mine) == canonical(theirs)


def fingerprint(report):
    payload = json.dumps(canonical(report), sort_keys=True,
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def differences(mine, theirs, limit=40):
    """Plain lines: where two reports differ in value."""
    lines = []

    def walk(a, b, path):
        if len(lines) >= limit:
            return
        if isinstance(a, dict) or isinstance(b, dict):
            a, b = a or {}, b or {}
            if isinstance(a, dict) and isinstance(b, dict):
                for key in sorted(set(a) | set(b)):
                    walk(a.get(key, ""), b.get(key, ""),
                         f"{path} > {key}" if path else key)
                return
        if isinstance(a, list) or isinstance(b, list):
            a, b = a or [], b or []
            if isinstance(a, list) and isinstance(b, list):
                if len(a) != len(b):
                    lines.append(f"{path}: {len(a)} here, {len(b)} in MySQL")
                for index, (x, y) in enumerate(zip(a, b), start=1):
                    walk(x, y, f"{path} {index}")
                return
        if a != b:
            lines.append(f"{path}: here '{a}' | MySQL '{b}'")

    walk(canonical(mine), canonical(theirs), "")
    return lines


def summary(report):
    general = report.get("general_information") or {}
    rows = sum(len(section.get("rows") or [])
               for section in report.get("item_lists") or [])
    return {"so_number": str(general.get("so_number") or ""),
            "inspection_date": str(general.get("inspection_date") or ""),
            "consignee": str(general.get("consignee") or ""),
            "supplier": str(general.get("supplier") or ""),
            "condition": str(report.get("cargo_condition") or ""),
            "item_lines": rows}


# ---------------------------------------------------------------------
# the guard of one workbook
# ---------------------------------------------------------------------

def ledger_path(excel_path):
    excel_path = Path(excel_path)
    return (fsr_paths.json_dir_for_workbook(excel_path)
            / f"{excel_path.stem}_mysql_ledger.json")


def supports(db):
    """A stand-in used by older tests has only save_report()."""
    return all(hasattr(db, name) for name in (
        "connect", "lock_report", "unlock_report", "report_exists",
        "load_report", "write_report"))


class Guard:
    def __init__(self, db, excel_path, user="", clock=None):
        self.db = db
        self.excel_path = Path(excel_path)
        self.user = user
        self._now = clock or datetime.now
        self.path = ledger_path(excel_path)
        self.replaced_dir = (fsr_paths.json_dir_for_workbook(excel_path)
                             / REPLACED_FOLDER)
        # Set by before_local_write(): only a write announced that way may
        # mark the ledger as current again (after_local_write).
        self._armed = False

    # ---- the ledger ----
    def _workbooks(self):
        book = self.excel_path
        return [book, book.with_name(fsr_paths.WITHDRAWAL_WORKBOOK_NAME)]

    def _read(self):
        """(ledger dictionary, trusted?). Anything wrong -> an empty one."""
        empty = {"version": VERSION, "copy_id": uuid.uuid4().hex,
                 "reports": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                ledger = json.load(file)
        except FileNotFoundError:
            return empty, False
        except (OSError, ValueError):
            log.warning("The MySQL ledger %s cannot be read: every report "
                        "counts as not owned.", self.path)
            return empty, False
        if (not isinstance(ledger, dict)
                or not isinstance(ledger.get("reports"), dict)
                or any(not isinstance(e, dict) or not isinstance(
                    e.get("fingerprint"), str)
                    for e in ledger["reports"].values())):
            log.warning("The MySQL ledger %s has an unknown format: every "
                        "report counts as not owned.", self.path)
            return empty, False
        ledger.setdefault("copy_id", empty["copy_id"])
        return ledger, True

    def _books(self):
        """Size and exact change time of each workbook, as it is now."""
        found = {}
        for book in self._workbooks():
            try:
                info = book.stat()
            except OSError:
                continue
            found[book.name] = [info.st_mtime_ns, info.st_size]
        return found

    def is_stale(self, ledger=None):
        """A workbook is not as the program last left it (a restored
        backup, an edit outside the program), or the ledger is lost."""
        if ledger is None:
            ledger, trusted = self._read()
            if not trusted:
                return True
        return ledger.get("books") != self._books()

    def _empty(self, ledger):
        """Stop relying on what the ledger says (in memory)."""
        if ledger["reports"]:
            ledger["emptied"] = self._now().isoformat(timespec="seconds")
        ledger["reports"] = {}
        ledger["books"] = self._books()

    def ledger(self):
        """The ledger as it may be relied on right now."""
        ledger, trusted = self._read()
        if not trusted:
            ledger["books"] = self._books()
        elif self.is_stale(ledger):
            if ledger["reports"]:
                log.warning(
                    "The Excel file is not as this program last left it: "
                    "the MySQL ledger is not relied on, every report "
                    "counts as not owned.")
            self._empty(ledger)
        return ledger

    def _store(self, ledger):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        storage.write_json_atomic(self.path, ledger)

    def before_local_write(self):
        """Call before the program itself writes the workbook. If the ledger
        is not to be trusted at this moment it is emptied for good - else
        the program's own write would make it look current again."""
        ledger, trusted = self._read()
        if trusted and self.is_stale(ledger) and ledger["reports"]:
            log.warning(
                "The Excel file is not as this program last left it: the "
                "MySQL ledger is emptied, every report counts as not owned.")
            self._empty(ledger)
            try:
                self._store(ledger)
            except OSError:
                log.exception("The MySQL ledger could not be written")
                return          # not armed: the old ledger stays distrusted
        self._armed = True

    def after_local_write(self):
        """Call right after the program wrote a workbook (and before the
        MySQL step of that save): the ledger belongs to the workbook as it
        is now. Does nothing unless before_local_write() came first on
        this guard: otherwise an out-of-date ledger could be marked current
        without having been emptied."""
        if not self._armed:
            log.warning("after_local_write() without before_local_write(): "
                        "the MySQL ledger was left as it is.")
            return
        self._armed = False
        ledger, _ = self._read()        # not trusted -> a fresh, empty one
        books = self._books()
        if ledger.get("books") == books and self.path.exists():
            return
        ledger["books"] = books
        try:
            self._store(ledger)
        except OSError:
            log.exception("The MySQL ledger could not be written")

    def owns(self, control_no):
        return storage.control_key(control_no) in self.ledger()["reports"]

    def _remember(self, ledger, control_no, report_in_mysql):
        ledger["reports"][storage.control_key(control_no)] = {
            "control": control_no,
            "fingerprint": fingerprint(report_in_mysql),
            "written": self._now().isoformat(timespec="seconds"),
        }
        self._store(ledger)

    def forget(self, control_no):
        ledger, trusted = self._read()
        if trusted and ledger["reports"].pop(
                storage.control_key(control_no), None) is not None:
            self._store(ledger)

    # ---- one report ----
    def look(self, data, connection=None):
        """What would happen to this report - without writing anything:
        "new", "identical", "update" (mine, unchanged in MySQL), or a
        conflict dictionary."""
        own = connection is None
        conn = connection or self.db.connect()
        try:
            return self._decide(conn, data, self.ledger())[0]
        finally:
            if own:
                try:
                    conn.rollback()
                finally:
                    conn.close()

    def _decide(self, conn, data, ledger, lock_rows=False):
        control = data["control_no"]
        exists = (self.db.report_exists(conn, control) if lock_rows
                  else control_in(self.db, conn, control))
        if not exists:
            return "new", None
        theirs = self.db.load_report(control, conn)
        if same_value(data, theirs):
            return "identical", theirs
        entry = ledger["reports"].get(storage.control_key(control))
        if entry and entry.get("fingerprint") == fingerprint(theirs):
            return "update", theirs
        kind = CHANGED_ELSEWHERE if entry else NOT_OWNED
        return self._conflict(kind, data, theirs,
                              ledger.get("emptied")), theirs

    def _conflict(self, kind, mine, theirs, emptied=None):
        control = mine["control_no"]
        if kind == CHANGED_ELSEWHERE:
            why = (f"This copy of the program sent report {control} to "
                   "MySQL, but afterwards it was changed in MySQL by another "
                   "copy of the program or directly in the database.")
        elif emptied:
            # The program cannot know any more whether it sent this one.
            why = ("MySQL already holds a DIFFERENT report numbered "
                   f"{control}, and this copy of the program has no record "
                   "of having sent it. (Its record was reset on "
                   f"{str(emptied).replace('T', ' ')}, because the Excel "
                   "file had been changed outside the program or restored.)")
        else:
            why = ("MySQL already holds a DIFFERENT report numbered "
                   f"{control} that this copy of the program did not put "
                   "there.")
        return {"kind": kind, "control": control, "text": why,
                "mine": summary(mine), "theirs": summary(theirs),
                "differences": differences(mine, theirs),
                "found": self._now().isoformat(timespec="seconds")}

    def save(self, data, decision=None, connection=None):
        """Write one report under the rule of the module text.

        Returns ("written" | "identical", notes). Raises MySQLConflict when
        MySQL holds something this copy may not overwrite - unless
        decision == REPLACE (the user's deliberate choice), in which case
        the replaced version is kept first. Raises MySQLBusy when another
        copy holds the lock."""
        if not supports(self.db):               # a simple stand-in
            return "written", self.db.save_report(data) or []
        control = data["control_no"]
        own = connection is None
        conn = connection or self.db.connect()
        locked = False
        try:
            locked = self.db.lock_report(conn, control)
            if not locked:
                raise MySQLBusy(
                    f"Another copy of the program is saving {control} in "
                    "MySQL right now. It will be tried again.")
            ledger = self.ledger()
            verdict, theirs = self._decide(conn, data, ledger,
                                           lock_rows=True)
            if verdict == "identical":
                conn.rollback()
                self._remember(ledger, control, theirs)
                return "identical", []
            if isinstance(verdict, dict) and decision != REPLACE:
                conn.rollback()
                raise MySQLConflict(verdict)
            if decision == REPLACE and theirs is not None:
                # A deliberate replacement: what is there now is kept
                # first, whoever wrote it.
                self.keep_replaced(theirs, verdict["kind"] if isinstance(
                    verdict, dict) else "replaced on request")
            notes = self.db.write_report(conn, data) or []
            conn.commit()
            self._remember(ledger, control,
                           self.db.load_report(control, conn))
            return "written", notes
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            if locked:
                try:
                    self.db.unlock_report(conn, control)
                except Exception:
                    log.exception("MySQL lock of %s not released", control)
            if own:
                conn.close()

    # ---- many reports (Import, Sync to MySQL, first run) ----
    def plan(self, reports, connection=None):
        """Sort reports by what a write would do, without writing:
        {"new": [...], "identical": [...], "update": [...],
         "conflicts": [(report, conflict)]}."""
        result = {"new": [], "identical": [], "update": [], "conflicts": []}
        own = connection is None
        conn = connection or self.db.connect()
        try:
            ledger = self.ledger()
            for report in reports:
                verdict, _ = self._decide(conn, report, ledger)
                if isinstance(verdict, dict):
                    result["conflicts"].append((report, verdict))
                else:
                    result[verdict].append(report)
        finally:
            if own:
                try:
                    conn.rollback()
                finally:
                    conn.close()
        return result

    def save_many(self, reports, replace=()):
        """Write every report that may be written. `replace` holds the
        Control #s the user ticked to replace in MySQL. Returns
        {"written": [...], "identical": [...], "conflicts": [(report,
        conflict)], "errors": [(control, text)]}."""
        chosen = {storage.control_key(c) for c in replace}
        result = {"written": [], "identical": [], "conflicts": [],
                  "errors": []}
        if not supports(self.db):
            for report in reports:
                try:
                    self.db.save_report(report)
                    result["written"].append(report["control_no"])
                except Exception as error:
                    result["errors"].append((report["control_no"],
                                             str(error)))
            return result
        conn = self.db.connect()
        try:
            for report in reports:
                control = report["control_no"]
                decision = REPLACE if storage.control_key(
                    control) in chosen else None
                try:
                    status, _ = self.save(report, decision, conn)
                    result[status].append(control)
                except MySQLConflict as conflict:
                    result["conflicts"].append((report, conflict.conflict))
                except MySQLBusy as busy:
                    result["errors"].append((control, str(busy)))
                except Exception as error:
                    log.exception("MySQL write of %s failed", control)
                    result["errors"].append((control, str(error)))
        finally:
            conn.close()
        return result

    def adopt_identical(self, reports):
        """First run with existing data: reports that MySQL holds with the
        same value become this copy's own, without a question. Returns the
        Control #s adopted. Writes nothing to MySQL."""
        if not supports(self.db):
            return []
        adopted = []
        conn = self.db.connect()
        try:
            ledger = self.ledger()
            for report in reports:
                control = report["control_no"]
                if storage.control_key(control) in ledger["reports"]:
                    continue
                if not control_in(self.db, conn, control):
                    continue
                theirs = self.db.load_report(control, conn)
                if same_value(report, theirs):
                    ledger["reports"][storage.control_key(control)] = {
                        "control": control,
                        "fingerprint": fingerprint(theirs),
                        "written": self._now().isoformat(timespec="seconds"),
                        "adopted": True}
                    adopted.append(control)
            if adopted:
                self._store(ledger)
        finally:
            try:
                conn.rollback()
            finally:
                conn.close()
        return adopted

    def taken(self, control_no):
        """True when MySQL has a report with this number that is not this
        copy's own (used to pick a free number for a new report)."""
        if not supports(self.db):
            return False
        conn = self.db.connect()
        try:
            return control_in(self.db, conn, control_no) and not self.owns(
                control_no)
        finally:
            conn.close()

    # ---- what was replaced ----
    def keep_replaced(self, theirs, reason=""):
        """Save the version that is about to be replaced; returns its file.
        Raises OSError when it cannot be kept - then nothing is replaced."""
        now = self._now()
        control = theirs["control_no"]
        self.replaced_dir.mkdir(parents=True, exist_ok=True)
        name = f"{storage.safe_filename(control)}_{now:%Y%m%d_%H%M%S}"
        target = self.replaced_dir / f"{name}.json"
        counter = 1
        while target.exists():
            counter += 1
            target = self.replaced_dir / f"{name}_{counter}.json"
        ledger, _ = self._read()
        record = {
            "format": "fsr-mysql-replaced", "version": VERSION,
            "control_no": control,
            "replaced_at": now.isoformat(timespec="seconds"),
            "replaced_by": self.user,
            "copy_id": ledger.get("copy_id", ""),
            "copy_workbook": str(self.excel_path),
            "computer": socket.gethostname(),
            "reason": reason,
            "report": theirs,
        }
        storage.write_json_atomic(target, record)
        log_file = self.replaced_dir / "replaced_log.csv"
        fresh = not log_file.exists()
        with open(log_file, "a", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            if fresh:
                writer.writerow(["replaced_at", "control_no", "replaced_by",
                                 "computer", "copy_workbook", "copy_id",
                                 "reason", "kept_as"])
            writer.writerow([record["replaced_at"], control, self.user,
                             record["computer"], record["copy_workbook"],
                             record["copy_id"], reason, target.name])
        log.warning("MySQL report %s replaced by %s from %s; the replaced "
                    "version is kept as %s", control, self.user or "?",
                    self.excel_path, target)
        return target

    def put_back(self, file_path):
        """Write a kept version into MySQL again (what is there now is kept
        first). Returns the Control #."""
        with open(file_path, "r", encoding="utf-8") as file:
            record = json.load(file)
        if not isinstance(record, dict) or record.get(
                "format") != "fsr-mysql-replaced" or not isinstance(
                record.get("report"), dict):
            raise ValueError("This is not a kept MySQL report.")
        report = record["report"]
        self.save(report, REPLACE)
        return report["control_no"]


def control_in(db, conn, control_no):
    """Is this Control # in MySQL? (no row lock)"""
    wanted = storage.control_key(control_no)
    if hasattr(db, "has_report"):
        return db.has_report(conn, control_no)
    cur = conn.cursor()
    try:
        cur.execute("SELECT control_no FROM reports WHERE control_no = %s",
                    (control_no,))
        return any(storage.control_key(row[0]) == wanted
                   for row in cur.fetchall())
    finally:
        cur.close()
