"""Export Master Data: everything this PC holds, in ONE JSON file for the owner.

A site PC (User edition) sends this file to the owner, whose Owner edition
brings it in with Import Master Data (fsr_import.py) - into the owner's Excel
file and MySQL database - exactly like the file the Android app exports.

The file is a normal fsr-master-data file: the reports of both workbooks with
their incident text, this PC's master lists (consignees, suppliers ...), and the
Bad Order case statuses of the warehouse side file. It names this PC, so the
owner knows where it came from. It holds every saved report, or only the
reports chosen (`controls`): the owner's import never removes a report that is
not in the file, so a file with one report only adds or updates that one.
Nothing here changes a report or a workbook;
the owner's import treats a repeated export as already imported. Reports that
were handed over to or from another inspector (fsr_handover) carry their
permanent identity and revision, so the owner gets them once.

  python fsr_master_export.py data.xlsx --device my-pc --inspector "Name" --out file.json
      [--report FSR-AB-202611-0001 ...]
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


def saved_reports(excel_path):
    """What can be exported, newest first: [(Control #, SO, inspection date,
    consignee, last saved, kind)], kind "report" (main workbook) or
    "withdrawal" (PO-linked, Withdrawal workbook). A Control # in both
    workbooks is listed once, as the Withdrawal workbook's (as exported)."""
    import fsr_store
    store = fsr_store.open_store(excel_path)
    linked = [tuple(row) + ("withdrawal",)
              for row in store.list_withdrawal_reports()]
    owned = {storage.control_key(row[0]) for row in linked}
    rows = [tuple(row) + ("report",) for row in store.list_reports()
            if storage.control_key(row[0]) not in owned] + linked
    rows.sort(key=lambda row: storage.control_sort_key(row[0]), reverse=True)
    return rows


def build_export(excel_path, device_id, inspector="", master_lists=None,
                 controls=None):
    """The export as a dictionary. `controls`: the Control #s to export (None:
    every saved report). Raises MasterExportError rather than leaving
    anything out without saying so."""
    import fsr_store
    store = fsr_store.open_store(excel_path)
    reports = merge_withdrawal_reports(store.read_all_reports(),
                                       store.read_all_withdrawal_reports())
    if controls is not None:
        wanted = {storage.control_key(c) for c in controls}
        if not wanted:
            raise MasterExportError("No report was chosen.")
        reports = [r for r in reports
                   if storage.control_key(r["control_no"]) in wanted]
        found = {storage.control_key(r["control_no"]) for r in reports}
        missing = [c for c in controls if storage.control_key(c) not in found]
        if missing:
            raise MasterExportError(
                "These reports are not saved here any more, so the export "
                "was stopped:\n" + "\n".join(missing))
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
    if controls is not None:      # only the chosen reports' case statuses
        statuses = [e for e in statuses
                    if storage.control_key(e.get("control_no")) in wanted]

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


def write_export(excel_path, target, device_id, inspector="", master_lists=None,
                 controls=None):
    """Write the file; returns the number of reports in it."""
    data = build_export(excel_path, device_id, inspector, master_lists,
                        controls)
    storage.write_json_atomic(target, data)
    return len(data["reports"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook")
    parser.add_argument("--device", required=True)
    parser.add_argument("--inspector", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--master-list", help="master_list.json to include")
    parser.add_argument("--report", action="append", dest="reports",
                        help="export only this Control # (repeat for more)")
    args = parser.parse_args()
    lists = None
    if args.master_list:
        import json
        lists = json.loads(Path(args.master_list).read_text(encoding="utf-8"))
    count = write_export(args.workbook, args.out, args.device, args.inspector,
                         lists, args.reports)
    print(f"{count} report(s) written to {args.out}")
