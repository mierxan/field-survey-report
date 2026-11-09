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
    """{Control #: its Last Saved cell}; {} when there is no file yet."""
    if not Path(excel_path).exists():
        return {}
    wb = storage.open_workbook_for_read(excel_path)
    if "Reports" not in wb.sheetnames:
        return {}
    return {
        str(row["Control #"]).strip(): str(row.get("Last Saved"))
        for row in storage.report_dicts(wb["Reports"])
        if row.get("Control #")
    }


# ---------- import ------------------------------------------

def _renumbered(report, old, new):
    """Receiving Refs carry the Control #, so they follow a new number."""
    prefix = f"RCV-{old}-"
    for item_list in report["item_lists"]:
        for row in item_list.get("rows", []):
            ref = str(row.get("Receiving Ref") or "")
            if ref.startswith(prefix):
                row["Receiving Ref"] = f"RCV-{new}-" + ref[len(prefix):]
    report["control_no"] = new


def _write(excel_path, report, editing):
    result = storage.write_report_to_excel(excel_path, report, editing)
    control = result["control"]
    if report.get("cargo_condition") == storage.CONDITION_BAD:
        storage.save_incident_data(
            excel_path, control, report["general_information"]["so_number"],
            report.get("incident_reports") or [])
    else:
        storage.delete_incident_data(excel_path, control)
    storage.save_other_item_forms(
        excel_path, control, report.get("other_item_forms") or {})
    return control


def import_master_data(excel_path, data, on_saved=None):
    """Bring the reports of a read_master_file() result into the workbook.

    The workbook is copied once before its first change. The ledger is written
    after every report, so if a save fails (say the workbook is open in Excel)
    the import can simply be repeated. on_saved(report) runs after each saved
    report (the MySQL copy). Returns a summary dictionary.
    """
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

    saved = _last_saved_by_control(excel_path)
    # Numbers of the PO-linked Withdrawal workbook: never reused by an import.
    taken_elsewhere = set(storage.withdrawal_control_numbers(excel_path))

    for original in data["reports"]:
        # A copy: renumbering must never change the caller's data, so the same
        # data can be imported again (and its master lists read) unchanged.
        report = copy.deepcopy(original)
        phone_no = str(report["control_no"]).strip()
        key = f"{device}|{phone_no}"
        phone_saved = str(report.get("last_saved") or "")
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
            _renumbered(report, phone_no, local)
        else:
            local = phone_no
            editing = False
            if local in saved or local in taken_elsewhere:
                # The report keeps the initials of the inspector who made it.
                local = storage.next_control_number(
                    [*saved, *taken_elsewhere],
                    storage.control_initials_of(phone_no))
                _renumbered(report, phone_no, local)
                summary["renumbered"].append((phone_no, local))

        backup_once()
        control = _write(excel_path, report, editing)
        saved = _last_saved_by_control(excel_path)
        ledger[key] = {
            "control": control,
            "phone_control": phone_no,
            "inspector": inspector,
            "phone_saved": phone_saved,
            "pc_saved": saved.get(control),
            "imported": datetime.now().isoformat(timespec="seconds"),
        }
        storage.write_json_atomic(ledger_path(excel_path), ledger)
        summary["updated" if editing else "added"].append(control)
        summary["saved_reports"].append(report)
        if on_saved is not None:
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
