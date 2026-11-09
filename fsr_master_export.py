"""Export Master Data: everything this PC holds, in ONE JSON file for the owner.

A site PC (User edition) sends this file to the owner, whose Owner edition
brings it in with Import Master Data (fsr_import.py) - into the owner's Excel
file and MySQL database - exactly like the file the Android app exports.

The file is a normal fsr-master-data file: the reports of both workbooks with
their incident text, this PC's master lists (consignees, suppliers ...), and the
Bad Order case statuses of the warehouse side file. It names this PC, so the
owner knows where it came from. Nothing here changes a report or a workbook;
the owner's import treats a repeated export as already imported.

  python fsr_master_export.py data.xlsx --device my-pc --inspector "Name" --out file.json
"""
import argparse
from datetime import datetime
from pathlib import Path

import fsr_import
import fsr_paths
import fsr_storage as storage
import fsr_withdrawal
from warehouse.store import SideStore, merge_withdrawal_reports


class MasterExportError(ValueError):
    """Something a complete export needs could not be read; no file is written."""


def _last_saved(path, sheet):
    if not Path(path).exists():
        return {}
    wb = storage.load_workbook(path, data_only=True)
    if sheet not in wb.sheetnames:
        return {}
    return {
        storage.cell_text(row["Control #"]).casefold():
            str(row.get("Last Saved") or "")
        for row in storage.report_dicts(wb[sheet]) if row.get("Control #")
    }


def _clean_lists(master_lists):
    """Only the known lists, as lists of non-empty names."""
    master_lists = master_lists or {}
    return {key: [str(n).strip() for n in master_lists.get(key) or []
                  if str(n).strip()]
            for key in fsr_import.LIST_KEYS}


def build_export(excel_path, device_id, inspector="", master_lists=None):
    """The export as a dictionary. Raises MasterExportError rather than leaving
    anything out without saying so."""
    book = fsr_paths.withdrawal_workbook_path(excel_path)
    reports = merge_withdrawal_reports(
        storage.read_all_reports(excel_path),
        fsr_withdrawal.read_all_reports(book))
    saved = {**_last_saved(excel_path, "Reports"),
             **_last_saved(book, fsr_withdrawal.HEADER_SHEET)}

    damaged = [r["incident_error"] for r in reports if r.get("incident_error")]
    if damaged:
        raise MasterExportError(
            "These incident files could not be read, so the export was stopped:"
            "\n" + "\n".join(damaged))
    for report in reports:
        report.pop("incident_error", None)
        report["last_saved"] = saved.get(report["control_no"].casefold(), "")
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
