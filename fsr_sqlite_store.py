"""The SQLite store (Phase 5): the reports of this PC in ONE database file
beside the workbook, written in one transaction per save.

What it holds is exactly what the two workbooks hold: every row of the
Reports, Declared Goods, Item List and Remarks sheets and of the four
sheets of the Withdrawal workbook, each row as its cells hold it (numbers
as numbers, dates as dates) and in the order of the sheet. Rows are made by
the same functions as the workbook's (fsr_storage.report_row_values,
report_child_rows; fsr_withdrawal.header_values, plan_lines,
goods_and_remarks) and read back by the same functions
(fsr_storage.report_from_rows, fsr_withdrawal.reports_from_rows), so every
screen gets the same report as from the workbook.

Kept as files, as before: the incident texts, the other Item List forms,
the import record, the MySQL ledger, the save record, PO_Master and
Withdrawn_Item. The workbooks themselves become an export in today's
layout (fsr_sqlite_export), written from here in the background.

Where the database lives: this Windows user's Local AppData, never next to
the workbook (fsr_db_location). A database is in use for a workbook when
fsr_db_location finds it (it is put there only after a migration passed its
comparison - fsr_sqlite_migrate). A database still next to the workbook
(where the first Phase 5 builds put it) is used until it is moved.
"""
import json
import sqlite3
import threading
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

import fsr_backup
import fsr_db_location as location
import fsr_import
import fsr_mysql_guard
import fsr_paths
import fsr_renumber
import fsr_save_journal
import fsr_storage as storage
import fsr_withdrawal

DB_SUFFIX = location.DB_SUFFIX
SCHEMA_VERSION = 1
MAIN, BOOK = "main", "withdrawal"

# The child sheets of each book, as in the workbooks.
MAIN_SHEETS = ("Declared Goods", "Item List", "Remarks")
BOOK_SHEETS = (fsr_withdrawal.LINE_SHEET, fsr_withdrawal.GOODS_SHEET,
               fsr_withdrawal.REMARK_SHEET)
HEADERS = {
    MAIN: {name: headers for name, (_, headers)
           in storage.EXCEL_SHEETS.items()},
    BOOK: {name: headers for name, (_, headers)
           in fsr_withdrawal.WITHDRAWAL_SHEETS.items()},
}
HEADER_SHEET = {MAIN: "Reports", BOOK: fsr_withdrawal.HEADER_SHEET}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- one row per report: the row of its Reports / Withdrawal Reports sheet
CREATE TABLE IF NOT EXISTS reports (
    book       TEXT NOT NULL CHECK (book IN ('main', 'withdrawal')),
    key        TEXT NOT NULL,          -- Control #, no spaces, any case
    control_no TEXT NOT NULL,          -- as it is spelled
    seq        INTEGER NOT NULL,       -- its place in the sheet
    header     TEXT NOT NULL,          -- {column: cell value} (JSON)
    PRIMARY KEY (book, key)
);
-- a Control # is unique across both kinds of report
CREATE UNIQUE INDEX IF NOT EXISTS reports_by_key ON reports (key);
-- the rows of the other sheets
CREATE TABLE IF NOT EXISTS lines (
    book  TEXT NOT NULL,
    sheet TEXT NOT NULL,
    seq   INTEGER NOT NULL,            -- its place in the sheet
    key   TEXT NOT NULL,               -- the report it belongs to
    row   TEXT NOT NULL,               -- [cell values] (JSON)
    PRIMARY KEY (book, sheet, seq)
);
CREATE INDEX IF NOT EXISTS lines_by_key ON lines (key);
"""


def existing_db(excel_path):
    """The database in use for this workbook, or None: in Local AppData, or
    still next to the workbook (until it is moved)."""
    found = location.find_db(excel_path)
    if found is not None:
        return found
    legacy = location.legacy_db_path(excel_path)
    return legacy if legacy.is_file() else None


def db_path_for(excel_path):
    """The database of this workbook: where it is, else where a new one
    goes (Local AppData)."""
    return existing_db(excel_path) or location.default_db_path(excel_path)


def is_active(excel_path):
    return existing_db(excel_path) is not None


# ---------- cell values <-> JSON ------------------------------

def encode(value):
    if isinstance(value, Decimal):
        # As the workbook gives a number back: whole -> int, else float.
        return int(value) if value == value.to_integral_value()             else float(value)
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, date):
        return {"$d": value.isoformat()}
    if isinstance(value, time):
        return {"$t": value.isoformat()}
    return value


def decode(value):
    if isinstance(value, dict):
        if "$dt" in value:
            return datetime.fromisoformat(value["$dt"])
        if "$d" in value:
            return date.fromisoformat(value["$d"])
        if "$t" in value:
            return time.fromisoformat(value["$t"])
    return value


def dump_row(values):
    return json.dumps([encode(v) for v in values], ensure_ascii=False)


def load_row(text):
    return tuple(decode(v) for v in json.loads(text))


def dump_header(values):
    return json.dumps({k: encode(v) for k, v in values.items()},
                      ensure_ascii=False)


def load_header(text):
    return {k: decode(v) for k, v in json.loads(text).items()}


def key_of(control):
    return storage.control_key(control)


# ---------- the database ----------------------------------------

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()

# Called with the workbook path after every committed write (the window
# asks for a new export then). Set by the window; empty elsewhere.
listeners = []


def _changed(excel_path):
    import logging
    for listener in list(listeners):
        try:
            listener(excel_path)
        # Broad on purpose: telling the window must never undo or fail a
        # write that is committed already.
        except Exception:
            logging.getLogger("fsr").exception("A change listener failed")


def _lock_for(path):
    """One write lock per database file in this process: writes from the
    window and from background work come one after the other."""
    key = str(Path(path).resolve()).casefold()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def connect(path):
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    # The rollback journal (not WAL): the database file itself changes with
    # every committed write, which the MySQL ledger's note relies on.
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create(path, database_id=None, workbook=None):
    """A new, empty database (the file must not exist yet), carrying its
    id and the workbook it belongs to."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO meta VALUES ('schema_version', ?)",
                     (str(SCHEMA_VERSION),))
        conn.execute("INSERT INTO meta VALUES ('changes', '0')")
        conn.execute("INSERT INTO meta VALUES ('database_id', ?)",
                     (database_id or location.new_id(),))
        if workbook is not None:
            conn.execute("INSERT INTO meta VALUES ('workbook', ?)",
                         (str(Path(workbook).resolve()),))
    finally:
        conn.close()


def read_meta(path, key):
    """One value of a database's meta table (None when it is not there)."""
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        found = conn.execute("SELECT value FROM meta WHERE key=?",
                             (key,)).fetchone()
    except sqlite3.DatabaseError:
        return None
    finally:
        conn.close()
    return found[0] if found else None


def write_meta(path, values):
    """Set meta values (the id, the workbook) - one transaction. Not a
    change of the reports: the change counter stays as it is."""
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for key, value in values.items():
            conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                         (key, str(value)))
        conn.execute("COMMIT")
    finally:
        conn.close()


class SqliteStore:
    """The store of the workbook `excel_path` once it moved to SQLite. The
    same methods as fsr_store.ExcelStore, with the same results."""

    kind = "sqlite"

    def __init__(self, excel_path, required_root=None, db_path=None):
        self.excel_path = Path(excel_path)
        self.required_root = required_root
        self.db_path = Path(db_path) if db_path else db_path_for(excel_path)
        self._lock = _lock_for(self.db_path)

    # ---- where things are ----
    @property
    def withdrawal_path(self):
        return fsr_paths.withdrawal_workbook_path(self.excel_path,
                                                  self.required_root)

    @property
    def database_id(self):
        """The id this database carries (also written into its exports).
        A database made before ids existed gets one now."""
        found = read_meta(self.db_path, "database_id")
        if not found:
            found = location.new_id()
            write_meta(self.db_path, {"database_id": found})
        return found

    @property
    def backup_name(self):
        """The name its backups are given: beside the workbook, in the
        Backups folder in Documents (the database itself is in Local
        AppData): Backups\\<workbook name>_backup_<date>.sqlite3."""
        return self.excel_path.with_suffix(DB_SUFFIX)

    def ledger_files(self):
        """What the MySQL ledger's note of "the data as the program last
        left it" is about: the database file."""
        return [self.db_path]

    # ---- low level ----
    def _read(self, sql, args=()):
        if not self.db_path.is_file():
            raise FileNotFoundError(f"The database is missing: {self.db_path}")
        conn = connect(self.db_path)
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def _write(self, work):
        """work(conn) inside ONE transaction: all of it or nothing."""
        with self._lock:
            conn = connect(self.db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    result = work(conn)
                    conn.execute(
                        "UPDATE meta SET value = CAST(value AS INTEGER) + 1 "
                        "WHERE key = 'changes'")
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            finally:
                conn.close()
        _changed(self.excel_path)
        return result

    def changes(self):
        """A counter that grows with every write."""
        (value,), = self._read("SELECT value FROM meta WHERE key='changes'")
        return int(value)

    def _headers(self, book):
        """[{column: value}] of one book, in sheet order."""
        return [load_header(text) for (text,) in self._read(
            "SELECT header FROM reports WHERE book=? ORDER BY seq", (book,))]

    def _grouped(self, book, sheets):
        """{sheet: {key: [row values]}} in sheet order."""
        grouped = {name: {} for name in sheets}
        for sheet, key, text in self._read(
                "SELECT sheet, key, row FROM lines WHERE book=? "
                "ORDER BY sheet, seq", (book,)):
            if sheet in grouped and key:
                grouped[sheet].setdefault(key, []).append(load_row(text))
        return grouped

    def _sheet_rows(self, book, sheet):
        return [load_row(text) for (text,) in self._read(
            "SELECT row FROM lines WHERE book=? AND sheet=? ORDER BY seq",
            (book, sheet))]

    @staticmethod
    def _next_seq(conn, table, book, sheet=None):
        if table == "reports":
            (top,), = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM reports WHERE book=?",
                (book,)).fetchall()
        else:
            (top,), = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM lines WHERE book=? AND "
                "sheet=?", (book, sheet)).fetchall()
        return top + 1

    @staticmethod
    def _numbers(conn, book):
        return [c for (c,) in conn.execute(
            "SELECT control_no FROM reports WHERE book=? ORDER BY seq",
            (book,))]

    @staticmethod
    def _append_line(conn, book, sheet, key, values):
        seq = SqliteStore._next_seq(conn, "lines", book, sheet)
        conn.execute("INSERT INTO lines VALUES (?, ?, ?, ?, ?)",
                     (book, sheet, seq, key, dump_row(values)))

    # ---- reports of the main workbook ----
    def list_reports(self):
        """[(Control #, SO, inspection date, consignee, last saved)]"""
        reports = []
        for values in self._headers(MAIN):
            if not values.get("Control #"):
                continue
            reports.append((
                storage.cell_text(values.get("Control #")),
                storage.cell_text(values.get("SO Number")),
                storage.cell_text(values.get("Inspection Date")),
                storage.cell_text(values.get("Consignee")),
                storage.cell_text(values.get("Last Saved"), with_time=True),
            ))
        reports.sort(key=lambda entry: storage.control_sort_key(entry[0]),
                     reverse=True)
        return reports

    def read_report(self, control_no):
        found = self._read(
            "SELECT header FROM reports WHERE book=? AND key=?",
            (MAIN, key_of(control_no)))
        if not found:
            raise ValueError(
                f"Control # {control_no} was not found in the Excel file.")
        rows = {}
        for sheet, text in self._read(
                "SELECT sheet, row FROM lines WHERE book=? AND key=? "
                "ORDER BY seq", (MAIN, key_of(control_no))):
            rows.setdefault(sheet, []).append(load_row(text))
        return storage.report_from_rows(
            self.excel_path, load_header(found[0][0]),
            lambda sheet: rows.get(sheet, []))

    def read_all_reports(self):
        grouped = self._grouped(MAIN, MAIN_SHEETS)
        reports = []
        for values in self._headers(MAIN):
            if not values.get("Control #"):
                continue
            key = key_of(values["Control #"])
            reports.append(storage.report_from_rows(
                self.excel_path, values,
                lambda sheet, key=key: grouped[sheet].get(key, [])))
        return reports

    def search_index(self):
        """The same as fsr_storage.search_index_excel(), from the rows."""
        index = {}

        def entry(control):
            return index.setdefault(control, {
                "so": [], "bl": [], "po": [], "dr": [], "gatepass": [],
                "description": []})

        def add(item, key, value):
            value = storage.cell_text(value)
            if value:
                item[key].append(value)

        for values in self._headers(MAIN):
            if not values.get("Control #"):
                continue
            item = entry(storage.cell_text(values["Control #"]))
            add(item, "so", values.get("SO Number"))
            add(item, "bl", values.get("BL/AWB Number"))
            add(item, "po", values.get("PO Number"))
            add(item, "dr", values.get("DR Number"))
            add(item, "gatepass", values.get("Gatepass Number"))
        for sheet, desc_key in (("Item List", "Description of Goods"),
                                ("Declared Goods", "Description")):
            headers = HEADERS[MAIN][sheet]
            for row in self._sheet_rows(MAIN, sheet):
                values = dict(zip(headers, row))
                if not values.get("Control #"):
                    continue
                item = entry(storage.cell_text(values["Control #"]))
                add(item, "description", values.get(desc_key))
                if sheet == "Item List":
                    add(item, "po", values.get("PO Number"))
        return index

    def write_report(self, data, editing, saved_at=None):
        return self.write_reports([(data, editing, saved_at)])[0]

    def write_reports(self, items):
        """[(data, editing, saved_at)] in ONE transaction - all or none.
        The same rules as fsr_storage.write_reports_to_excel()."""
        def work(conn):
            return [self._apply_report(conn, data, editing, saved_at)
                    for data, editing, saved_at in items]
        return self._write(work)

    def _apply_report(self, conn, data, editing, saved_at):
        control_no = data["control_no"]
        key = key_of(control_no)
        existing = conn.execute(
            "SELECT seq FROM reports WHERE book=? AND key=?",
            (MAIN, key)).fetchone()
        elsewhere = self._numbers(conn, BOOK)
        taken_elsewhere = any(storage.same_key(n, control_no)
                              for n in elsewhere)
        if editing and taken_elsewhere and not existing:
            raise ValueError(
                f"Control # {control_no} belongs to the Withdrawal workbook "
                "and cannot be saved into this file.")
        if (existing or taken_elsewhere) and not editing:
            control_no = storage.next_control_number(
                [*self._numbers(conn, MAIN), *elsewhere])
            key = key_of(control_no)
            existing = None

        header = dict(zip(storage.REPORT_HEADERS, storage.report_row_values(
            data, control_no, saved_at)))
        if existing:
            conn.execute(
                "UPDATE reports SET control_no=?, header=? WHERE book=? AND "
                "key=?", (control_no, dump_header(header), MAIN, key))
        else:
            conn.execute(
                "INSERT INTO reports VALUES (?, ?, ?, ?, ?)",
                (MAIN, key, control_no, self._next_seq(conn, "reports", MAIN),
                 dump_header(header)))

        conn.execute(
            "DELETE FROM lines WHERE book=? AND key=? AND sheet IN (?, ?, ?)",
            (MAIN, key, *MAIN_SHEETS))
        child = storage.report_child_rows(data, control_no)
        for sheet in MAIN_SHEETS:
            for values in child[sheet]:
                self._append_line(conn, MAIN, sheet, key, values)
        return {
            "control": control_no,
            "updated": existing is not None,
            "goods": len(data["declared_goods"]),
            "items": len(child["Item List"]),
            "remarks": len(child["Remarks"]),
        }

    def delete_reports(self, control_numbers):
        """Demo Mode reset only, with the same refusal as ExcelStore."""
        import fsr_store
        fsr_store.check_demo_delete(self.excel_path, control_numbers)
        keys = {key_of(c) for c in control_numbers}

        def work(conn):
            present = {k for (k,) in conn.execute(
                "SELECT key FROM reports WHERE book=?", (MAIN,))}
            for key in keys:
                conn.execute("DELETE FROM reports WHERE book=? AND key=?",
                             (MAIN, key))
                conn.execute("DELETE FROM lines WHERE book=? AND key=?",
                             (MAIN, key))
            return len(keys & present)
        return self._write(work)

    def last_saved_times(self):
        return self._last_saved(MAIN)

    def _last_saved(self, book):
        return {
            storage.cell_text(values["Control #"]).casefold():
                str(values.get("Last Saved") or "")
            for values in self._headers(book) if values.get("Control #")
        }

    def saved_stamp(self, control_no, linked):
        """The Last Saved time of a report (ISO text), or None when it is
        not there (the save record recognises a save by it)."""
        found = self._read(
            "SELECT header FROM reports WHERE book=? AND key=?",
            (BOOK if linked else MAIN, key_of(control_no)))
        if not found:
            return None
        value = load_header(found[0][0]).get("Last Saved")
        if isinstance(value, datetime):
            return value.isoformat(timespec="milliseconds")
        return str(value) if value is not None else ""

    # ---- PO lines ----
    def find_po(self, po_number):
        return fsr_withdrawal.find_po(
            self.excel_path, po_number, self.read_all_reports(),
            self.read_all_withdrawal_reports())

    def remaining_quantity(self, row, except_control=""):
        return fsr_withdrawal.remaining_quantity(
            self.excel_path, row, except_control, self.read_all_reports(),
            self.read_all_withdrawal_reports())

    # ---- PO-linked Withdrawal reports ----
    def owns_withdrawal(self, control_no):
        return bool(self._read(
            "SELECT 1 FROM reports WHERE book=? AND key=?",
            (BOOK, key_of(control_no))))

    def withdrawal_numbers(self):
        return [storage.cell_text(c) for (c,) in self._read(
            "SELECT control_no FROM reports WHERE book=? ORDER BY seq",
            (BOOK,)) if c]

    def list_withdrawal_reports(self):
        return [(
            storage.cell_text(values.get("Control #")),
            storage.cell_text(values.get("SO Number")),
            storage.cell_text(values.get("Inspection Date")),
            storage.cell_text(values.get("Consignee")),
            storage.cell_text(values.get("Last Saved"), with_time=True),
        ) for values in self._headers(BOOK) if values.get("Control #")]

    def read_withdrawal_report(self, control_no):
        for report in self.read_all_withdrawal_reports():
            if storage.same_key(report["control_no"], control_no):
                return report
        raise ValueError(
            f"Control # {control_no} was not found in "
            f"{fsr_paths.WITHDRAWAL_WORKBOOK_NAME}.")

    def read_all_withdrawal_reports(self):
        return fsr_withdrawal.reports_from_rows(
            self.excel_path.with_name(fsr_paths.WITHDRAWAL_WORKBOOK_NAME),
            self._headers(BOOK), self._grouped(BOOK, BOOK_SHEETS))

    def withdrawal_search_index(self):
        return fsr_withdrawal.search_index(
            None, self.read_all_withdrawal_reports())

    def withdrawal_last_saved_times(self):
        return self._last_saved(BOOK)

    def write_withdrawal_report(self, data, editing, saved_at=None):
        """The same rules as fsr_withdrawal.write_withdrawal_report()."""
        rows = [row for section in data["item_lists"]
                for row in section["rows"]]
        control_no = data["control_no"]
        # What the OTHER reports took: read before the write starts.
        taken = fsr_withdrawal.withdrawn_by_ref(
            self.excel_path, control_no if editing else "",
            main_reports=self.read_all_reports(),
            book_reports=self.read_all_withdrawal_reports())

        def work(conn):
            nonlocal control_no
            key = key_of(control_no)
            existing = conn.execute(
                "SELECT seq FROM reports WHERE book=? AND key=?",
                (BOOK, key)).fetchone()
            main_numbers = [e[0] for e in self.list_reports()]
            in_main = any(storage.same_key(n, control_no)
                          for n in main_numbers)
            if editing and in_main and not existing:
                raise fsr_withdrawal.WithdrawalError(
                    f"Control # {control_no} belongs to the main workbook and "
                    "cannot be saved into the Withdrawal workbook.")
            fsr_withdrawal.validate_rows(rows, None, "", taken=taken)
            if (existing or in_main) and not editing:
                control_no = storage.next_control_number(
                    [*main_numbers, *self._numbers(conn, BOOK)])
                key = key_of(control_no)
                existing = None

            header = dict(zip(fsr_withdrawal.HEADER_HEADERS,
                              fsr_withdrawal.header_values(data, control_no,
                                                           saved_at)))
            if existing:
                conn.execute(
                    "UPDATE reports SET control_no=?, header=? WHERE book=? "
                    "AND key=?", (control_no, dump_header(header), BOOK, key))
            else:
                conn.execute(
                    "INSERT INTO reports VALUES (?, ?, ?, ?, ?)",
                    (BOOK, key, control_no,
                     self._next_seq(conn, "reports", BOOK),
                     dump_header(header)))

            # lines: changed ones in place, removed ones deleted, new added
            id_at = fsr_withdrawal.LINE_HEADERS.index(
                fsr_withdrawal.LINE_ID_HEADER)
            sheet = fsr_withdrawal.LINE_SHEET
            located = {}
            for seq, text in conn.execute(
                    "SELECT seq, row FROM lines WHERE book=? AND sheet=? AND "
                    "key=? ORDER BY seq", (BOOK, sheet, key)):
                located[str(load_row(text)[id_at])] = seq
            delete, lines = fsr_withdrawal.plan_lines(
                list(located), control_no, data["item_lists"])
            for line_id in delete:
                conn.execute("DELETE FROM lines WHERE book=? AND sheet=? AND "
                             "seq=?", (BOOK, sheet, located[line_id]))
            for line_id, values, kept in lines:
                if kept:
                    conn.execute(
                        "UPDATE lines SET row=? WHERE book=? AND sheet=? AND "
                        "seq=?", (dump_row(values), BOOK, sheet,
                                  located[line_id]))
                else:
                    self._append_line(conn, BOOK, sheet, key, values)

            conn.execute(
                "DELETE FROM lines WHERE book=? AND key=? AND sheet IN (?, ?)",
                (BOOK, key, fsr_withdrawal.GOODS_SHEET,
                 fsr_withdrawal.REMARK_SHEET))
            goods, remarks = fsr_withdrawal.goods_and_remarks(data,
                                                              control_no)
            for values in goods:
                self._append_line(conn, BOOK, fsr_withdrawal.GOODS_SHEET,
                                  key, values)
            for values in remarks:
                self._append_line(conn, BOOK, fsr_withdrawal.REMARK_SHEET,
                                  key, values)
            return {
                "control": control_no,
                "updated": existing is not None,
                "goods": len(data["declared_goods"]),
                "items": len(rows),
                "remarks": len(remarks),
            }
        return self._write(work)

    # ---- Control #s ----
    def next_control_number(self):
        numbers = [values.get("Control #") for values in self._headers(MAIN)]
        return storage.next_control_number(
            [*numbers, *self.withdrawal_numbers()])

    def control_numbers(self):
        return [e[0] for e in self.list_reports()] + self.withdrawal_numbers()

    def next_free_number(self, old, also_taken=()):
        return storage.next_control_number(
            [*self.control_numbers(), *also_taken, old],
            storage.control_initials_of(old))

    def renumber(self, old, new):
        return fsr_renumber.renumber_report(self.excel_path, old, new,
                                            self.required_root, store=self)

    def renumber_rows(self, old, new):
        """Every cell of the reports that names `old` (Control # columns,
        the reference columns and the Receiving Refs), in one transaction.
        Returns the number of cells changed."""
        def swap_header(values):
            changed = 0
            for column, value in list(values.items()):
                if value is None:
                    continue
                if column == "Control #" or \
                        column in fsr_renumber.REFERENCE_HEADERS:
                    if storage.same_key(value, old):
                        values[column] = new
                        changed += 1
                elif column == fsr_renumber.REF_HEADER:
                    swapped = fsr_renumber._swap_ref(value, old, new)
                    if swapped != value:
                        values[column] = swapped
                        changed += 1
            return changed

        def work(conn):
            changed = 0
            for book, key, text in conn.execute(
                    "SELECT book, key, header FROM reports").fetchall():
                values = load_header(text)
                count = swap_header(values)
                if count:
                    changed += count
                    conn.execute(
                        "UPDATE reports SET key=?, control_no=?, header=? "
                        "WHERE book=? AND key=?",
                        (key_of(values.get("Control #")),
                         storage.cell_text(values.get("Control #")),
                         dump_header(values), book, key))
            for book, sheet, seq, text in conn.execute(
                    "SELECT book, sheet, seq, row FROM lines").fetchall():
                headers = HEADERS[book][sheet]
                values = dict(zip(headers, load_row(text)))
                count = swap_header(values)
                if count:
                    changed += count
                    row = list(load_row(text))
                    for index, column in enumerate(headers[:len(row)]):
                        row[index] = values[column]
                    conn.execute(
                        "UPDATE lines SET key=?, row=? WHERE book=? AND "
                        "sheet=? AND seq=?",
                        (key_of(row[0]), dump_row(row), book, sheet, seq))
            return changed
        return self._write(work)

    # ---- the files beside a report (unchanged: JSON files) ----
    def save_incidents(self, control_no, so_number, reports):
        return storage.save_incident_data(self.excel_path, control_no,
                                          so_number, reports)

    def load_incidents(self, control_no):
        return storage.load_incident_data(self.excel_path, control_no)

    def delete_incidents(self, control_no):
        return storage.delete_incident_data(self.excel_path, control_no)

    def save_item_forms(self, control_no, forms):
        return storage.save_other_item_forms(self.excel_path, control_no,
                                             forms)

    def load_item_forms(self, control_no):
        return storage.load_other_item_forms(self.excel_path, control_no)

    # ---- derived lists ----
    def rebuild_item_lists(self):
        return fsr_withdrawal.sync_item_lists(
            self.excel_path, self.read_all_reports(),
            self.read_all_withdrawal_reports())

    # ---- records kept beside the reports ----
    def save_record(self):
        return fsr_save_journal.Journal(self.excel_path)

    def save_steps(self, mysql=None, guard=None):
        return fsr_save_journal.Stores(self.excel_path, mysql=mysql,
                                       required_root=self.required_root,
                                       guard=guard)

    def mysql_guard(self, db, user=""):
        return fsr_mysql_guard.Guard(db, self.excel_path, user=user)

    def imported_inspector(self, control_no):
        return fsr_import.imported_inspector(self.excel_path, control_no)

    def import_master_data(self, data, **options):
        return fsr_import.import_master_data(self.excel_path, data,
                                             **options)

    def backup_before_save(self, keep, linked=False):
        """Today's copy of the database (one file for both kinds of
        report), made with SQLite's own backup."""
        return fsr_backup.backup_before_save(self.backup_name, keep,
                                             copy=self.copy_to,
                                             source=self.db_path)

    def copy_to(self, target):
        """A consistent copy of the database into `target`, made with
        SQLite's own backup (correct even while another connection writes),
        then checked with SQLite's integrity check. A copy that fails the
        check is removed and sqlite3.DatabaseError is raised."""
        source = connect(self.db_path)
        try:
            copy = sqlite3.connect(str(target))
            try:
                source.backup(copy)
            finally:
                copy.close()
        finally:
            source.close()
        problem = integrity_problem(target)
        if problem:
            try:
                Path(target).unlink()
            except OSError:
                pass
            raise sqlite3.DatabaseError(
                f"The backup copy failed its integrity check: {problem}")


def integrity_problem(path):
    """None when SQLite's integrity check of the database file `path`
    passes; otherwise what it found (also: not a database at all)."""
    try:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro",
                               uri=True)
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError as error:
        return str(error)
    found = [str(row[0]) for row in rows]
    return None if found == ["ok"] else "; ".join(found[:5])


def new_store(excel_path, required_root=None):
    """The SQLite store of a workbook that has no reports yet: its empty
    database is created in Local AppData (a new PC, a new data folder, the
    tests)."""
    if not is_active(excel_path):
        path = location.default_db_path(excel_path)
        database_id = location.new_id()
        create(path, database_id, excel_path)
        location.register(path, excel_path, database_id)
    return SqliteStore(excel_path, required_root)
