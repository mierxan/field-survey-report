"""Hand a report or a draft over to the next inspector, and receive one.

An inspector who moves to another location can give an unfinished report to
the inspector who continues it: Hand Over writes ONE file (format
"fsr-handover") with that report or draft, the next inspector receives it
with Receive Hand-over - on a Windows PC (Owner or User edition) or on the
Android app, which writes and reads the same file (docs/HANDOVER.md).

Numbering: a saved report keeps the Control # it was first given, on every
PC and phone. Only when that exact number is already used by ANOTHER report
where it arrives does it get the next free number there. A draft of a new
report has no number yet; it takes the finishing inspector's next number on
its first save, as any new report does. A draft started on the Android
app already has its number (the app numbers a report on its first save, also
as a draft): it keeps it, and it becomes a draft on the PC that keeps the
report's identity (see "phone drafts" below).

The sender keeps a copy marked "handed over": it can be opened and printed,
not saved, until it comes back (Receive Hand-over, or for the Owner Import
Review) or the sender cancels the hand-over.

A handed-over report carries a permanent identity (report id + the location
where it was first handed over) and a revision number, also in Master Data
files. When both inspectors later send Master Data to the Owner, the
Owner's import recognises one report and keeps the newest revision
(fsr_import), instead of adding it twice.

The record of this PC is <workbook>_handovers.json beside the workbook's
other side files: {"reports": {report id: entry}}.
"""
import copy
import hashlib
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import fsr_import
import fsr_paths
import fsr_storage as storage

log = logging.getLogger("fsr")

FORMAT = "fsr-handover"
VERSION = 1
APP = "windows"
SUFFIX = "_handovers.json"
MAX_BYTES = 20 * 1024 * 1024

ACTIVE = "active"              # worked on here
HANDED_OVER = "handed_over"    # given to the next inspector: not saved here
RECEIVING = "receiving"        # being written here (a cut-off receive)

# what a report in a hand-over or Master Data file carries for its identity
IDENTITY_KEYS = ("report_id", "revision", *fsr_import.HANDOVER_KEYS)


class HandoverError(ValueError):
    """The hand-over could not be made or received; nothing was changed."""


class HandoverConflict(HandoverError):
    """This PC has its own working copy of the received report. `changes`:
    fsr_import.report_changes() from this PC's copy to the received one."""

    def __init__(self, message, control, changes):
        super().__init__(message)
        self.control = control
        self.changes = changes


# ---------- the record of this PC ----------

def ledger_path(excel_path):
    excel_path = Path(excel_path)
    return (fsr_paths.json_dir_for_workbook(excel_path)
            / f"{excel_path.stem}{SUFFIX}")


def load(excel_path):
    path = ledger_path(excel_path)
    if not path.exists():
        return {"reports": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise HandoverError(
            f"The hand-over record could not be read:\n{path}\n{error}") \
            from error
    if not isinstance(data, dict) or not isinstance(data.get("reports"),
                                                    dict):
        raise HandoverError(f"The hand-over record is damaged:\n{path}")
    return data


def _save(excel_path, data):
    path = ledger_path(excel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json_atomic(path, data)


def find(data, control):
    """(report id, entry) of the report with this Control #, or (None,
    None)."""
    for report_id, entry in data["reports"].items():
        if storage.same_key(entry.get("control"), control):
            return report_id, entry
    return None, None


def status(excel_path, control):
    """A copy of this PC's hand-over entry of a report, or None."""
    _, entry = find(load(excel_path), control)
    return copy.deepcopy(entry) if entry else None


def handed_over(excel_path, control):
    """The entry when this report was handed over from here (it is not saved
    here then), else None."""
    try:
        entry = status(excel_path, control)
    except HandoverError:
        log.exception("Hand-over record unreadable")
        return None
    return entry if entry and entry.get("state") == HANDED_OVER else None


def now_text():
    return datetime.now().isoformat(timespec="seconds")


def _note(entry, event, **more):
    entry.setdefault("history", []).append(
        {"event": event, "time": now_text(), **more})


# ---------- identity and revisions ----------

def clean(report):
    """The report without identity fields (as it is kept in the workbook)."""
    result = copy.deepcopy(report)
    for key in (*IDENTITY_KEYS, "incident_error"):
        result.pop(key, None)
    return result


def _bump(entry, report):
    """A new revision when the content changed since the last one. True when
    the entry changed."""
    fingerprint = fsr_import.report_fingerprint(clean(report))
    if entry.get("fingerprint") == fingerprint:
        return False
    if entry.get("fingerprint") is not None:
        entry["revision"] = int(entry.get("revision") or 0) + 1
    entry["fingerprint"] = fingerprint
    return True


def identity(entry):
    return {"report_id": entry["report_id"], "revision": entry["revision"],
            "location_id": entry["location_id"],
            "location_name": entry["location_name"],
            "handover_origin": dict(entry["origin"])}


def _new_entry(control, sender):
    device = sender.get("device_id") or "windows"
    who = sender.get("initials") or sender.get("inspector") or device
    return {"report_id": uuid.uuid4().hex, "control": control, "revision": 1,
            "fingerprint": None, "location_id": f"handover:{device}",
            "location_name": f"Handed over by {who}",
            "origin": {"device": device, "control": control},
            "state": ACTIVE, "history": []}


def with_identity(excel_path, reports):
    """For Export Master Data: every report that was handed over (from or
    to this PC) carries its identity and current revision."""
    data = load(excel_path)
    if not data["reports"]:
        return reports
    changed = False
    result = []
    for report in reports:
        _, entry = find(data, report["control_no"])
        if entry is not None and entry.get("state") != RECEIVING:
            changed |= _bump(entry, report)
            report = dict(report, **identity(entry))
        result.append(report)
    if changed:
        _save(excel_path, data)
    return result


# ---------- the file ----------

def _envelope(payload):
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return {"format": FORMAT, "version": VERSION, "payload": text,
            "checksum": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def _write_file(target, payload):
    """Write, then read back and check, before anything here is marked."""
    storage.write_json_atomic(target, _envelope(payload))
    back = read_file(target)
    if back["handover_id"] != payload["handover_id"]:
        raise HandoverError("The hand-over file could not be checked.")


def _problem(payload):
    if not isinstance(payload, dict):
        return "it holds no hand-over"
    if payload.get("kind") not in ("report", "draft"):
        return "it holds neither a report nor a draft"
    if not isinstance(payload.get("handover_id"), str) \
            or not payload["handover_id"]:
        return "it has no hand-over id"
    if not isinstance(payload.get("from"), dict):
        return "it does not say who handed it over"
    report = payload.get("report")
    if report is not None:
        problem = fsr_import._report_problem(report)
        if problem:
            return f"its report cannot be used: {problem}"
        if not str(report.get("report_id") or "").strip():
            return "its report has no report id"
        if fsr_import.report_revision(report) is None:
            return "its report has no revision"
    elif payload["kind"] == "report":
        return "it holds no report"
    draft = payload.get("draft")
    if payload["kind"] == "draft":
        if not isinstance(draft, dict) or draft.get("app") not in (
                "windows", "android"):
            return "it holds no draft"
    return None


def read_file(path):
    """The checked contents (payload) of a hand-over file."""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise HandoverError("The file is too large (more than 20 MB).")
        root = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise HandoverError(f"The file could not be read:\n{error}") \
            from error
    if isinstance(root, dict) and root.get("format") == fsr_import.FORMAT:
        raise HandoverError(
            "This is a Master Data file, not a hand-over file. The Owner "
            "brings it in with Import Master Data.")
    if not isinstance(root, dict) or root.get("format") != FORMAT:
        raise HandoverError("This is not a Field Survey Report hand-over "
                            "file.")
    if root.get("version") != VERSION:
        raise HandoverError(
            f"This hand-over file has version {root.get('version')}, and "
            f"this program reads version {VERSION}. Please update the "
            "program.")
    text = root.get("payload")
    if not isinstance(text, str) or root.get("checksum") != hashlib.sha256(
            text.encode("utf-8")).hexdigest():
        raise HandoverError("The hand-over file is damaged or incomplete. "
                            "Ask for it to be sent again.")
    try:
        payload = json.loads(text)
    except ValueError as error:
        raise HandoverError("The hand-over file is damaged.") from error
    problem = _problem(payload)
    if problem:
        raise HandoverError(f"The hand-over file cannot be used: {problem}.")
    return payload


def describe(payload):
    """One line for the receiver: what the file holds, from whom."""
    sender = payload["from"]
    who = sender.get("inspector") or sender.get("initials") or "an inspector"
    if payload["kind"] == "report":
        what = f"completed report {payload['report']['control_no']}"
    elif payload["draft"].get("app") == "android":
        phone = payload["draft"].get("report")
        number = phone.get("controlNo") if isinstance(phone, dict) else ""
        what = (f"unfinished report {number} (a draft from the phone app)"
                if number else "an unfinished report from the phone app")
    elif payload.get("report"):
        what = (f"unfinished changes to report "
                f"{payload['report']['control_no']}")
    else:
        what = "an unfinished new report (draft)"
    when = str(payload.get("created_at") or "").replace("T", " ")[:16]
    return f"{what}, handed over by {who} on {when}"


# ---------- handing over ----------

def _linked_form(form):
    return bool(form["withdrawal"]["owned"] or any(
        row["po_link"] for section in form["items"]
        for row in section["rows"]))


def _payload(kind, sender, to, note, report=None, draft=None):
    return {"handover_id": uuid.uuid4().hex, "kind": kind, "app": APP,
            "created_at": now_text(), "from": dict(sender), "to": to or "",
            "note": note or "", "report": report, "draft": draft}


def _report_for(excel_path, store, control, sender, data):
    """(report with identity, entry) of a saved report of this PC."""
    if any(storage.same_key(n, control) for n in store.withdrawal_numbers()):
        raise HandoverError(
            f"{control} is a Withdrawal report linked to a PO. Those cannot "
            "be handed over yet: their stock belongs to this location.")
    report = store.read_report(control)
    if report.get("incident_error"):
        raise HandoverError(report["incident_error"])
    report["last_saved"] = store.last_saved_times().get(
        report["control_no"].strip().casefold(), "")
    _, entry = find(data, report["control_no"])
    if entry is None:
        entry = _new_entry(report["control_no"], sender)
        data["reports"][entry["report_id"]] = entry
    entry["control"] = report["control_no"]
    _bump(entry, report)
    return dict(clean(report), **identity(entry)), entry


def _mark_sent(excel_path, data, entry, payload, owner_edition):
    entry.update(state=HANDED_OVER, to=payload["to"],
                 at=payload["created_at"],
                 handover_id=payload["handover_id"])
    _note(entry, "handed_over", to=payload["to"],
          revision=entry["revision"], handover_id=payload["handover_id"])
    _save(excel_path, data)
    if owner_edition:
        fsr_import.record_handover(
            excel_path, payload["report"], entry["control"],
            device=payload["from"].get("device_id", ""),
            inspector=payload["from"].get("inspector", ""))


def hand_over_report(excel_path, control, target, sender, to="", note="",
                     owner_edition=False):
    """Write the hand-over file of saved report `control` and mark it handed
    over here. `sender`: {"inspector", "initials", "device_id"}. Returns the
    payload written."""
    import fsr_store
    store = fsr_store.open_store(excel_path)
    data = load(excel_path)
    report, entry = _report_for(excel_path, store, control, sender, data)
    payload = _payload("report", sender, to, note, report=report)
    _write_file(target, payload)
    _mark_sent(excel_path, data, entry, payload, owner_edition)
    return payload


def hand_over_draft(excel_path, value, draft_store, target, sender, to="",
                    note="", owner_edition=False):
    """Write the hand-over file of one of this account's drafts (a value of
    fsr_drafts.Store.list()). The draft stays here marked handed over (it
    can only be discarded); when it changes a saved report, that report is
    handed over with it."""
    import fsr_store
    if value.get("handed_over"):
        raise HandoverError("This draft was already handed over.")
    if value.get("orphan"):
        raise HandoverError("Drafts of removed accounts cannot be handed "
                            "over.")
    if Path(value["workbook"]).resolve() != Path(excel_path).resolve():
        raise HandoverError(
            "This draft belongs to another workbook. Choose that workbook "
            "first.")
    if _linked_form(value["form"]):
        raise HandoverError(
            "This draft is a Withdrawal linked to a PO. Those cannot be "
            "handed over yet: their stock belongs to this location.")
    data = load(excel_path)
    report = entry = None
    if value["editing"]:
        store = fsr_store.open_store(excel_path)
        report, entry = _report_for(excel_path, store, value["control"],
                                    sender, data)
    draft = {"app": APP, "form": copy.deepcopy(value["form"]),
             "editing": bool(value["editing"]),
             "control": value["control"] if value["editing"] else "",
             "source": value.get("source", "excel")}
    kept = _kept(value.get("received"))
    if kept is not None and not value["editing"]:
        # a phone draft received here: its number and identity go along
        draft["kept"] = kept
    payload = _payload("draft", sender, to, note, report=report, draft=draft)
    _write_file(target, payload)
    if entry is not None:
        _mark_sent(excel_path, data, entry, payload, owner_edition)
    kept = {k: v for k, v in value.items() if k not in ("orphan", "old")}
    kept["handed_over"] = {"to": payload["to"], "at": payload["created_at"],
                           "handover_id": payload["handover_id"]}
    draft_store.write(kept)
    return payload


def cancel(excel_path, control):
    """The sender works on a handed-over report here again (the file was
    lost, or the next inspector will not finish it)."""
    data = load(excel_path)
    _, entry = find(data, control)
    if entry is None or entry.get("state") != HANDED_OVER:
        raise HandoverError(f"{control} is not handed over.")
    entry["state"] = ACTIVE
    _note(entry, "cancelled")
    _save(excel_path, data)


def came_back(excel_path, report_id, control, revision):
    """The Owner accepted a newer revision of a report it had handed over
    (Import Review): it is worked on here again."""
    report_id = str(report_id or "").strip()
    if not report_id:
        return
    data = load(excel_path)
    entry = data["reports"].get(report_id)
    if entry is None:
        return
    entry.update(control=control, state=ACTIVE, fingerprint=None,
                 revision=max(int(entry.get("revision") or 0),
                              int(revision or 0)))
    _note(entry, "came_back", revision=revision)
    _save(excel_path, data)


# ---------- receiving ----------

def _write_report(excel_path, store, report, editing, journal, stores,
                  mysql):
    """One report into the workbook or database, on record first like a
    normal save (the save record finishes it after a cut-off). Returns
    (Control #, error of the PO lists or None)."""
    import fsr_save_journal as journal_module
    now = datetime.now()
    stamp = now.replace(microsecond=now.microsecond // 1000 * 1000)
    records = None
    if journal is not None:
        records = journal.begin_batch(
            [(report, editing,
              journal_module.steps_for(report, False, mysql), {})],
            now=stamp)

    def write():
        return store.write_reports([(report, editing, stamp)])
    try:
        if stores is not None and stores.guard is not None:
            with stores.guard.local_write():
                results = write()
        else:
            results = write()
    except BaseException:
        if records is not None:
            try:
                journal.discard_batch(records)
            # Broad on purpose: the error being raised is the one that
            # matters; a failing clean-up must not replace it.
            except Exception:
                log.debug("Hand-over record not discarded", exc_info=True)
        raise
    control = results[0]["control"]
    report["control_no"] = control
    fsr_import.write_side_files(excel_path, control, report)
    lists_failed = None
    if records is not None:
        record = records[0]
        if "item_lists" in record["steps"]:
            try:
                stores.item_lists(record)
            except Exception as error:      # finished at the next save
                lists_failed = error
        record["control"] = record["data"]["control_no"] = control
        record["data"] = copy.deepcopy(record["data"])
        record["editing"] = True
        record["stamp"] = record["stamp_planned"]
        for step in ("workbook", "incidents", "item_forms"):
            record["steps"][step] = journal_module.DONE
        if "item_lists" in record["steps"]:
            if lists_failed is None:
                record["steps"]["item_lists"] = journal_module.DONE
            else:
                record["errors"]["item_lists"] = str(lists_failed)
        journal.save_many(records)
    return control, lists_failed


def _receive_report(excel_path, payload, journal, stores, mysql,
                    owner_edition, replace):
    import fsr_store
    incoming = payload["report"]
    report_id = str(incoming["report_id"]).strip()
    revision = fsr_import.report_revision(incoming)
    sent_as = str(incoming["control_no"]).strip()
    store = fsr_store.open_store(excel_path)
    numbers = store.control_numbers()

    def here(control):
        return next((n for n in numbers if storage.same_key(n, control)),
                    None)

    data = load(excel_path)
    entry = data["reports"].get(report_id)
    local = None
    known_revision = None
    working = False         # this PC has its own working copy
    if entry is not None and here(entry["control"]):
        local = here(entry["control"])
        known_revision = int(entry.get("revision") or 0)
        working = entry.get("state") == ACTIVE
    elif owner_edition:
        ledger_entry = fsr_import.load_ledger(excel_path).get(
            fsr_import.report_identity({}, incoming))
        if ledger_entry and here(ledger_entry["control"]):
            # imported here before from a Master Data file
            local = here(ledger_entry["control"])
            known_revision = fsr_import._as_revision(
                ledger_entry.get("revision")) or 0
            working = True
    result = {"control": local, "sent_as": sent_as, "renumbered": False,
              "result": None, "lists_failed": None}
    if local is not None and revision <= known_revision:
        result["result"] = "unchanged"
        return result
    if local is not None and working and not replace:
        current = store.read_report(local)
        raise HandoverConflict(
            f"This PC already has its own copy of {local}, and it is not "
            "handed over. Replacing it with the received report loses the "
            "changes made here since.", local,
            fsr_import.report_changes(clean(current), clean(incoming)))
    if local is None:
        wanted = entry["control"] if entry is not None else sent_as
        local = wanted
        if here(wanted):
            # that number is another report here: the next free one
            local = store.next_free_number(wanted)
            result["renumbered"] = True
    report = clean(incoming)
    if not storage.same_key(local, sent_as):
        fsr_import._renumbered(report, sent_as, local)
    report["control_no"] = local

    if entry is None:
        entry = {"report_id": report_id,
                 "location_id": incoming["location_id"],
                 "location_name": incoming.get("location_name") or "",
                 "origin": dict(incoming.get("handover_origin") or {
                     "device": payload["from"].get("device_id", ""),
                     "control": sent_as}),
                 "history": []}
        data["reports"][report_id] = entry
    # On record before the report is written: a cut-off receive is
    # finished by receiving the file again, never doubled.
    entry.update(control=local, state=RECEIVING, revision=revision + 1,
                 fingerprint=None)
    _save(excel_path, data)
    editing = here(local) is not None
    local, result["lists_failed"] = _write_report(
        excel_path, store, report, editing, journal, stores, mysql)
    entry["control"] = local
    entry["state"] = ACTIVE
    entry.pop("to", None)
    _note(entry, "received", sender=payload["from"],
          revision=revision, handover_id=payload["handover_id"])
    try:
        _bump(entry, store.read_report(local))
    except (OSError, ValueError):
        log.exception("Received report not read back")
    _save(excel_path, data)
    if owner_edition:
        fsr_import.record_handover(
            excel_path, dict(incoming), local,
            device=payload["from"].get("device_id", ""),
            inspector=payload["from"].get("inspector", ""),
            result="received_handover")
    result.update(control=local,
                  result="updated" if editing else "added")
    return result



# ---------- phone drafts ----------
#
# A draft started on the Android app is the app's own report record. The PC
# turns it into the Windows data shape (the same as the app's Master Data
# export, MasterDataExport.reportJson, checked against a file the app's
# tests write), and the window turns that into its draft form. The draft
# keeps the phone's Control # and the report's identity in
# value["received"]: the number is put on the form when the draft is
# restored (the next free one when another report here has it by then), and
# on its first save the identity is recorded (adopt), so it stays one
# report: for a hand-back to the phone and for the Owner.

PHONE_FORMS = ("Default", "Containerized", "Loading")
_PHONE_LINE = (("Description of Goods", "description"),
               ("PO Number", "poNumber"), ("Packaging", "packaging"),
               ("Quantity", "quantity"), ("Dimensions", "dimensions"),
               ("Weights", None), ("Unit Price", "unitPrice"),
               ("Total Price", "totalPrice"), ("Findings", "findings"),
               ("Cargo ID", "cargoId"), ("Receiving Ref", "receivingRef"),
               ("UOM", "uom"), ("Currency", "currency"),
               ("Container / Truck No.", "unitNo"))
_PHONE_FILLED = ("description", "poNumber", "packaging", "quantity", "uom",
                 "dimensions", "weights", "weightUnit", "currency",
                 "unitPrice", "totalPrice", "findings", "unitNo")


def _phone_text(value):
    return value if isinstance(value, str) else ""


def _phone_rows(values):
    return [v for v in values if isinstance(v, dict)] \
        if isinstance(values, list) else []


def _phone_strings(values):
    return [v for v in values if isinstance(v, str) and v.strip()] \
        if isinstance(values, list) else []


def phone_report_data(phone):
    """The Windows data shape of a phone draft (the app's Report record)."""
    def text(key, default=""):
        return _phone_text(phone.get(key, default))

    def line(value):
        weight = " ".join(part for part in (
            _phone_text(value.get("weights")).strip(),
            _phone_text(value.get("weightUnit")).strip()) if part)
        return {header: weight if key is None
                else _phone_text(value.get(key))
                for header, key in _PHONE_LINE}

    def filled(value):
        return any(_phone_text(value.get(key)).strip()
                   for key in _PHONE_FILLED)

    lists = phone.get("itemLists")
    lists = lists if isinstance(lists, dict) else {}

    def lists_of(form):
        found = _phone_rows(lists.get(form)) if form in lists \
            else [{"lines": []}]
        return [{"name": f"Item List {number}",
                 "rows": [line(row) for row in _phone_rows(
                     value.get("lines")) if filled(row)]}
                for number, value in enumerate(found, 1)]

    form = text("itemForm", "Default")
    condition = text("cargoCondition")
    others = {}
    for name in PHONE_FORMS:
        if name != form:
            found = lists_of(name)
            if any(value["rows"] for value in found):
                others[name] = found
    incidents = []
    if condition == "Bad Order":
        for card in _phone_rows(phone.get("incidents", [{}])):
            incidents.append({
                **{key: _phone_text(card.get(name)) for key, name in (
                    ("vessel", "vessel"), ("voyage", "voyage"),
                    ("client", "client"), ("so_number", "soNumber"),
                    ("port", "port"), ("date", "date"),
                    ("operation", "operation"))},
                "lines": _phone_strings(card.get("lines"))})
    return {
        "control_no": text("controlNo"), "last_saved": text("lastSaved"),
        "cargo_condition": condition, "item_form": form,
        "goods_types": {
            "new": phone.get("goodsNew") is True,
            "used": phone.get("goodsUsed") is True,
            "food_stuffs": phone.get("goodsFoodStuff") is True,
            "vehicle": phone.get("goodsVehicle") is True,
            "pharma_chemicals": phone.get("goodsPharma") is True,
            "others": phone.get("goodsOthers") is True,
            "others_text": text("goodsOthersText")},
        "general_information": {
            "so_number": text("soNumber"),
            "inspection_date": text("inspectionDate"),
            "consignee": text("consignee"), "supplier": text("supplier"),
            "brokerage": text("brokerage"), "hauler": text("hauler"),
            "location": text("location"),
            "destination": text("destination"),
            "country_of_origin": text("countryOfOrigin")},
        "inspection_schedule": {
            "activity": text("activity"),
            "commenced_date": text("commencedDate"),
            "commenced_time": text("commencedTime"),
            "completion_date": text("completionDate"),
            "completion_time": text("completionTime")},
        "transport_details": {
            "shipment_type": text("shipmentType"),
            "container_type": text("containerType"),
            "vessel_carrier": text("vesselCarrier"),
            "vehicle_type": text("vehicleType"),
            "vehicle_plate_number": text("vehiclePlateNumber")},
        "documents_used": {
            "invoice_number": text("invoiceNumber"),
            "po_number": text("poNumber"), "jo_number": text("joNumber"),
            "gatepass_number": text("gatepassNumber"),
            "bl_awb_number": text("blAwbNumber"),
            "dr_number": text("drNumber"),
            "other_documents": text("otherDocuments")},
        "declared_goods": [
            {key: _phone_text(good.get(key))
             for key in ("description", "quantity", "packaging")}
            for good in _phone_rows(phone.get("declaredGoods"))
            if any(_phone_text(good.get(key)).strip()
                   for key in ("description", "quantity", "packaging"))],
        "other_important_remarks": _phone_strings(phone.get("otherRemarks")),
        "item_lists": lists_of(form),
        "other_item_forms": others,
        "findings_and_remarks": _phone_strings(
            phone.get("additionalDetails")),
        "incident_reports": incidents,
    }


def _phone_identity(value):
    """The identity a phone draft carries, checked, or None."""
    if not isinstance(value, dict):
        return None
    revision = value.get("revision")
    if not str(value.get("report_id") or "").strip() \
            or isinstance(revision, bool) or not isinstance(revision, int) \
            or revision < 1 or not isinstance(value.get("location_id"), str):
        return None
    origin = value.get("handover_origin")
    return {"report_id": str(value["report_id"]).strip(),
            "revision": revision, "location_id": value["location_id"],
            "location_name": _phone_text(value.get("location_name")),
            "handover_origin": {
                "device": _phone_text(origin.get("device")),
                "control": _phone_text(origin.get("control"))}
            if isinstance(origin, dict) else None}


def _kept(received):
    """{"control", "identity"} of a draft that keeps its number (a phone
    draft), or None."""
    if not isinstance(received, dict):
        return None
    identity = _phone_identity(received.get("identity"))
    control = _phone_text(received.get("control")).strip()
    if identity is None or not control:
        return None
    return {"control": control, "identity": identity}


def _without_own_refs(data, control):
    """Receiving Refs made from the phone's number are given again when the
    report is saved here, from the number it gets then."""
    prefix = f"RCV-{control}-".casefold()
    for lists in (data["item_lists"], *data["other_item_forms"].values()):
        for value in lists:
            for row in value["rows"]:
                if str(row.get("Receiving Ref") or "").casefold() \
                        .startswith(prefix):
                    row["Receiving Ref"] = ""
    return data


def kept_number(excel_path, received):
    """The Control # a restored draft that keeps its number gets: its own,
    or the next free one when another report here has it. None for other
    drafts."""
    import fsr_store
    kept = _kept(received)
    if kept is None:
        return None
    store = fsr_store.open_store(excel_path)
    if any(storage.same_key(n, kept["control"])
           for n in store.control_numbers()):
        return store.next_free_number(kept["control"])
    return kept["control"]


def adopt(excel_path, control, received, owner_edition=False):
    """A draft that keeps its number (a phone draft) was saved here as
    `control`: from now on it is the same report as on the phone. Returns
    the entry, or None for other drafts."""
    import fsr_store
    kept = _kept(received)
    if kept is None:
        return None
    phone = kept["identity"]
    sender = received.get("from") if isinstance(received.get("from"),
                                                dict) else {}
    data = load(excel_path)
    entry = data["reports"].get(phone["report_id"])
    if entry is None:
        entry = {"report_id": phone["report_id"],
                 "location_id": phone["location_id"],
                 "location_name": phone["location_name"],
                 "origin": phone["handover_origin"] or {
                     "device": sender.get("device_id", ""),
                     "control": kept["control"]},
                 "history": []}
        data["reports"][phone["report_id"]] = entry
    entry.update(control=control, state=ACTIVE,
                 revision=phone["revision"] + 1, fingerprint=None)
    entry.pop("to", None)
    _note(entry, "received", sender=sender, revision=phone["revision"],
          handover_id=received.get("handover_id"), draft=True,
          sent_as=kept["control"])
    report = fsr_store.open_store(excel_path).read_report(control)
    _bump(entry, report)
    _save(excel_path, data)
    if owner_edition:
        fsr_import.record_handover(
            excel_path, {**clean(report), **identity(entry),
                         "revision": phone["revision"]}, control,
            device=sender.get("device_id", ""),
            inspector=sender.get("inspector", ""),
            result="received_handover")
    return entry


def _receive_phone_draft(excel_path, draft, to_form):
    """(form, what the draft keeps) of a draft from the phone app."""
    import fsr_store
    phone = draft.get("report")
    found = _phone_identity(draft.get("identity"))
    if not isinstance(phone, dict) or found is None \
            or not _phone_text(phone.get("controlNo")).strip():
        raise HandoverError("The draft in the file is damaged.")
    if to_form is None:
        raise HandoverError("A draft from the phone app can only be "
                            "received in the program's window.")
    sent_as = phone["controlNo"].strip()
    entry = load(excel_path)["reports"].get(found["report_id"])
    if entry is not None:
        numbers = fsr_store.open_store(excel_path).control_numbers()
        here = next((n for n in numbers
                     if storage.same_key(n, entry.get("control"))), None)
        if here is not None:
            raise HandoverError(
                f"This PC already has this report as {here}, from an "
                "earlier hand-over. Ask for it to be saved on the phone and "
                "handed over as a completed report instead.")
    data = _without_own_refs(phone_report_data(phone), sent_as)
    return to_form(data), {"control": sent_as, "identity": found}


def _receive_draft(excel_path, payload, draft_store, owner_label, control,
                   sent_as, to_form=None):
    import fsr_drafts
    import fsr_store
    from fsr_draft_form import validate_snapshot
    from fsr_renumber import _walk_refs
    draft = payload["draft"]
    found, _ = draft_store.list()
    if any((value.get("received") or {}).get("handover_id")
           == payload["handover_id"] for value in found):
        return None             # received before: one draft, not two
    if draft["app"] == "android":
        form, keeps = _receive_phone_draft(excel_path, draft, to_form)
    else:
        form = copy.deepcopy(draft["form"])
        keeps = _kept(draft.get("kept"))
    if not validate_snapshot(form):
        raise HandoverError("The draft in the file is damaged.")
    editing = bool(draft.get("editing")) and control is not None
    if editing and sent_as and not storage.same_key(sent_as, control):
        form = _walk_refs(form, sent_as, control)
    baseline = {}
    if editing:
        store = fsr_store.open_store(excel_path)
        baseline = fsr_drafts.saved_state(store, control, False)
    value = {"version": fsr_drafts.VERSION, "id": uuid.uuid4().hex,
             "scope": draft_store.scope, "owner": draft_store.owner,
             "owner_label": owner_label, "session": "", "pid": 0,
             "process_started": None, "revision": 1,
             "changed": fsr_drafts.now_text(), "workbook": str(excel_path),
             "editing": editing, "control": control if editing else "",
             "source": draft.get("source", "excel"), "baseline": baseline,
             "form": form,
             "received": {"from": payload["from"], "at": now_text(),
                          "handover_id": payload["handover_id"]}}
    if keeps is not None and not editing:
        value["received"].update(keeps)
    draft_store.write(value)
    return value


def receive(excel_path, payload, draft_store=None, owner_label="",
            journal=None, stores=None, mysql=False, owner_edition=False,
            replace=False, to_form=None):
    """Bring a read_file() payload in. A report is added (keeping its
    number when it is free here) or updates this PC's copy when that was
    handed over from here; a draft becomes one of the signed-in account's
    drafts (`draft_store`: fsr_drafts.Store). HandoverConflict: this PC has
    its own working copy - call again with replace=True to replace it.
    `to_form(data)`: the draft form of a report in the Windows data shape
    (made by the window), needed for a draft from the phone app.
    Returns {"result", "control", "sent_as", "renumbered", "draft",
    "lists_failed"}."""
    excel_path = Path(excel_path)
    if payload["kind"] == "draft":
        if draft_store is None:
            raise HandoverError("Drafts are not available. Sign in again.")
    result = {"result": None, "control": None, "renumbered": False,
              "draft": None, "lists_failed": None,
              "sent_as": (payload.get("report") or {}).get("control_no")}
    if payload.get("report") is not None:
        result.update(_receive_report(excel_path, payload, journal, stores,
                                      mysql, owner_edition, replace))
    if payload["kind"] == "draft":
        result["draft"] = _receive_draft(
            excel_path, payload, draft_store, owner_label,
            result["control"], result["sent_as"], to_form)
        if result["result"] is None:
            result["result"] = "draft" if result["draft"] else "unchanged"
    return result
