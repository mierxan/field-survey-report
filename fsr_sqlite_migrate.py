"""Moving the reports of a workbook into its SQLite database (Phase 5) -
once, automatically, at the first start of the new version (and when
"Change Excel File" picks a workbook that has not moved yet). The Owner
and the User edition do the same.

migrate():
  1. Everything is copied, unchanged, to Backups\\before_sqlite_<date>\\
     beside the workbook: both workbooks, PO_Master, Withdrawn_Item and the
     JSON files (incidents, item forms, records).
  2. Every row of every sheet is copied into a new database, as its cells
     hold it, in the order of the sheet.
  3. Every report is read from the workbook and from the database and the
     two are compared field by field; so are the saved-reports lists, the
     search indexes, the Last Saved times and the Control #s. The export
     is written to a temporary folder and compared with the workbook row by
     row.
  4. Only when everything is equal is the database given its name - from
     then on the program uses it. If anything differs, the database is put
     aside (".not_used_<time>"), the program keeps using the workbook as
     before, and the user is told plainly what differed.

reconcile(): at start, an export that was changed outside the program.
use_excel_again(): the way back.
"""
import contextlib
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

import fsr_db_location as location
import fsr_paths
import fsr_sqlite_export as export
import fsr_sqlite_store as sq
import fsr_storage as storage
import fsr_withdrawal

log = logging.getLogger("fsr")

BACKUP_FOLDER = "Backups"
SHOWN_DIFFERENCES = 15


class MigrationRefused(Exception):
    """The workbook holds something the database would not keep."""


class Result:
    """status: "active" (already moved), "new" (no workbook yet: an empty
    database), "migrated", "kept" (it stays on the workbook; `message`
    says why), "skipped" (an earlier attempt failed and the workbook has
    not changed since)."""

    def __init__(self, status, message="", **details):
        self.status = status
        self.message = message
        self.details = details

    def __repr__(self):
        return f"Result({self.status!r}, {self.message[:60]!r})"


def failure_path(excel_path):
    excel_path = Path(excel_path)
    return (fsr_paths.json_dir_for_workbook(excel_path)
            / f"{excel_path.stem}_sqlite_migration.json")


def _books(excel_path, required_root=None):
    main = Path(excel_path)
    return main, fsr_paths.withdrawal_workbook_path(main, required_root)


def _stats(paths):
    found = {}
    for path in paths:
        try:
            info = Path(path).stat()
        except OSError:
            continue
        found[Path(path).name] = [info.st_mtime_ns, info.st_size]
    return found


def _stamp(now):
    return now.strftime("%Y%m%d_%H%M%S")


# ---------- 1. the backup ------------------------------------------

def backup(excel_path, required_root=None, now=None):
    """Copy everything belonging to this workbook, unchanged."""
    now = now or datetime.now()
    main, book = _books(excel_path, required_root)
    base = main.parent / BACKUP_FOLDER / f"before_sqlite_{_stamp(now)}"
    folder, number = base, 1
    while True:
        try:
            folder.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:         # a second move in the same second
            number += 1
            folder = base.with_name(f"{base.name}_{number}")
    import fsr_backup
    # Each copy is checked after it is written: the same bytes as the file
    # (and a complete zip archive for a workbook). There is no database yet
    # at this point - only workbooks and JSON files are copied.
    for path in (main, book, main.with_name(fsr_paths.PO_MASTER_NAME),
                 main.with_name(fsr_paths.WITHDRAWN_ITEM_NAME)):
        if path.exists():
            fsr_backup.verified_copy(path, folder / path.name)
    json_dir = fsr_paths.json_dir_for_workbook(main)
    if json_dir.exists():
        # The JSON files only - never a workbook, a database, the printed
        # forms or earlier backups (the JSON folder may be the workbook's).
        shutil.copytree(
            json_dir, folder / "json",
            ignore=shutil.ignore_patterns(
                BACKUP_FOLDER, "*.xlsx", "*.xls", "*.pdf", "*.tmp",
                f"*{sq.DB_SUFFIX}*", "Report Forms"))
        for copied in (folder / "json").rglob("*"):
            if copied.is_file():
                fsr_backup.verify_copy(
                    json_dir / copied.relative_to(folder / "json"), copied)
    return folder


# ---------- 2. the rows of the workbooks ------------------------------

def _all_none(row):
    return all(value is None for value in row)


def _child_rows(ws, headers, label, typed=()):
    rows = []
    for number, row in enumerate(storage.sheet_rows(ws, typed), start=2):
        if row is None or _all_none(row):
            continue
        beyond = [v for v in row[len(headers):] if v is not None]
        if beyond:
            raise MigrationRefused(
                f'Row {number} of the sheet "{label}" has cells to the '
                "right of the program's columns. The export would not "
                "keep them.")
        rows.append(tuple(row[:len(headers)]))
    return rows


def _header_rows(ws, label):
    rows = []
    for number, values in enumerate(storage.report_dicts(ws), start=2):
        if _all_none(values.values()):
            continue
        if not storage.cell_text(values.get("Control #")):
            raise MigrationRefused(
                f'Row {number} of the sheet "{label}" has no Control #.')
        rows.append(values)
    return rows


_FORMULA = re.compile(rb"<(?:\w+:)?f[\s>/]")
_CELL = re.compile(rb'<(?:\w+:)?c\s[^>]*?\br="([A-Z]+[0-9]+)"')


def _sheet_files(archive):
    """{sheet XML file in the archive: sheet name}."""
    import xml.etree.ElementTree as ET
    main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel = ("{http://schemas.openxmlformats.org/officeDocument/2006/"
           "relationships}id")
    targets = {}
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for item in rels:
        target = item.get("Target", "").lstrip("/")
        targets[item.get("Id")] = (target if target.startswith("xl/")
                                   else "xl/" + target)
    names = {}
    for sheet in ET.fromstring(archive.read("xl/workbook.xml")).iter(
            main + "sheet"):
        names[targets.get(sheet.get(rel), "")] = sheet.get("name")
    return names


def _formula_cell(path):
    """The first cell holding a formula ("Sheet!B7"), or None. The program
    never writes formulas, so one was typed in Excel; the export keeps
    values only, so it would become a fixed number. (A formula is an <f>
    element of its cell in the sheet's XML: found there directly, which is
    far quicker than loading the workbook once more.)"""
    import zipfile
    with zipfile.ZipFile(path) as archive:
        for name, title in _sheet_files(archive).items():
            if name not in archive.namelist():
                continue
            data = archive.read(name)
            found = _FORMULA.search(data)
            if found:
                cells = list(_CELL.finditer(data, 0, found.start()))
                where = cells[-1].group(1).decode() if cells else "?"
                return f"{title}!{where}"
    return None


def read_rows(excel_path, required_root=None):
    """{book: (header rows, {sheet: rows})} of both workbooks, read once.
    Raises MigrationRefused for what the database would not keep."""
    main, book = _books(excel_path, required_root)
    for path in (main, book):
        if path.exists():
            found_at = _formula_cell(path)
            if found_at:
                raise MigrationRefused(
                    f"{path.name} has a formula typed into it (cell "
                    f"{found_at}). The export keeps values only, so the "
                    "formula would be lost. Move it to another file to "
                    "switch to the database.")
    found = {sq.MAIN: ([], {s: [] for s in sq.MAIN_SHEETS}),
             sq.BOOK: ([], {s: [] for s in sq.BOOK_SHEETS})}
    if main.exists():
        wb = storage.open_workbook_for_read(main)
        extra = [n for n in wb.sheetnames if n not in storage.EXCEL_SHEETS]
        if extra:
            raise MigrationRefused(
                f"{main.name} has sheets the program did not make: "
                f"{', '.join(extra)}. The export would not keep them.")
        headers = (_header_rows(wb["Reports"], "Reports")
                   if "Reports" in wb.sheetnames else [])
        rows = {}
        for sheet in sq.MAIN_SHEETS:
            rows[sheet] = (_child_rows(wb[sheet], sq.HEADERS[sq.MAIN][sheet],
                                       sheet,
                                       storage.TYPED_COLUMNS.get(sheet, ()))
                           if sheet in wb.sheetnames else [])
        found[sq.MAIN] = (headers, rows)
    if book.exists():
        wb = fsr_withdrawal._open(book, data_only=True)
        extra = [n for n in wb.sheetnames
                 if n not in fsr_withdrawal.WITHDRAWAL_SHEETS]
        if extra:
            raise MigrationRefused(
                f"{book.name} has sheets the program did not make: "
                f"{', '.join(extra)}. The export would not keep them.")
        headers = _header_rows(wb[fsr_withdrawal.HEADER_SHEET],
                               fsr_withdrawal.HEADER_SHEET)
        rows = {sheet: _child_rows(
                    wb[sheet], sq.HEADERS[sq.BOOK][sheet], sheet,
                    storage.TYPED_COLUMNS["Declared Goods"]
                    if sheet == fsr_withdrawal.GOODS_SHEET else ())
                for sheet in sq.BOOK_SHEETS}
        found[sq.BOOK] = (headers, rows)

    seen = {}
    for book_name, (headers, _) in found.items():
        for values in headers:
            key = sq.key_of(values["Control #"])
            if key in seen:
                raise MigrationRefused(
                    f"Control # {storage.cell_text(values['Control #'])} is "
                    "used by two reports.")
            seen[key] = book_name
    return found


def write_rows(db_path, found):
    """A new database holding exactly these rows (one transaction)."""
    sq.create(db_path)
    conn = sq.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for book, (headers, rows) in found.items():
            for seq, values in enumerate(headers, start=1):
                conn.execute(
                    "INSERT INTO reports VALUES (?, ?, ?, ?, ?)",
                    (book, sq.key_of(values["Control #"]),
                     storage.cell_text(values["Control #"]), seq,
                     sq.dump_header(values)))
            for sheet, sheet_rows in rows.items():
                for seq, row in enumerate(sheet_rows, start=1):
                    conn.execute(
                        "INSERT INTO lines VALUES (?, ?, ?, ?, ?)",
                        (book, sheet, seq,
                         sq.key_of(row[0]) if row else "", sq.dump_row(row)))
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('migrated_at', ?)",
                     (datetime.now().isoformat(timespec="seconds"),))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# ---------- 3. the comparison ------------------------------------------

def _diff(where, a, b, out, path=""):
    """Field-by-field differences of two values (dicts / lists / cells)."""
    if len(out) >= SHOWN_DIFFERENCES:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            if key not in a or key not in b:
                out.append(f"{where}: {path}{key} only in "
                           f"{'the database' if key in b else 'the workbook'}")
            else:
                _diff(where, a[key], b[key], out, f"{path}{key}.")
        return
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            out.append(f"{where}: {path.rstrip('.')} has {len(a)} entries in "
                       f"the workbook, {len(b)} in the database")
            return
        for index, (x, y) in enumerate(zip(a, b)):
            _diff(where, x, y, out, f"{path}{index}.")
        return
    if a != b or type(a) is not type(b):
        out.append(f"{where}: {path.rstrip('.')} is {a!r} in the workbook, "
                   f"{b!r} in the database")


def compare_stores(excel, sql):
    """Every way the program reads reports, from both stores."""
    out = []
    excel_reports = excel.read_all_reports()
    sql_reports = sql.read_all_reports()
    _diff("the reports", [r["control_no"] for r in excel_reports],
          [r["control_no"] for r in sql_reports], out)
    for report, other in zip(excel_reports, sql_reports):
        _diff(f"report {report['control_no']}", report, other, out)
        if len(out) >= SHOWN_DIFFERENCES:
            return out
    # one report at a time (the other way of reading), against the first
    for report in excel_reports:
        _diff(f"report {report['control_no']} (read alone)", report,
              sql.read_report(report["control_no"]), out)
        if len(out) >= SHOWN_DIFFERENCES:
            return out
    excel_book = excel.read_all_withdrawal_reports()
    sql_book = sql.read_all_withdrawal_reports()
    _diff("the Withdrawal reports", excel_book, sql_book, out)
    for name in ("list_reports", "search_index", "last_saved_times",
                 "control_numbers", "next_control_number",
                 "list_withdrawal_reports", "withdrawal_search_index",
                 "withdrawal_last_saved_times", "withdrawal_numbers"):
        _diff(name.replace("_", " "), getattr(excel, name)(),
              getattr(sql, name)(), out)
    return out


def compare_export(sql, found, folder):
    """The export, written to `folder` and read back, against the rows of
    the workbooks: row by row, cell by cell."""
    out = []
    targets = {"main": folder / sql.excel_path.name,
               "withdrawal": folder / fsr_paths.WITHDRAWAL_WORKBOOK_NAME}
    export.write_export(sql, targets)
    written = {}
    for book, path in ((sq.MAIN, targets["main"]),
                       (sq.BOOK, targets["withdrawal"])):
        if not path.exists():
            written[book] = ([], {s: [] for s in found[book][1]})
            continue
        wb = storage.load_workbook(path, data_only=True)
        header_sheet = sq.HEADER_SHEET[book]
        headers = [v for v in storage.report_dicts(wb[header_sheet])
                   if not _all_none(v.values())]
        rows = {sheet: [tuple(r[:len(sq.HEADERS[book][sheet])])
                        for r in storage.sheet_rows(
                            wb[sheet],
                            storage.TYPED_COLUMNS["Declared Goods"]
                            if sheet == fsr_withdrawal.GOODS_SHEET else
                            storage.TYPED_COLUMNS.get(sheet, ())
                            if book == sq.MAIN else ())
                        if not _all_none(r)]
                for sheet in found[book][1]}
        written[book] = (headers, rows)
    for book in (sq.MAIN, sq.BOOK):
        old_headers, old_rows = found[book]
        new_headers, new_rows = written[book]
        label = "Excel file" if book == sq.MAIN else "Withdrawal workbook"
        if len(old_headers) != len(new_headers):
            out.append(f"the exported {label} has {len(new_headers)} "
                       f"reports, the original {len(old_headers)}")
        for old, new in zip(old_headers, new_headers):
            # Columns the original lacks (an older file) are empty.
            for column in set(old) | set(new):
                if old.get(column) != new.get(column):
                    out.append(
                        f"the exported {label}, report "
                        f"{storage.cell_text(old.get('Control #'))}: "
                        f"{column} is {new.get(column)!r}, the original "
                        f"{old.get(column)!r}")
        for sheet, rows in old_rows.items():
            written_rows = new_rows.get(sheet, [])
            if len(rows) != len(written_rows):
                out.append(f'the exported {label}, sheet "{sheet}": '
                           f"{len(written_rows)} rows, the original "
                           f"{len(rows)}")
                continue
            for number, (old, new) in enumerate(zip(rows, written_rows),
                                                start=2):
                width = max(len(old), len(new))
                old = tuple(old) + (None,) * (width - len(old))
                new = tuple(new) + (None,) * (width - len(new))
                # the same numbers - and shown the same way (as typed)
                if old != new or [getattr(v, "typed", None) for v in old] \
                        != [getattr(v, "typed", None) for v in new]:
                    out.append(f'the exported {label}, sheet "{sheet}", '
                               f"row {number}: {new!r}, the original "
                               f"{old!r}")
        if len(out) >= SHOWN_DIFFERENCES:
            break
    return out[:SHOWN_DIFFERENCES]


@contextlib.contextmanager
def _read_once(paths):
    """While migrating, each of these workbooks is loaded once and the
    loaded copy is used by every read of the comparison (they cannot change
    meanwhile: the window waits for the migration). Other files are read as
    usual."""
    wanted = {str(Path(p).resolve()).casefold() for p in paths}
    loaded = {}
    real = storage.load_workbook

    def load(filename, *args, **kwargs):
        key = str(Path(filename).resolve()).casefold()
        # Reads only (data_only=True): a write loads its own copy.
        if key not in wanted or args or not kwargs.get("data_only") \
                or kwargs.get("read_only"):
            return real(filename, *args, **kwargs)
        cache = (key, tuple(sorted(kwargs.items())))
        if cache not in loaded:
            loaded[cache] = real(filename, **kwargs)
        return loaded[cache]

    storage.load_workbook = load
    fsr_withdrawal.load_workbook = load
    try:
        yield
    finally:
        storage.load_workbook = real
        fsr_withdrawal.load_workbook = real


# ---------- 4. taking it into use -----------------------------------------

def _guarded(excel_path, work):
    """Do work() as a write the MySQL guard is told about (when MySQL is
    used): a ledger that was current stays current - for the database as
    it is afterwards."""
    import fsr_mysql_guard
    guard = fsr_mysql_guard.Guard(None, excel_path)
    if guard.path.exists():
        with guard.local_write():
            return work()
    return work()


def _activate(temp, db_path, excel_path):
    """Give the database its name in Local AppData and record it (its own
    meta and databases.json). Returns its id."""
    database_id = sq.read_meta(temp, "database_id") or location.new_id()

    def work():
        sq.write_meta(temp, {"database_id": database_id,
                             "workbook": Path(excel_path).resolve()})
        Path(temp).replace(db_path)
        location.register(db_path, excel_path, database_id)
    _guarded(excel_path, work)
    return database_id


def _set_aside(store, label, now):
    """Rename the database next to itself (kept, never deleted) and forget
    it: the workbook is then used without it."""
    aside = store.db_path.with_name(
        f"{store.db_path.name}.{label}_{_stamp(now)}")

    def work():
        store.db_path.replace(aside)
        location.forget(store.db_path)
    _guarded(store.excel_path, work)
    export.drop_state(store)
    return aside


def _quiet(*args, **kwargs):
    pass


# ---------- a database in the wrong place, or a workbook in a new one ------

def move_to_local(excel_path, required_root=None, now=None, progress=None):
    """A database next to the workbook - where the first Phase 5 builds put
    it, possibly in a folder OneDrive synchronises - moves to Local AppData:
    copied with SQLite's backup method, checked, every report compared;
    then the old file is renamed ".moved_to_local_<time>" (kept). If any of
    that fails, it is used where it is and the move is tried again at the
    next start."""
    now = now or datetime.now()
    progress = progress or _quiet
    excel_path = Path(excel_path)
    legacy = location.legacy_db_path(excel_path)
    synced = location.sync_tool(legacy.parent)
    problem = location.folder_problem(location.database_dir())
    if problem:
        return Result("kept_legacy",
                      f"The reports database next to the Excel file could "
                      f"not be moved: {problem}. It is used where it is.")
    target = location.default_db_path(excel_path)
    temp = target.with_name(target.name + ".moving")
    old = sq.SqliteStore(excel_path, required_root, db_path=legacy)
    try:
        if temp.exists():
            temp.unlink()
        progress("Copying the reports database to this PC's Local AppData "
                 "...")
        target.parent.mkdir(parents=True, exist_ok=True)
        old.copy_to(temp)                       # SQLite backup + check
        progress("Comparing every report, field by field ...")
        differences = compare_stores(old, sq.SqliteStore(
            excel_path, required_root, db_path=temp))
        if differences:
            raise MigrationRefused("the copy was not the same: "
                                   + "; ".join(differences[:3]))
        aside = legacy.with_name(
            f"{legacy.name}.moved_to_local_{_stamp(now)}")
        database_id = (sq.read_meta(legacy, "database_id")
                       or location.new_id())

        def work():
            sq.write_meta(temp, {"database_id": database_id,
                                 "workbook": excel_path.resolve()})
            temp.replace(target)
            location.register(target, excel_path, database_id)
            legacy.replace(aside)
        _guarded(excel_path, work)
    except Exception as error:
        log.exception("The database could not be moved to Local AppData")
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass
        return Result("kept_legacy",
                      "The reports database next to the Excel file could "
                      f"not be moved to this PC's Local AppData: {error}\n\n"
                      "It is used where it is for now; the move is tried "
                      "again at the next start.")
    # the note of what was exported follows the database
    moved = sq.SqliteStore(excel_path, required_root, db_path=target)
    old_note = export.legacy_state_path(excel_path)
    if old_note.exists() and not export.state_path(moved).exists():
        try:
            export.state_path(moved).write_bytes(old_note.read_bytes())
            old_note.unlink()
        except OSError:
            log.exception("The export note could not be moved")
    where = (f"in {legacy.parent}, a folder that {synced} synchronises"
             if synced else f"next to the Excel file in {legacy.parent}")
    return Result(
        "moved",
        f"The reports database was {where}. A database belongs in this "
        f"PC's Local AppData, so it was moved - after a full check, every "
        f"report compared - to:\n    {target}\nThe old file is kept as "
        f"{aside.name}; it can be deleted.", path=str(target))


def _find_by_id(database_id):
    """(database file, the workbook recorded for it) of the database with
    this id: from databases.json, else from the databases themselves."""
    hit = location.entry_for_id(database_id)
    if hit is not None:
        return hit
    folder = location.database_dir()
    if not folder.is_dir():
        return None
    for path in folder.glob("*" + sq.DB_SUFFIX):
        try:
            if sq.read_meta(path, "database_id") == database_id:
                return path, Path(sq.read_meta(path, "workbook") or "")
        except Exception:               # an unreadable file is skipped
            log.debug("%s skipped while looking for a database", path,
                      exc_info=True)
    return None


# The files beside a workbook's reports (in its JSON folder): carried along
# when the workbook is found in a new place.
_SIDE_FOLDERS = (storage.INCIDENT_FOLDER_NAME, storage.ITEM_FORM_FOLDER_NAME,
                 "MySQL Replaced")
_SIDE_FILES = ("_mysql_ledger.json", "_pending_saves.json",
               "_imported_reports.json", "_import_review.json",
               "_import_history.jsonl", "_handovers.json")


def carry_side_files(old_excel, new_excel):
    """Copy what belongs to the workbook's reports from its old JSON folder
    to the one of its new place - only what is not there yet; nothing is
    removed. Returns what was copied."""
    old_dir = fsr_paths.json_dir_for_workbook(old_excel)
    new_dir = fsr_paths.json_dir_for_workbook(new_excel)
    if not old_dir.is_dir():
        return []
    same_folder = location._key(old_dir) == location._key(new_dir)
    copied = []
    # the folders (named by Control #): only when the JSON folder changes;
    # the records named after the workbook: also when only its name changes
    for name in () if same_folder else _SIDE_FOLDERS:
        source = old_dir / name
        if not source.is_dir():
            continue
        for item in source.rglob("*"):
            if not item.is_file():
                continue
            target = new_dir / name / item.relative_to(source)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                copied.append(str(target.relative_to(new_dir)))
    for suffix in _SIDE_FILES:
        source = old_dir / f"{Path(old_excel).stem}{suffix}"
        target = new_dir / f"{Path(new_excel).stem}{suffix}"
        if source.is_file() and not target.exists():
            new_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(target.name)
    from warehouse.store import side_file_path
    source, target = side_file_path(old_excel), side_file_path(new_excel)
    if source.is_file() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target.name)
    return copied


def relink(excel_path, required_root=None):
    """A workbook with no database at its path but carrying a database's id
    (it was moved or renamed, or is chosen with Change Excel File in its new
    place): that database is used again. Returns a Result ("relinked"), or
    a note when the workbook is a COPY whose original is still in its place
    (it gets a database of its own), or None."""
    excel_path = Path(excel_path)
    database_id = location.workbook_identity(excel_path)
    if not database_id:
        return None
    found = _find_by_id(database_id)
    if found is None:
        return None
    db_path, recorded = found
    if recorded.exists() and \
            location._key(recorded) != location._key(excel_path) and \
            location.workbook_identity(recorded) == database_id:
        return (f"This Excel file is a copy of {recorded}, which is still "
                "in its place, so it gets a database of its own.")

    def work():
        sq.write_meta(db_path, {"workbook": excel_path.resolve()})
        location.register(db_path, excel_path, database_id)
    _guarded(excel_path, work)
    copied = carry_side_files(recorded, excel_path) if str(recorded) else []
    text = (f"This Excel file is in a new place:\n    {excel_path}\n"
            f"(before: {recorded}).\nIt goes on using its reports database:"
            f"\n    {db_path}")
    if copied:
        text += (f"\n\n{len(copied)} file(s) of its reports (incident texts, "
                 "item forms, records) were copied from its old JSON folder "
                 "to the new one; the old ones are left as they are.")
    return Result("relinked", text, path=str(db_path), copied=copied)


# ---------- the move -----------------------------------------------------------

def migrate(excel_path, required_root=None, now=None, progress=None):
    """Move this workbook's reports into its database. Never raises for a
    problem with the data: the Result says what happened. progress(text)
    is told each step (from the calling thread)."""
    now = now or datetime.now()
    progress = progress or _quiet
    excel_path = Path(excel_path)
    found_db = location.find_db(excel_path)
    if found_db is not None:
        problem = location.folder_problem(found_db.parent)
        if problem:
            # Local AppData itself synchronised or on a network drive: the
            # reports go back into the Excel file.
            back = use_excel_again(excel_path, required_root, now)
            return Result("returned" if back.status == "retired" else "kept",
                          f"The reports database cannot stay where it is: "
                          f"{problem}, and a database must not be in a "
                          f"synchronised folder or on a network drive.\n\n"
                          f"{back.message}")
        return Result("active")
    if location.legacy_db_path(excel_path).is_file():
        return move_to_local(excel_path, required_root, now, progress)
    try:
        main, book = _books(excel_path, required_root)
    except ValueError as error:
        return Result("kept", str(error))
    problem = location.folder_problem(location.database_dir())
    if problem:
        return Result("kept",
                      "The reports stay in the Excel file, as before: the "
                      f"folder for the reports database ({problem}) is not a "
                      "safe place for a database - it must not be in a "
                      "synchronised folder or on a network drive.")
    db_path = location.default_db_path(excel_path)
    if not main.exists() and not book.exists():
        database_id = location.new_id()          # a new PC: nothing to move
        sq.create(db_path, database_id, excel_path)
        location.register(db_path, excel_path, database_id)
        return Result("new", "A new database was created.", path=str(db_path))
    copy_note = ""
    if main.exists():
        linked = relink(excel_path, required_root)
        if isinstance(linked, Result):
            return linked
        copy_note = linked or ""

    failed = failure_path(excel_path)
    stats = _stats([main, book])
    try:
        earlier = json.loads(failed.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        earlier = None
    if isinstance(earlier, dict) and earlier.get("books") == stats:
        return Result("skipped", earlier.get("message", ""))

    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp = db_path.with_name(db_path.name + ".migrating")
    if temp.exists():
        temp.unlink()               # a migration cut off earlier

    def keep(message, differences=()):
        if temp.exists():
            aside = db_path.with_name(
                f"{db_path.name}.not_used_{_stamp(now)}")
            temp.replace(aside)
        text = message + ("\n\n" + "\n".join(differences)
                          if differences else "")
        try:
            failed.parent.mkdir(parents=True, exist_ok=True)
            storage.write_json_atomic(failed, {
                "books": stats, "message": text,
                "when": now.isoformat(timespec="seconds")})
        except OSError:
            log.exception("The migration note could not be written")
        log.warning("Stays on the workbook: %s", text)
        return Result("kept", text, differences=list(differences))

    progress("Copying the Excel files to the Backups folder ...")
    try:
        folder = backup(excel_path, required_root, now)
    except OSError as error:
        return keep(f"The backup copy could not be made or did not pass "
                    f"its check, so nothing was changed: {error}")
    read_stats = _stats([main, book])
    try:
        with _read_once([main, book]):
            progress("Reading the reports of the Excel file ...")
            found = read_rows(excel_path, required_root)
            progress("Writing the database ...")
            write_rows(temp, found)
            import fsr_store
            excel = fsr_store.ExcelStore(excel_path, required_root)
            sql = sq.SqliteStore(excel_path, required_root, db_path=temp)
            progress("Comparing every report, field by field ...")
            differences = compare_stores(excel, sql)
        if not differences:
            progress("Checking the Excel export, row by row ...")
            check = folder / "export_check"
            check.mkdir()
            try:
                differences = compare_export(sql, found, check)
            finally:
                shutil.rmtree(check, ignore_errors=True)
    except MigrationRefused as why:
        return keep(str(why))
    except PermissionError:
        return keep("The Excel file is open in another program. The move "
                    "to the database is tried again at the next start.")
    except Exception as error:
        log.exception("Migration failed")
        return keep(f"The reports could not be moved: {error}")
    if differences:
        return keep("The reports read from the database were not the same "
                    "as in the Excel file:", differences)
    if _stats([main, book]) != stats or read_stats != stats:
        # Saved in Excel (or by another copy of the program) since before
        # the backup: the database would miss that. Not taken; tried again
        # at the next start.
        return keep("The Excel file was changed while the reports were "
                    "being moved, so the move was not finished. It is tried "
                    "again at the next start; nothing was changed.")

    _activate(temp, db_path, excel_path)
    try:
        failed.unlink()
    except FileNotFoundError:
        pass
    # The Excel file is written from the database at once (the same
    # reports - checked above): from now on it carries the database's id.
    progress("Writing the Excel file from the database ...")
    store = sq.SqliteStore(excel_path, required_root, db_path=db_path)
    later = ""
    try:
        export.write_export(store, force=True)
    except PermissionError:
        later = (" The Excel file is open in another program; it is "
                 "brought up to date when it is closed.")
    except Exception:
        log.exception("The first export after the move failed")
        later = " The Excel file is brought up to date at the next save."
    counts = (len(found[sq.MAIN][0]), len(found[sq.BOOK][0]))
    return Result(
        "migrated",
        (copy_note + "\n\n" if copy_note else "")
        + f"{counts[0] + counts[1]} report(s) were moved into the reports "
        f"database:\n    {db_path}\nThe Excel file is now kept up to date as "
        f"an export.{later} Everything as it was is in {folder}.",
        reports=counts, backup=str(folder), path=str(db_path))


# ---------- an export changed outside the program -----------------------

def reconcile(excel_path, required_root=None, now=None):
    """Call at start (and when the export finds a changed file).

    * No exported file was changed outside the program: nothing to do.
    * The database has not changed since that export (for example: the
      previous version was used again on the export, or a file was edited
      in Excel), and the file was not written by ANOTHER database: the file
      holds everything the database holds plus the changes made to it, so
      it is taken as it is - the database is put aside (".replaced_<time>")
      and the workbook is moved in again, with the full backup and
      comparison.
    * Otherwise (both changed, or the file comes from another PC's
      database): the database stays; the changed file is kept beside it as
      "<name> (changed outside <time>).xlsx"; reports that are only in that
      file are added to the database (nothing is overwritten); reports that
      differ are listed - the user decides about them.
    Returns a Result ("unchanged", "taken", "merged" or a migrate() result
    status when taking it failed)."""
    now = now or datetime.now()
    excel_path = Path(excel_path)
    if not sq.is_active(excel_path):
        return Result("unchanged")
    store = sq.SqliteStore(excel_path, required_root)
    changed = export.changed_outside(store)
    if not changed:
        return Result("unchanged")
    state = export.load_state(store) or {}
    names = ", ".join(p.name for p in changed)
    mine = store.database_id
    foreign = [p for p in changed
               if location.workbook_identity(p) not in (None, mine)]

    if state.get("changes") == store.changes() and not foreign:
        aside = _set_aside(store, "replaced", now)
        result = migrate(excel_path, required_root, now)
        if result.status == "migrated":
            return Result(
                "taken",
                f"{names} was changed outside the program after it was "
                "last written. It was taken as it is now: the database was "
                f"built again from it. The previous database is kept as:\n"
                f"    {aside}", aside=str(aside))
        return result

    added, differing, problems = [], [], []
    import fsr_store
    for path in changed:
        kept = path.with_name(
            f"{path.stem} (changed outside {_stamp(now)}){path.suffix}")
        path.replace(kept)
        try:
            other = fsr_store.ExcelStore(kept, required_root)
            linked = path.name == fsr_paths.WITHDRAWAL_WORKBOOK_NAME
            theirs = (fsr_withdrawal.read_all_reports(kept) if linked
                      else other.read_all_reports())
            numbers = {sq.key_of(n) for n in store.control_numbers()}
            for report in theirs:
                report.pop("incident_error", None)
                control = report["control_no"]
                if sq.key_of(control) not in numbers:
                    if linked:
                        store.write_withdrawal_report(report, True)
                    else:
                        store.write_report(report, True)
                    added.append(control)
                else:
                    ours = (store.read_withdrawal_report(control) if linked
                            else store.read_report(control))
                    ours.pop("incident_error", None)
                    if {k: v for k, v in ours.items() if k != "item_form"} \
                            != {k: v for k, v in report.items()
                                if k != "item_form"}:
                        differing.append(control)
        except Exception as error:
            log.exception("A changed export could not be read")
            problems.append(f"{kept.name}: {error}")
    export.write_export(store, force=True)
    if foreign:
        lines = [f"{names} was written by ANOTHER copy of the program - "
                 "another reports database, for example another PC that "
                 "synchronises this folder through OneDrive. This PC's "
                 "database was kept and nothing in it was replaced; the "
                 "other file is kept beside it with \"(changed outside "
                 "...)\" in its name.",
                 "Two PCs must not use one Excel file. Share reports through "
                 "MySQL (the owner's PC) or with Export / Import Master "
                 "Data."]
    else:
        lines = [f"{names} was changed outside the program while the "
                 "database also had newer reports. The database was kept; "
                 "the changed file is kept beside it with \"(changed outside "
                 "...)\" in its name."]
    if added:
        lines.append("Reports that were only in that file were added: "
                     + ", ".join(added))
    if differing:
        lines.append("These reports differ in that file and were NOT "
                     "taken (check them by hand): " + ", ".join(differing))
    lines += problems
    return Result("merged", "\n\n".join(lines), added=added,
                  differing=differing, foreign=bool(foreign))


# ---------- the way back ---------------------------------------------------

def use_excel_again(excel_path, required_root=None, now=None):
    """Stop using the database: the export is brought up to date (it holds
    every report), then the database is put aside (".retired_<time>"). The
    program - this version or the previous one - then uses the workbook as
    before; this version moves it in again at its next start."""
    now = now or datetime.now()
    excel_path = Path(excel_path)
    if not sq.is_active(excel_path):
        return Result("unchanged", "The reports are in the Excel file "
                                   "already.")
    store = sq.SqliteStore(excel_path, required_root)
    changed = export.changed_outside(store)
    if changed:
        return Result("kept", f"{', '.join(p.name for p in changed)} was "
                              "changed outside the program. Start the "
                              "program once first, so it can decide about "
                              "that file; nothing was changed.")
    export.write_export(store)
    aside = _set_aside(store, "retired", now)
    # A failed attempt noted earlier is not a reason to skip the next one.
    try:
        failure_path(excel_path).unlink()
    except FileNotFoundError:
        pass
    return Result("retired", f"The Excel file {excel_path.name} holds every "
                             "report and is used again. The database is "
                             f"kept as:\n    {aside}", aside=str(aside))


# ---------- GO_BACK_TO_WORKBOOK.bat ----------------------------------------

STATUS, GO_BACK = "status", "go-back"
DONE, NOT_DONE, NOTHING_TO_DO = 0, 1, 3


def _status(excel_path, required_root):
    if not sq.is_active(excel_path):
        return ["The reports are kept in the Excel file:",
                f"    {excel_path}",
                "No database is in use, so there is nothing to do."
                ], NOTHING_TO_DO
    store = sq.SqliteStore(excel_path, required_root)
    lines = ["The reports are kept in the database:",
             f"    {store.db_path}",
             f"    {len(store.list_reports())} report(s), "
             f"{len(store.withdrawal_numbers())} PO-linked Withdrawal "
             "report(s).",
             "The Excel file:",
             f"    {excel_path}"]
    if export.changed_outside(store):
        lines += ["was CHANGED outside the program since the program last "
                  "wrote it.",
                  "Start the program once and close it again, so it can "
                  "decide about that file. Then run this again."]
        return lines, NOT_DONE
    lines.append("is up to date." if export.is_current(store) else
                 "is not up to date yet; it is brought up to date when you "
                 "go back.")
    return lines, DONE


def _go_back(excel_path, required_root):
    result = use_excel_again(excel_path, required_root)
    if result.status == "retired":
        return [result.message, "",
                "The previous version of the program can be used now: it "
                "opens this Excel file with every report.",
                "(This version would move the Excel file into a database "
                "again at its next start.)"], DONE
    if result.status == "unchanged":
        return [result.message], NOTHING_TO_DO
    return ["Nothing was changed:", result.message], NOT_DONE


def command(action, excel_path, required_root=None, report=None):
    """GO_BACK_TO_WORKBOOK.bat, through the program (FieldSurveyReport.exe
    --database-status / --go-back-to-workbook) or its Python: what it
    found or did, in plain words, written to `report` (a text file - the
    installed program has no console) or printed. Returns 0 (ready or
    done), 1 (not done) or 3 (nothing to do)."""
    excel_path = Path(excel_path)
    try:
        lines, code = (_go_back if action == GO_BACK else _status)(
            excel_path, required_root)
    except Exception as error:                 # said, never a traceback
        log.exception("The way back failed")
        lines, code = ["Nothing was changed. The way back stopped with "
                       "this problem:", f"    {error}"], NOT_DONE
    text = "\n".join(lines) + "\n"
    if report:
        Path(report).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return code


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="The reports database of a workbook: move it in now, "
                    "or stop using it (the way back).")
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--use-excel-again", action="store_true",
                        help="bring the export up to date and put the "
                             "database aside")
    args = parser.parse_args()
    done = (use_excel_again(args.workbook) if args.use_excel_again
            else migrate(args.workbook))
    print(f"{done.status}: {done.message}")
