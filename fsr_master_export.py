"""Export Master Data: everything this PC holds, in ONE JSON file for the owner.

A site PC (User edition) sends this file to the owner, whose Owner edition
brings it in with Import Master Data (fsr_import.py) - into the owner's Excel
file and MySQL database - exactly like the file the Android app exports.

The file is a normal fsr-master-data file: the reports of both workbooks with
their incident text, this PC's master lists (consignees, suppliers ...), and the
Bad Order case statuses of the warehouse side file. It names this PC, so the
owner knows where it came from. Nothing here changes a report or a workbook;
the owner's import treats a repeated export as already imported. Reports that
were handed over to or from another inspector (fsr_handover) carry their
permanent identity and revision, so the owner gets them once.

  python fsr_master_export.py data.xlsx --device my-pc --inspector "Name" --out file.json
"""
import argparse
from datetime import datetime
from pathlib import Path

import fsr_import
import fsr_storage as storage
from warehouse.store import SideStore, merge_withdrawal_reports


class MasterExportError(ValueError):
    """Something a complete export needs could not be read; no file is written."""


def _clean_lists(master_lists):
    """Only the known lists, as lists of non-empty names."""
    master_lists = master_lists or {}
    return {key: [str(n).strip() for n in master_lists.get(key) or []
                  if str(n).strip()]
            for key in fsr_import.LIST_KEYS}


def build_export(excel_path, device_id, inspector="", master_lists=None):
    """The export as a dictionary. Raises MasterExportError rather than leaving
    anything out without saying so."""
    import fsr_store
    store = fsr_store.open_store(excel_path)
    reports = merge_withdrawal_reports(store.read_all_reports(),
                                       store.read_all_withdrawal_reports())
    saved = {**store.last_saved_times(),
             **store.withdrawal_last_saved_times()}

    damaged = [r["incident_error"] for r in reports if r.get("incident_error")]
    if damaged:
        raise MasterExportError(
            "These incident files could not be read, so the export was stopped:"
            "\n" + "\n".join(damaged))
    for report in reports:
        report.pop("incident_error", None)
        report["last_saved"] = saved.get(report["control_no"].casefold(), "")
    import fsr_handover
    try:
        reports = fsr_handover.with_identity(excel_path, reports)
    except fsr_handover.HandoverError as error:
        raise MasterExportError(str(error)) from error
    try:
        statuses = SideStore(excel_path).data["case_status"]
    except ValueError as error:
        raise MasterExportError(str(error)) from error

    return {
        "format": fsr_import.FORMAT,
        "version": fsr_import.SUPPORTED_VERSION,
        "device_id": device_id,
        "inspector": inspector,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "master_lists": _clean_lists(master_lists),
        "reports": reports,
        "case_status": statuses,
    }


def write_export(excel_path, target, device_id, inspector="", master_lists=None):
    """Write the file; returns the number of reports in it."""
    data = build_export(excel_path, device_id, inspector, master_lists)
    storage.write_json_atomic(target, data)
    return len(data["reports"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook")
    parser.add_argument("--device", required=True)
    parser.add_argument("--inspector", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--master-list", help="master_list.json to include")
    args = parser.parse_args()
    lists = None
    if args.master_list:
        import json
        lists = json.loads(Path(args.master_list).read_text(encoding="utf-8"))
    count = write_export(args.workbook, args.out, args.device, args.inspector,
                         lists)
    print(f"{count} report(s) written to {args.out}")
