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
its first save, as any new report does.

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


def _receive_draft(excel_path, payload, draft_store, owner_label, control,
                   sent_as):
    import fsr_drafts
    import fsr_store
    from fsr_draft_form import validate_snapshot
    from fsr_renumber import _walk_refs
    draft = payload["draft"]
    found, _ = draft_store.list()
    if any((value.get("received") or {}).get("handover_id")
           == payload["handover_id"] for value in found):
        return None             # received before: one draft, not two
    form = copy.deepcopy(draft["form"])
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
    draft_store.write(value)
    return value


def receive(excel_path, payload, draft_store=None, owner_label="",
            journal=None, stores=None, mysql=False, owner_edition=False,
            replace=False):
    """Bring a read_file() payload in. A report is added (keeping its
    number when it is free here) or updates this PC's copy when that was
    handed over from here; a draft becomes one of the signed-in account's
    drafts (`draft_store`: fsr_drafts.Store). HandoverConflict: this PC has
    its own working copy - call again with replace=True to replace it.
    Returns {"result", "control", "sent_as", "renumbered", "draft",
    "lists_failed"}."""
    excel_path = Path(excel_path)
    if payload["kind"] == "draft":
        if payload["draft"]["app"] != APP:
            raise HandoverError(
                "This unfinished report was started on the Android app, so "
                "it can only be continued on a phone with the Field Survey "
                "Report app. A completed report can be received on any PC "
                "or phone.")
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
            result["control"], result["sent_as"])
        if result["result"] is None:
            result["result"] = "draft" if result["draft"] else "unchanged"
    return result
