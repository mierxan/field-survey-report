"""Share the Item List of a Withdrawal report with its destinations.

The origin inspector picks a saved Withdrawal report, assigns its Packing
Lists to destinations, and gets ONE shipment file per destination. The
destination inspector brings that file into a new Receiving draft (a later
phase), so the item list is not typed again. The Windows PCs (Owner and
User edition) and the Android app read and write the same file
(docs/SHIPMENT.md).

Nothing here writes to a report: the origin report is only read.

The file (".fsrshipment") has the envelope of the hand-over file:
    {"format": "fsr-shipment", "version": 1,
     "payload": "<the JSON payload as text>",
     "checksum": "<SHA-256 of the payload text, UTF-8>"}

What travels is the origin reference (Control #, location, Inspection Date,
inspector, device) and, per line, only the cargo details with their prices
(SHARED_FIELDS), its Packing List No. and its Origin Line. SO Number,
Supplier and the other First Page fields are never in the file. (Unit Price,
Total Price and Currency travel since 18 November 2026, by the owner's
decision; they were left out before.)

The Packing List No. of a line: its own "Packing List No." field when it has
one; else, for the reports saved before that field existed, the line's
Findings when it holds a packing list number (e.g. "BAC111126-009") - the
whole cell exactly as written, so "BAC111126-001 & 002" stays one entry. It
is never guessed or split. A line without one belongs to the group
"no Packing List", which can be shared like any other.
"""
import copy
import hashlib
import json
import re
import uuid
from datetime import date, datetime
from pathlib import Path

import fsr_storage as storage

FORMAT = "fsr-shipment"
VERSION = 1
KIND = "withdrawal_share"
APP = "windows"
SUFFIX = ".fsrshipment"
MAX_BYTES = 20 * 1024 * 1024

PACKING_LIST = "Packing List No."
ORIGIN_LINE = "Origin Line"
# The cargo details of a line that travel (the Windows field names).
SHARED_FIELDS = ("Description of Goods", "PO Number", "Packaging",
                 "Quantity", "UOM", "Dimensions", "Weights",
                 storage.UNIT_NO_HEADER, "Currency", "Unit Price",
                 "Total Price")
LINE_FIELDS = (*SHARED_FIELDS, PACKING_LIST, ORIGIN_LINE)
# Never in a shipment file (checked when it is read, too).
FORBIDDEN_FIELDS = ("Findings",
                    "Cargo ID", "Receiving Ref", "so_number", "supplier",
                    "consignee")

NO_PACKING_LIST = ""
NO_PACKING_LIST_LABEL = "(no Packing List)"
# A packing list number: letters, digits, a dash, digits (BAC111126-009,
# MTA11126-001, LEY111126-001 & 002 ...).
_PACKING_NUMBER = re.compile(r"[A-Za-z]{2,6}\d{4,8}-\d{2,4}")


class ShipmentError(ValueError):
    """No shipment file was made or read; nothing was changed."""


# ---------- packing lists of a report ----------

def packing_list_of(row):
    """The Packing List No. of a saved line ("" when it has none)."""
    own = str(row.get(PACKING_LIST) or "").strip()
    if own:
        return own
    findings = str(row.get("Findings") or "").strip()
    return findings if _PACKING_NUMBER.search(findings) else NO_PACKING_LIST


def is_withdrawal(report):
    activity = (report.get("inspection_schedule") or {}).get("activity", "")
    return str(activity).strip().casefold() == "withdrawal"


def origin_line(control, list_no, line_no):
    return f"{control}/{list_no}/{line_no}"


def groups(report):
    """The Packing Lists of a report, in the order they first appear:
    [{"number", "po_numbers", "lines": [(list_no, line_no, row)]}]."""
    found = {}
    for list_no, item_list in enumerate(report.get("item_lists") or [],
                                        start=1):
        for line_no, row in enumerate(item_list.get("rows") or [], start=1):
            if not any(str(v or "").strip() for v in row.values()):
                continue
            number = packing_list_of(row)
            group = found.setdefault(number, {"number": number,
                                              "po_numbers": [], "lines": []})
            group["lines"].append((list_no, line_no, row))
            po = str(row.get("PO Number") or "").strip()
            if po and po not in group["po_numbers"]:
                group["po_numbers"].append(po)
    return list(found.values())


def label(number):
    return number or NO_PACKING_LIST_LABEL


# ---------- the saved Withdrawal reports of a workbook ----------

def withdrawal_reports(store):
    """Every saved Withdrawal report of this workbook (the main workbook
    and the PO-linked ones), newest Control # last."""
    reports = [r for r in store.read_all_reports() if is_withdrawal(r)]
    linked = store.read_all_withdrawal_reports()
    owned = {storage.control_key(r["control_no"]) for r in linked}
    reports = [r for r in reports
               if storage.control_key(r["control_no"]) not in owned]
    return reports + [r for r in linked if is_withdrawal(r)]


def read_report(store, control):
    """A saved Withdrawal report of this workbook (a copy)."""
    if any(storage.same_key(n, control) for n in store.withdrawal_numbers()):
        report = store.read_withdrawal_report(control)
    else:
        report = store.read_report(control)
    if not is_withdrawal(report):
        raise ShipmentError(f"{control} is not a Withdrawal report.")
    return copy.deepcopy(report)


# ---------- the payload ----------

def now_text():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _line(control, list_no, line_no, row):
    line = {key: str(row.get(key) or "").strip() for key in SHARED_FIELDS}
    line[PACKING_LIST] = packing_list_of(row)
    line[ORIGIN_LINE] = origin_line(control, list_no, line_no)
    return line


def build_payload(report, destination, numbers, sender, transfer_id=None,
                  created_at=None):
    """The payload of the shipment of `numbers` (Packing List numbers; ""
    for the lines without one) to `destination`. `sender`: {"inspector",
    "initials", "device_id"}."""
    destination = str(destination or "").strip()
    if not destination:
        raise ShipmentError("Choose the destination first.")
    control = report["control_no"]
    wanted = set(numbers)
    chosen = [g for g in groups(report) if g["number"] in wanted]
    missing = wanted - {g["number"] for g in chosen}
    if missing:
        raise ShipmentError(
            f"{control} has no Packing List "
            + ", ".join(sorted(label(m) for m in missing)) + ".")
    if not chosen:
        raise ShipmentError(f"Choose the Packing Lists for {destination}.")
    picked = {(l, n) for g in chosen for l, n, _ in g["lines"]}
    item_lists = []
    for list_no, item_list in enumerate(report.get("item_lists") or [],
                                        start=1):
        rows = [_line(control, list_no, line_no, row)
                for line_no, row in enumerate(item_list.get("rows") or [],
                                              start=1)
                if (list_no, line_no) in picked]
        if rows:
            item_lists.append({"name": f"Item List {len(item_lists) + 1}",
                               "rows": rows})
    general = report.get("general_information") or {}
    return {
        "transfer_id": transfer_id or uuid.uuid4().hex,
        "kind": KIND,
        "app": APP,
        "created_at": created_at or now_text(),
        "from": {"inspector": str(sender.get("inspector") or ""),
                 "initials": str(sender.get("initials") or ""),
                 "device_id": str(sender.get("device_id") or "")},
        "origin": {
            "control_no": control,
            "activity": "Withdrawal",
            "location": str(general.get("location") or ""),
            "inspection_date": str(general.get("inspection_date") or ""),
            "item_form": storage.item_form_name(report.get("item_form")),
        },
        "destination": destination,
        "packing_lists": [
            {"number": g["number"], "po_numbers": list(g["po_numbers"]),
             "line_count": len(g["lines"])} for g in chosen],
        "item_lists": item_lists,
    }


# ---------- checking ----------

def _text(value):
    return isinstance(value, str)


def problem(payload):
    """Why a payload cannot be used, or None."""
    if not isinstance(payload, dict):
        return "it holds no shipment"
    if payload.get("kind") != KIND:
        return "it is not a Withdrawal shipment"
    if not _text(payload.get("transfer_id")) or not payload["transfer_id"]:
        return "it has no transfer id"
    if payload.get("app") not in ("windows", "android"):
        return "it does not say which app made it"
    if not isinstance(payload.get("from"), dict):
        return "it does not say who sent it"
    origin = payload.get("origin")
    if not isinstance(origin, dict) or not _text(origin.get(
            "control_no")) or not origin["control_no"].strip():
        return "it has no origin Control #"
    if not _text(payload.get("destination")) or \
            not payload["destination"].strip():
        return "it has no destination"
    lists = payload.get("item_lists")
    if not isinstance(lists, list) or not lists:
        return "it holds no Item List"
    counts = {}
    for item_list in lists:
        rows = item_list.get("rows") if isinstance(item_list, dict) else None
        if not isinstance(rows, list) or not rows:
            return "an Item List has no lines"
        for row in rows:
            if not isinstance(row, dict):
                return "a line is damaged"
            extra = [k for k in row if k not in LINE_FIELDS]
            if extra:
                return f"a line has fields that are not shared: {extra[0]}"
            if not all(_text(v) for v in row.values()):
                return "a line is damaged"
            if not row.get(ORIGIN_LINE, "").strip():
                return "a line has no origin line"
            number = row.get(PACKING_LIST, "")
            counts[number] = counts.get(number, 0) + 1
    packing = payload.get("packing_lists")
    if not isinstance(packing, list):
        return "it has no list of Packing Lists"
    listed = {}
    for entry in packing:
        if not isinstance(entry, dict) or not _text(entry.get("number")) \
                or not isinstance(entry.get("po_numbers"), list) \
                or not isinstance(entry.get("line_count"), int):
            return "its list of Packing Lists is damaged"
        listed[entry["number"]] = entry["line_count"]
    if listed != counts:
        return "its Packing Lists do not match its lines"
    return None


def _envelope(payload):
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return {"format": FORMAT, "version": VERSION, "payload": text,
            "checksum": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def decode(root):
    """The checked payload of a parsed shipment file."""
    if isinstance(root, dict) and root.get("format") == "fsr-handover":
        raise ShipmentError("This is a hand-over file, not a shipment file. "
                            "Bring it in with Receive Hand-over.")
    if not isinstance(root, dict) or root.get("format") != FORMAT:
        raise ShipmentError("This is not a Field Survey Report shipment "
                            "file.")
    if root.get("version") != VERSION:
        raise ShipmentError(
            f"This shipment file has version {root.get('version')}, and this "
            f"program reads version {VERSION}. Please update the program.")
    text = root.get("payload")
    if not isinstance(text, str) or root.get("checksum") != hashlib.sha256(
            text.encode("utf-8")).hexdigest():
        raise ShipmentError("The shipment file is damaged or incomplete. Ask "
                            "for it to be sent again.")
    try:
        payload = json.loads(text)
    except ValueError as error:
        raise ShipmentError("The shipment file is damaged.") from error
    reason = problem(payload)
    if reason:
        raise ShipmentError(f"The shipment file cannot be used: {reason}.")
    return payload


def read_file(path):
    """The checked payload of a shipment file."""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise ShipmentError("The file is too large (more than 20 MB).")
        root = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ShipmentError(f"The file could not be read:\n{error}") \
            from error
    return decode(root)


# ---------- writing ----------

def file_name(control, destination, day=None):
    def safe(text):
        return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text)).strip("_") or "X"
    day = day or date.today()
    return (f"FSR_Shipment_{safe(control)}_to_{safe(destination)}_"
            f"{day:%Y-%m-%d}{SUFFIX}")


def _free_path(folder, name):
    target = Path(folder) / name
    number = 2
    while target.exists():
        target = Path(folder) / f"{Path(name).stem}_{number}{SUFFIX}"
        number += 1
    return target


def plan(report, assignments):
    """{destination: [Packing List numbers]} from {number: destination},
    destinations in the order first used. Checks that every number is one
    of the report's and has one destination."""
    known = {g["number"] for g in groups(report)}
    result = {}
    for number, destination in assignments.items():
        destination = str(destination or "").strip()
        if not destination:
            continue
        if number not in known:
            raise ShipmentError(f"{report['control_no']} has no Packing "
                                f"List {label(number)}.")
        same = next((d for d in result if d.casefold()
                     == destination.casefold()), destination)
        result.setdefault(same, []).append(number)
    if not result:
        raise ShipmentError("Assign at least one Packing List to a "
                            "destination.")
    return result


def write_shipments(store, control, assignments, folder, sender, day=None):
    """Write one shipment file per destination for saved Withdrawal report
    `control`. `assignments`: {Packing List number: destination}. Each file
    is read back and checked; if one cannot be written, the files of this
    call are removed again (all or nothing). The report is only read.
    Returns [(destination, path, payload)]."""
    report = read_report(store, control)
    folder = Path(folder)
    if not folder.is_dir():
        raise ShipmentError(f"The folder does not exist:\n{folder}")
    written = []
    try:
        for destination, numbers in plan(report, assignments).items():
            payload = build_payload(report, destination, numbers, sender)
            reason = problem(payload)
            if reason:
                raise ShipmentError(f"The shipment for {destination} could "
                                    f"not be made: {reason}.")
            target = _free_path(folder, file_name(control, destination, day))
            storage.write_json_atomic(target, _envelope(payload))
            written.append((destination, target, payload))
            if read_file(target) != payload:
                raise ShipmentError(f"The file for {destination} could not "
                                    "be checked.")
    except BaseException:
        for _, target, _ in written:
            try:
                target.unlink()
            except OSError:
                pass
        raise
    return written


def describe(payload):
    """One line: what the shipment holds."""
    origin = payload["origin"]
    lines = sum(len(il["rows"]) for il in payload["item_lists"])
    names = ", ".join(label(p["number"]) for p in payload["packing_lists"])
    return (f"{lines} item line(s) of Withdrawal report "
            f"{origin['control_no']} ({origin.get('location') or 'origin'}) "
            f"for {payload['destination']} - Packing List(s): {names}")


# =====================================================================
# THE DESTINATION: bringing a shipment file into a new Receiving draft
# =====================================================================
#
# The PC (or phone) is set once to the destination it serves ("This site's
# destination"); a file for another destination is refused. The file's lines
# become the Item List of a NEW Receiving draft of the signed-in account,
# with their Packing List No. and Origin Line kept in the hidden line fields
# and Findings left empty for the destination inspector. The First Page is
# empty except Activity = Receiving. Nothing else is written: the draft is
# made, then recorded in <workbook>_shipments.json beside the workbook's
# other side files; if the record cannot be written, the draft is removed
# again (all or nothing).
#
# A shipment is refused as already imported when any of its origin lines is
# in a saved report of this workbook or in a draft made from an earlier
# import that still exists. (A draft discarded by mistake can be imported
# again.)

SETTING = "site_destination"            # in settings.json of this PC
LEDGER_SUFFIX = "_shipments.json"


class ShipmentDuplicate(ShipmentError):
    """The shipment, or some of its lines, came in before."""


def site_destination(settings):
    return str((settings or {}).get(SETTING) or "").strip()


def ledger_path(excel_path):
    import fsr_paths
    excel_path = Path(excel_path)
    return (fsr_paths.json_dir_for_workbook(excel_path)
            / f"{excel_path.stem}{LEDGER_SUFFIX}")


def load_ledger(excel_path):
    path = ledger_path(excel_path)
    if not path.exists():
        return {"imports": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ShipmentError(f"The record of imported shipments could not be "
                            f"read:\n{path}\n{error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("imports"),
                                                    dict):
        raise ShipmentError(f"The record of imported shipments is damaged:"
                            f"\n{path}")
    return data


def _save_ledger(excel_path, data):
    path = ledger_path(excel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json_atomic(path, data)


def origin_lines(payload):
    return [row[ORIGIN_LINE] for item_list in payload["item_lists"]
            for row in item_list["rows"]]


def receiving_data(payload):
    """The new Receiving report in the Windows data shape: the shipment's
    lines in its Item Lists (Packing List No. and Origin Line hidden,
    Findings empty), everything else empty but Activity = Receiving."""
    form = storage.item_form_name(payload["origin"].get("item_form"))
    item_lists = []
    for number, item_list in enumerate(payload["item_lists"], start=1):
        rows = []
        for line in item_list["rows"]:
            row = {header: "" for header in storage.ITEM_LINE_HEADERS}
            row.update({key: line.get(key, "") for key in SHARED_FIELDS})
            for key in (PACKING_LIST, ORIGIN_LINE):
                if line.get(key, "").strip():
                    row[key] = line[key]
            rows.append(row)
        item_lists.append({"name": f"Item List {number}", "rows": rows})
    return {
        "control_no": "", "cargo_condition": "", "item_form": form,
        "goods_types": storage.empty_goods_types(), "incident_reports": [],
        "general_information": {key: "" for key in (
            "so_number", "inspection_date", "consignee", "supplier",
            "brokerage", "hauler", "location", "destination",
            "country_of_origin")},
        "inspection_schedule": {"activity": "Receiving", "commenced_date": "",
                                "commenced_time": "", "completion_date": "",
                                "completion_time": ""},
        "transport_details": {key: "" for _, key, *_ in
                              storage.TRANSPORT_FIELDS},
        "documents_used": {key: "" for _, key in storage.DOCUMENT_FIELDS},
        "declared_goods": [], "other_important_remarks": [],
        "item_lists": item_lists, "other_item_forms": {},
        "findings_and_remarks": [],
    }


def lines_in_reports(store):
    """{origin line: Control #} of the saved reports of this workbook."""
    found = {}
    for report in store.read_all_reports():
        for item_list in report.get("item_lists") or []:
            for row in item_list.get("rows") or []:
                line = str(row.get(ORIGIN_LINE) or "").strip()
                if line:
                    found.setdefault(line, report["control_no"])
    return found


def _draft_exists(draft_store, entry):
    try:
        return draft_store.path(entry["draft_id"],
                                entry.get("owner")).exists()
    except (KeyError, ValueError, TypeError):
        return False


def check_import(excel_path, payload, destination, store, draft_store):
    """Raises ShipmentError when `payload` cannot be imported here: another
    destination, or imported before (ShipmentDuplicate)."""
    destination = str(destination or "").strip()
    meant = payload["destination"].strip()
    if not destination:
        raise ShipmentError(
            "This PC's destination is not set yet. Set it first (Receive "
            "Shipment > This PC's destination): only shipments for that "
            "destination can be imported here.")
    if destination.casefold() != meant.casefold():
        raise ShipmentError(
            f"This shipment is for {meant}, but this PC is set to receive "
            f"for {destination}. It was not imported.\n\nSend the file to "
            f"{meant}, or ask the origin inspector for the file made for "
            f"{destination}.")
    wanted = set(origin_lines(payload))
    ledger = load_ledger(excel_path)
    for transfer, entry in ledger["imports"].items():
        if not _draft_exists(draft_store, entry):
            continue
        if transfer == payload["transfer_id"] or wanted & set(
                entry.get("origin_lines") or []):
            when = str(entry.get("at", ""))[:16].replace("T", " ")
            raise ShipmentDuplicate(
                f"This shipment was imported before, on {when}: it is a "
                "draft in Account > Unfinished work (Restore it there). "
                "Nothing was imported again.")
    saved = lines_in_reports(store)
    clash = sorted({saved[line] for line in wanted if line in saved})
    if clash:
        raise ShipmentDuplicate(
            f"Lines of this shipment are already in saved report(s) "
            f"{', '.join(clash)}. Nothing was imported again.")


def import_shipment(excel_path, payload, destination, store, draft_store,
                    owner_label, to_form):
    """Make the Receiving draft of a checked payload (read_file / decode).
    `to_form(data)`: the draft form of a report in the Windows data shape
    (made by the window, as for a phone draft). Returns the draft value."""
    import uuid as _uuid
    import fsr_drafts
    from fsr_draft_form import validate_snapshot
    check_import(excel_path, payload, destination, store, draft_store)
    form = to_form(receiving_data(payload))
    # the First Page starts empty: no date of today, no Commenced Date
    form["date"] = ""
    form.setdefault("schedule_entries", {})["commenced_date"] = ""
    if not validate_snapshot(form):
        raise ShipmentError("The Receiving draft could not be made.")
    origin = payload["origin"]
    summary = {
        "transfer_id": payload["transfer_id"],
        "origin_control": origin["control_no"],
        "origin_location": origin.get("location", ""),
        "origin_date": origin.get("inspection_date", ""),
        "destination": payload["destination"],
        "from": dict(payload.get("from") or {}),
        "packing_lists": [p["number"] for p in payload["packing_lists"]],
    }
    value = {"version": fsr_drafts.VERSION, "id": _uuid.uuid4().hex,
             "scope": draft_store.scope, "owner": draft_store.owner,
             "owner_label": owner_label, "session": "", "pid": 0,
             "process_started": None, "revision": 1,
             "changed": fsr_drafts.now_text(), "workbook": str(excel_path),
             "editing": False, "control": "", "source": "excel",
             "baseline": {}, "form": form, "shipment": summary}
    draft_store.write(value)
    try:
        ledger = load_ledger(excel_path)
        ledger["imports"][payload["transfer_id"]] = {
            **summary, "at": now_text(), "draft_id": value["id"],
            "owner": draft_store.owner, "origin_lines": origin_lines(payload),
            "app": payload.get("app", "")}
        _save_ledger(excel_path, ledger)
    except BaseException:
        draft_store.discard(value["id"])
        raise
    return value


def describe_import(payload):
    """What the destination inspector reads before saying Yes."""
    origin = payload["origin"]
    sender = payload.get("from") or {}
    who = sender.get("inspector") or sender.get("initials") or "an inspector"
    app = "Windows program" if payload.get("app") == "windows" \
        else "phone app"
    lines = sum(len(il["rows"]) for il in payload["item_lists"])
    packing = "\n".join(
        f"   {label(p['number'])}  -  {p['line_count']} line(s)"
        + (f", PO {', '.join(p['po_numbers'])}" if p["po_numbers"] else "")
        for p in payload["packing_lists"])
    where = f" ({origin['location']})" if origin.get("location") else ""
    day = f", {origin['inspection_date']}" \
        if origin.get("inspection_date") else ""
    return (f"Shipment for {payload['destination']}\n\n"
            f"From Withdrawal report {origin['control_no']}{where}{day}\n"
            f"Sent by {who} on {str(payload.get('created_at', ''))[:10]} "
            f"from the {app}\n\nPacking Lists ({lines} line(s)):\n{packing}")
