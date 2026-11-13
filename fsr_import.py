"""Import Master Data: bring the reports an inspector sent from the Android
app into the Excel data file.

The file (FSR_Master_Data_*.json) holds every completed report of one phone.
Phones number their reports independently, so a report is recognised by
device + phone Control #, recorded in a small ledger beside the workbook:

  * not seen before  -> added; if its number is taken on this PC it gets the
                        next free number (the existing report is untouched)
  * seen, unchanged  -> nothing happens, so sending a file again is safe
  * changed on the phone -> the PC copy is updated, unless the PC copy was
                        also edited or was deleted here: then it is left alone
                        and reported

How it is written (Phase 3)
  1. The whole file is checked (read_master_file) and every report's fate
     and number are worked out from ONE read of the workbook - nothing is
     changed yet.
  2. One backup copy of the workbook.
  3. With a save record (fsr_save_journal): the reports go on record
     together, as one batch, before the first write.
  4. ONE write of the workbook for all of them. The file is replaced as a
     whole, so either every report is in it or none.
  5. Their incident files, other Item List forms, the import record (the
     ledger below), PO_Master / Withdrawn_Item - and MySQL, which the
     program then sends in the background.
  Cut off before 4: nothing was imported, and the next start says so (the
  batch is dropped from the record). Cut off after 4: the next start
  finishes 5 and says that the import was completed.
"""
import copy
import json
import shutil
from datetime import datetime
from pathlib import Path

import fsr_storage as storage
import fsr_paths

FORMAT = "fsr-master-data"
SUPPORTED_VERSION = 1
LIST_KEYS = ("consignee_list", "supplier_list", "broker_list", "hauler_list",
             "location_list", "destination_list", "country_of_origin_list")
REQUIRED_SECTIONS = ("general_information", "inspection_schedule",
                     "transport_details", "documents_used")


class MasterDataError(ValueError):
    """The chosen file is not a usable master data file."""


def read_master_file(path):
    """Read and check the whole file before anything is changed."""
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError) as error:
        raise MasterDataError(f"The file could not be read:\n{error}") from error

    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise MasterDataError(
            "This is not a Field Survey Report master data file.")
    if data.get("version") != SUPPORTED_VERSION:
        raise MasterDataError(
            f"This file has version {data.get('version')}, and this program "
            f"reads version {SUPPORTED_VERSION}. Please update the program.")
    if not str(data.get("device_id") or "").strip():
        raise MasterDataError("The file does not say which phone it came from.")

    reports = data.get("reports")
    if not isinstance(reports, list):
        raise MasterDataError("The file has no list of reports.")
    for number, report in enumerate(reports, start=1):
        problem = _report_problem(report)
        if problem:
            raise MasterDataError(
                f"Report {number} in the file cannot be used: {problem}.")
    return data


def _report_problem(report):
    if not isinstance(report, dict):
        return "it is not a report"
    if not str(report.get("control_no") or "").strip():
        return "it has no Control #"
    for section in REQUIRED_SECTIONS:
        if not isinstance(report.get(section), dict):
            return f"it has no {section}"
    for key in ("declared_goods", "item_lists", "other_important_remarks",
                "findings_and_remarks"):
        if not isinstance(report.get(key), list):
            return f"it has no {key}"
    if not report["general_information"].get("so_number"):
        return f"{report['control_no']} has no SO Number"
    if not isinstance(storage.parse_date(report["general_information"].get(
            "inspection_date")), datetime):
        return f"{report['control_no']} has an invalid Inspection Date"
    return None


# ---------- ledger ------------------------------------------

def ledger_path(excel_path):
    excel_path = Path(excel_path)
    return (fsr_paths.json_dir_for_workbook(excel_path)
            / f"{excel_path.stem}_imported_reports.json")


def load_ledger(excel_path):
    path = ledger_path(excel_path)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as file:
            ledger = json.load(file)
    except ValueError as error:
        # Guessing would risk duplicates or overwriting, so stop instead.
        raise MasterDataError(
            f"The import record could not be read:\n{path}\n{error}") from error
    return ledger if isinstance(ledger, dict) else {}


def imported_inspector(excel_path, control_no):
    """The phone inspector who prepared this report ("" if not imported)."""
    try:
        ledger = load_ledger(excel_path)
    except (MasterDataError, OSError):
        return ""
    for entry in ledger.values():
        if storage.same_key(entry.get("control"), control_no):
            return str(entry.get("inspector") or "")
    return ""


def _last_saved_by_control(excel_path):
    """{Control #: its Last Saved cell}; empty when there is no file yet.
    Control #s are found without regard to letter case."""
    if not Path(excel_path).exists():
        return storage.ControlKeyed()
    wb = storage.open_workbook_for_read(excel_path)
    if "Reports" not in wb.sheetnames:
        return storage.ControlKeyed()
    return storage.ControlKeyed({
        str(row["Control #"]).strip(): str(row.get("Last Saved"))
        for row in storage.report_dicts(wb["Reports"])
        if row.get("Control #")
    })


def _ledger_key(ledger, device, phone_no):
    """The ledger key of this phone report: the key already in the ledger
    when its Control # differs only by letter case, else a new one."""
    key = f"{device}|{phone_no}"
    if key in ledger:
        return key
    wanted = storage.control_key(phone_no)
    for existing in ledger:
        owner, _, control = existing.rpartition("|")
        if owner == device and storage.control_key(control) == wanted:
            return existing
    return key


# ---------- import ------------------------------------------

def _renumbered(report, old, new):
    """Receiving Refs carry the Control #, so they follow a new number."""
    prefix = f"RCV-{old}-"
    for item_list in report["item_lists"]:
        for row in item_list.get("rows", []):
            ref = str(row.get("Receiving Ref") or "")
            if ref.casefold().startswith(prefix.casefold()):
                row["Receiving Ref"] = f"RCV-{new}-" + ref[len(prefix):]
    report["control_no"] = new


def write_side_files(excel_path, control, report):
    """The incident file and the other Item List forms of one report."""
    if report.get("cargo_condition") == storage.CONDITION_BAD:
        storage.save_incident_data(
            excel_path, control, report["general_information"]["so_number"],
            report.get("incident_reports") or [])
    else:
        storage.delete_incident_data(excel_path, control)
    storage.save_other_item_forms(
        excel_path, control, report.get("other_item_forms") or {})


def record_imports(excel_path, entries):
    """Add {ledger key: entry} to the import record - one write."""
    if not entries:
        return
    ledger = load_ledger(excel_path)
    ledger.update(entries)
    storage.write_json_atomic(ledger_path(excel_path), ledger)


def _quiet(*args, **kwargs):
    pass


def import_master_data(excel_path, data, on_saved=None, journal=None,
                       stores=None, mysql=False, progress=None):
    """Bring the reports of a read_master_file() result into the workbook
    (see the module text for the order of the writes).

    `journal` / `stores` (fsr_save_journal): the import is put on record
    first and every step is ticked off there; with mysql=True the records
    keep their MySQL step open for the background sender. Without a
    journal the same writes happen, only not on record (tests, tools).
    progress(text, done, total) is called from the working thread.
    on_saved(report) runs after the import for every saved report.
    Returns a summary dictionary."""
    import fsr_save_journal as journal_module

    progress = progress or _quiet
    excel_path = Path(excel_path)
    device = str(data["device_id"]).strip()
    inspector = str(data.get("inspector") or "").strip()
    ledger = load_ledger(excel_path)
    summary = {"added": [], "updated": [], "unchanged": [], "renumbered": [],
               "conflicts": [], "deleted_here": [], "backup": None,
               "saved_reports": []}

    def backup_once():
        if summary["backup"] is None and excel_path.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = excel_path.with_name(
                f"{excel_path.stem}_before_import_{stamp}{excel_path.suffix}")
            shutil.copy2(excel_path, target)
            summary["backup"] = str(target)

    total = len(data["reports"])
    progress(f"Checking {total} report(s) against the Excel file ...", 0,
             total)
    saved = _last_saved_by_control(excel_path)
    # Numbers of the PO-linked Withdrawal workbook: never reused by an import.
    elsewhere = storage.withdrawal_control_numbers(excel_path)
    taken_elsewhere = {storage.control_key(n) for n in elsewhere}
    # numbers given to new reports of this file
    assigned = storage.ControlKeyed()
    plan = []          # (report, editing, ledger key, phone #, phone saved)
    planned_keys = {}  # ledger key -> its place in plan

    for original in data["reports"]:
        # A copy: renumbering must never change the caller's data, so the same
        # data can be imported again (and its master lists read) unchanged.
        report = copy.deepcopy(original)
        phone_no = str(report["control_no"]).strip()
        key = _ledger_key(ledger, device, phone_no)
        phone_saved = str(report.get("last_saved") or "")
        if key not in planned_keys:
            # the same phone number in another letter case, earlier in
            # this file, is the same report
            for planned in planned_keys:
                owner, _, number = planned.rpartition("|")
                if owner == device and storage.control_key(
                        number) == storage.control_key(phone_no):
                    key = planned
                    break
        if key in planned_keys:
            # The same phone report twice in one file: as before, the later
            # one is what the PC keeps - one report, not two.
            index = planned_keys[key]
            earlier, editing = plan[index][0], plan[index][1]
            _renumbered(report, phone_no, earlier["control_no"])
            plan[index] = (report, editing, key, phone_no, phone_saved)
            continue
        entry = ledger.get(key)

        if entry is not None:
            local = entry["control"]
            if phone_saved == entry.get("phone_saved"):
                summary["unchanged"].append(local)
                continue
            if local not in saved:
                summary["deleted_here"].append(local)
                continue
            if saved[local] != entry.get("pc_saved"):
                summary["conflicts"].append(local)
                continue
            editing = True
            local = saved.name(local)       # as it is spelled in the workbook
            _renumbered(report, phone_no, local)
        else:
            local = phone_no
            editing = False
            if local in saved or local in assigned or \
                    storage.control_key(local) in taken_elsewhere:
                # The report keeps the initials of the inspector who made it.
                local = storage.next_control_number(
                    [*saved, *elsewhere, *assigned],
                    storage.control_initials_of(phone_no))
                _renumbered(report, phone_no, local)
                summary["renumbered"].append((phone_no, local))
        assigned[local] = True
        planned_keys[key] = len(plan)
        plan.append((report, editing, key, phone_no, phone_saved))

    if not plan:
        return summary

    backup_once()
    # One Last Saved time for the whole import, chosen before the write:
    # it is how the record recognises the write afterwards.
    now = datetime.now()
    stamp = now.replace(microsecond=now.microsecond // 1000 * 1000)
    imported = now.isoformat(timespec="seconds")
    records = None
    if journal is not None:
        records = journal.begin_batch(
            [(report, editing,
              journal_module.steps_for(report, False, mysql)
              + ["import_ledger"],
              {"import": {"key": key, "entry": {
                  "phone_control": phone_no, "inspector": inspector,
                  "phone_saved": phone_saved, "pc_saved": str(stamp),
                  "imported": imported}}})
             for report, editing, key, phone_no, phone_saved in plan],
            now=stamp)

    progress(f"Writing {len(plan)} report(s) into the Excel file ...", 0,
             len(plan))
    write = (lambda: storage.write_reports_to_excel(
        excel_path, [(report, editing, stamp)
                     for report, editing, *_ in plan]))
    try:
        if stores is not None and stores.guard is not None:
            with stores.guard.local_write():
                results = write()
        else:
            results = write()
    except BaseException:
        # The workbook is replaced in one go: when the write fails, nothing
        # of this import is in it, so its records go too.
        if records is not None:
            try:
                journal.discard_batch(records)
            except Exception:
                pass
        raise

    entries = {}
    for number, ((report, editing, key, phone_no, phone_saved), result) in \
            enumerate(zip(plan, results), start=1):
        control = result["control"]
        report["control_no"] = control
        progress(f"Writing the files of {control} ...", number, len(plan))
        write_side_files(excel_path, control, report)
        entries[key] = {
            "control": control, "phone_control": phone_no,
            "inspector": inspector, "phone_saved": phone_saved,
            "pc_saved": str(stamp), "imported": imported}
        summary["updated" if editing else "added"].append(control)
        summary["saved_reports"].append(report)
    progress("Updating the record of imported reports ...", len(plan),
             len(plan))
    record_imports(excel_path, entries)

    lists_failed = None
    if records is not None and any(
            "item_lists" in record["steps"] for record in records):
        progress("Updating PO_Master and Withdrawn_Item ...", len(plan),
                 len(plan))
        try:
            stores.item_lists(records[0])
        except Exception as error:      # finished at the next save / start
            lists_failed = error
    if records is not None:
        for record, result in zip(records, results):
            record["control"] = record["data"]["control_no"] = \
                result["control"]
            record["data"] = copy.deepcopy(record["data"])
            record["editing"] = True
            record["stamp"] = record["stamp_planned"]
            for step in ("workbook", "incidents", "item_forms",
                         "import_ledger"):
                record["steps"][step] = journal_module.DONE
            if "item_lists" in record["steps"] and lists_failed is None:
                record["steps"]["item_lists"] = journal_module.DONE
            if lists_failed is not None:
                record["errors"]["item_lists"] = str(lists_failed)
        journal.save_many(records)
    summary["item_lists_failed"] = lists_failed

    if on_saved is not None:
        for report in summary["saved_reports"]:
            on_saved(report)
    return summary


def new_master_names(data, master_lists):
    """{list key: names in the file but not in this PC's lists}."""
    result = {}
    for key in LIST_KEYS:
        known = {str(n).strip().casefold() for n in master_lists.get(key, [])}
        for name in (data.get("master_lists") or {}).get(key) or []:
            name = str(name).strip()
            if name and name.casefold() not in known:
                known.add(name.casefold())
                result.setdefault(key, []).append(name)
    return result


def add_master_names(new_names, master_lists):
    """Add in place, so the open comboboxes see the names too."""
    for key, names in new_names.items():
        target = master_lists.setdefault(key, [])
        target.extend(names)
        target.sort(key=str.casefold)
