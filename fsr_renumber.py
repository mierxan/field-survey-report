"""Give a saved report another Control # everywhere on this PC.

Used when a report that was numbered while MySQL was away turns out to
carry a number another copy of the program has used in MySQL, and the user
chooses "save mine under the next free number". The report is renumbered

  * in the main workbook and the Withdrawal workbook: its own rows, the
    "Source Control #" of withdrawal lines that point at it, and every
    Receiving Ref built from its number (RCV-<number>-...),
  * in its incident file and its other-Item-List-forms file (renamed, and
    the number inside),
  * in the import ledger and in the warehouse side file (Bad Order case
    status, reconciliation decisions),
  * in PO_Master.xlsx and Withdrawn_Item.xlsx (rebuilt).

Printed report forms already made under the old number are left as they
are; print the report again to get forms with the new number.
"""
import json
import os  # noqa: F401 - os.replace, via fsr_storage.replace_file
from pathlib import Path

import fsr_paths
import fsr_storage as storage

REFERENCE_HEADERS = ("Source Control #",)
REF_HEADER = "Receiving Ref"


class RenumberError(ValueError):
    """The report could not be renumbered; nothing was changed."""


def local_numbers(excel_path):
    numbers = [entry[0] for entry in storage.list_saved_reports(excel_path)]
    return numbers + list(storage.withdrawal_control_numbers(excel_path))


def next_free(excel_path, old, also_taken=()):
    """The next number free on this PC and not in `also_taken` (MySQL's
    numbers), keeping the initials of `old`."""
    return storage.next_control_number(
        [*local_numbers(excel_path), *also_taken, old],
        storage.control_initials_of(old))


def _swap_ref(value, old, new):
    text = str(value or "")
    prefix = f"RCV-{old}-"
    if text.casefold().startswith(prefix.casefold()):
        return f"RCV-{new}-" + text[len(prefix):]
    return value


def _renumber_workbook(path, old, new):
    """Returns the number of cells changed (0 = file not written)."""
    if not Path(path).exists():
        return 0
    wb = storage.load_workbook(path)
    changed = 0
    for ws in wb.worksheets:
        header = [cell.value for cell in ws[1]] if ws.max_row else []
        if not header:
            continue
        key_columns = [1] if str(header[0] or "").strip() == "Control #" \
            else []
        key_columns += [index + 1 for index, name in enumerate(header)
                        if name in REFERENCE_HEADERS]
        ref_columns = [index + 1 for index, name in enumerate(header)
                       if name == REF_HEADER]
        for row in ws.iter_rows(min_row=2):
            for column in key_columns:
                cell = row[column - 1] if column <= len(row) else None
                if cell is not None and cell.value is not None and \
                        storage.same_key(cell.value, old):
                    cell.value = new
                    changed += 1
            for column in ref_columns:
                cell = row[column - 1] if column <= len(row) else None
                if cell is not None and cell.value:
                    swapped = _swap_ref(cell.value, old, new)
                    if swapped != cell.value:
                        cell.value = swapped
                        changed += 1
    if changed:
        temp = Path(path).with_name(Path(path).stem + ".saving.tmp")
        try:
            wb.save(temp)
            storage.replace_file(temp, path)
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass
    return changed


def _walk_refs(value, old, new):
    if isinstance(value, dict):
        return {k: _walk_refs(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk_refs(v, old, new) for v in value]
    if isinstance(value, str):
        if storage.same_key(value, old):
            return new
        if value.casefold().startswith(f"{old}/".casefold()):
            return new + value[len(old):]       # "<number>/1/2" subject ids
        return _swap_ref(value, old, new)
    return value


def _move_json(old_path, new_path, old, new):
    if not old_path.exists():
        return False
    data = json.loads(old_path.read_text(encoding="utf-8"))
    data = _walk_refs(data, old, new)
    new_path.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json_atomic(new_path, data)
    if old_path.resolve() != new_path.resolve():
        old_path.unlink()
    return True


def _rewrite_json(path, old, new):
    if not path.exists():
        return False
    before = json.loads(path.read_text(encoding="utf-8"))
    after = _walk_refs(before, old, new)
    if after != before:
        storage.write_json_atomic(path, after)
        return True
    return False


def renumber_report(excel_path, old, new, required_root=None, store=None):
    """Renumber one report on this PC. Returns what was touched. `store`:
    the SQLite store, when the reports are in its database."""
    excel_path = Path(excel_path)
    old, new = str(old).strip(), str(new).strip()
    if not new or storage.same_key(old, new):
        raise RenumberError("The new Control # must differ from the old one.")
    present = (local_numbers(excel_path) if store is None
               else store.control_numbers())
    if not any(storage.same_key(n, old) for n in present):
        raise RenumberError(f"Report {old} is not in this PC's workbooks.")
    if any(storage.same_key(n, new) for n in present):
        raise RenumberError(f"Control # {new} is already used on this PC.")

    touched = {"cells": 0, "files": []}
    book = fsr_paths.withdrawal_workbook_path(excel_path, required_root)
    # PO_Master / Withdrawn_Item keep rows of reports they do not find in
    # the workbook, so the old number is changed there too before they are
    # rebuilt below.
    lists = [excel_path.with_name(fsr_paths.PO_MASTER_NAME),
             excel_path.with_name(fsr_paths.WITHDRAWN_ITEM_NAME)]
    if store is not None:
        cells = store.renumber_rows(old, new)
        if cells:
            touched["cells"] += cells
            touched["files"].append(store.db_path.name)
    for path in ((*lists,) if store is not None
                 else (excel_path, book, *lists)):
        cells = _renumber_workbook(path, old, new)
        if cells:
            touched["cells"] += cells
            touched["files"].append(Path(path).name)

    if _move_json(storage.incident_json_path(excel_path, old),
                  storage.incident_json_path(excel_path, new), old, new):
        touched["files"].append("incident file")
    if _move_json(storage.other_item_forms_path(excel_path, old),
                  storage.other_item_forms_path(excel_path, new), old, new):
        touched["files"].append("item forms file")

    import fsr_import
    if _rewrite_json(fsr_import.ledger_path(excel_path), old, new):
        touched["files"].append("import ledger")
    # accepted and waiting revisions follow the number; the import history
    # is never rewritten (its events keep the number they had then)
    if _rewrite_json(fsr_import.review_path(excel_path), old, new):
        touched["files"].append("import review")
    from warehouse import store
    if _rewrite_json(store.side_file_path(excel_path), old, new):
        touched["files"].append("warehouse side file")

    import fsr_withdrawal
    try:
        if store is not None:
            store.rebuild_item_lists()
        else:
            fsr_withdrawal.sync_item_lists(excel_path)
        touched["files"].append("PO_Master / Withdrawn_Item")
    except Exception as error:          # rebuilt again at the next save
        touched["lists_error"] = str(error)
    return touched
