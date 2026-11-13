"""The Excel export of the SQLite store (Phase 5).

Once the reports are in the database, the workbooks Field_Survey_Reports.xlsx
and Withdrawal_Reports.xlsx are written FROM it, in today's layout exactly
(the same sheets, columns, number formats and tables, made by the same
functions as before), in the background after each change. So:

* opening the file in Excel, sending it, and the previous version of the
  program all see every report, as before;
* the file can be rebuilt at any time from the database.

The program notes each file it wrote (size, change time, SHA-256) in
<database file>.export.json next to the database in Local AppData - not in
the database, so writing the export never touches the database file the
MySQL ledger watches, and the note follows the database when the workbook
is moved. A file that differs from that note was changed outside the
program: it is never overwritten (fsr_sqlite_migrate.reconcile decides what
happens to it).

Each exported workbook carries the database's id in its document
properties (fsr_db_location.stamp_identity): a moved workbook finds its
database by it, and a file written by ANOTHER database (another PC sharing
the folder through OneDrive) is recognised as not this PC's.
"""
import hashlib
import json
import logging
from pathlib import Path

import fsr_paths
import fsr_storage as storage
import fsr_withdrawal

log = logging.getLogger("fsr")


class ChangedOutside(Exception):
    """An exported file was changed since the program wrote it."""

    def __init__(self, paths):
        super().__init__(", ".join(Path(p).name for p in paths))
        self.paths = [Path(p) for p in paths]


def state_path(store):
    """The note of what was exported, next to the database."""
    return store.db_path.with_name(store.db_path.name + ".export.json")


def legacy_state_path(excel_path):
    """Where the first Phase 5 builds kept that note (the JSON folder)."""
    excel_path = Path(excel_path)
    return (fsr_paths.json_dir_for_workbook(excel_path)
            / f"{excel_path.stem}_export.json")


def load_state(store):
    for path in (state_path(store), legacy_state_path(store.excel_path)):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            log.warning("The export note %s cannot be read", path)
            return None
        return state if isinstance(state, dict) else None
    return None


def save_state(store, changes, files):
    path = state_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json_atomic(path, {"changes": changes, "files": files})
    try:
        legacy_state_path(store.excel_path).unlink()   # replaced by this one
    except OSError:
        pass


def drop_state(store):
    for path in (state_path(store), legacy_state_path(store.excel_path)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def file_note(path):
    """{size, mtime_ns, sha256} of a file, or None when it is not there."""
    path = Path(path)
    try:
        info = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns,
            "sha256": digest}


def _same(note, path):
    """Is the file still what `note` says (by content)?"""
    path = Path(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        return note is None
    if note is None:
        return False
    if info.st_size == note["size"] and info.st_mtime_ns == note["mtime_ns"]:
        return True
    return hashlib.sha256(path.read_bytes()).hexdigest() == note["sha256"]


def export_paths(store):
    return {"main": store.excel_path,
            "withdrawal": store.excel_path.with_name(
                fsr_paths.WITHDRAWAL_WORKBOOK_NAME)}


def changed_outside(store):
    """The exported files that were changed since the program wrote them."""
    state = load_state(store)
    if state is None:
        return []
    files = state.get("files") or {}
    return [path for name, path in export_paths(store).items()
            if name in files and not _same(files[name], path)]


def is_current(store):
    """Has every change of the database been exported?"""
    state = load_state(store)
    return state is not None and state.get("changes") == store.changes()


# ---------- writing the workbooks ----------------------------

def _snapshot(store):
    """Every row of both books, and the change counter they belong to, read
    while no write can happen in between."""
    import fsr_sqlite_store as sq
    with store._lock:
        return {
            "changes": store.changes(),
            sq.MAIN: (store._headers(sq.MAIN),
                      {s: store._sheet_rows(sq.MAIN, s)
                       for s in sq.MAIN_SHEETS}),
            sq.BOOK: (store._headers(sq.BOOK),
                      {s: store._sheet_rows(sq.BOOK, s)
                       for s in sq.BOOK_SHEETS}),
        }


def _save(wb, path):
    path = Path(path)
    temp = path.with_name(path.stem + ".saving.tmp")
    try:
        wb.save(temp)
        storage.replace_file(temp, path)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


class _Rows:
    """Writes rows one below the other, as fsr_storage.append_row() does -
    the same cells and number formats - but counts the rows itself:
    append_row() asks the sheet for its last row each time, which costs
    more with every row (fine for one save, far too slow for 100,000 rows
    of an export)."""

    def __init__(self, ws):
        self.ws = ws
        self.row_no = 1                 # the heading row

    def append(self, values, formats=None):
        self.row_no += 1
        for col_index, value in enumerate(values, start=1):
            storage.put_cell(self.ws, self.row_no, col_index, value)
        storage.apply_formats(self.ws, self.row_no, formats)


def main_workbook(headers, rows, database_id=None):
    """Field_Survey_Reports.xlsx as fsr_storage.write_reports_to_excel()
    makes it (plus the database's id in its document properties)."""
    wb = storage.Workbook()
    wb.remove(wb.active)
    if database_id:
        import fsr_db_location
        fsr_db_location.stamp_identity(wb, database_id)
    price_formats = {
        4 + storage.ITEM_HEADERS.index(header): "#,##0.00"
        for header in storage.MONEY_ITEM_HEADERS
    }
    for name, (table_name, columns) in storage.EXCEL_SHEETS.items():
        ws = wb.create_sheet(name)
        ws.append(columns)
        out = _Rows(ws)
        if name == "Reports":
            for values in headers:
                out.append([values.get(c) for c in columns],
                           storage.REPORT_FORMATS)
        else:
            formats = price_formats if name == "Item List" else None
            for row in rows[name]:
                out.append(list(row), formats)
        storage.finalize_sheet(ws, table_name, columns)
    return wb


def withdrawal_workbook(headers, rows, database_id=None):
    """Withdrawal_Reports.xlsx as fsr_withdrawal.write_withdrawal_report()
    makes it (plus the database's id in its document properties)."""
    wb = storage.Workbook()
    wb.remove(wb.active)
    if database_id:
        import fsr_db_location
        fsr_db_location.stamp_identity(wb, database_id)
    for name, (table_name, columns) in fsr_withdrawal.WITHDRAWAL_SHEETS.items():
        ws = wb.create_sheet(name)
        ws.append(columns)
        out = _Rows(ws)
        if name == fsr_withdrawal.HEADER_SHEET:
            for values in headers:
                out.append([values.get(c) for c in columns],
                           storage.REPORT_FORMATS)
        else:
            for row in rows[name]:
                out.append(list(row))
        storage.finalize_sheet(ws, table_name, columns)
    return wb


def write_export(store, targets=None, force=False):
    """Write both workbooks from the database. Raises ChangedOutside, and
    writes nothing, when an exported file was changed since the program
    wrote it (unless `force`). `targets`: {"main": path, "withdrawal":
    path} to write elsewhere (the migration's check); then no note is kept.
    Returns the change counter written."""
    import fsr_sqlite_store as sq
    keep_note = targets is None
    targets = targets or export_paths(store)
    if keep_note and not force:
        changed = changed_outside(store)
        if changed:
            raise ChangedOutside(changed)
    snap = _snapshot(store)
    notes = dict((load_state(store) or {}).get("files") or {}) \
        if keep_note else {}
    database_id = store.database_id

    main_headers, main_rows = snap[sq.MAIN]
    _save(main_workbook(main_headers, main_rows, database_id),
          targets["main"])
    if keep_note:
        notes["main"] = file_note(targets["main"])

    book_headers, book_rows = snap[sq.BOOK]
    # The Withdrawal workbook exists once there is a PO-linked report (as
    # before); one that exists already is kept up to date.
    if book_headers or Path(targets["withdrawal"]).exists():
        _save(withdrawal_workbook(book_headers, book_rows, database_id),
              targets["withdrawal"])
        if keep_note:
            notes["withdrawal"] = file_note(targets["withdrawal"])
    if keep_note:
        save_state(store, snap["changes"], notes)
    return snap["changes"]
