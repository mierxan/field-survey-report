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
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

import fsr_storage as storage
import fsr_paths

log = logging.getLogger("fsr")

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
    import fsr_store
    store = fsr_store.open_store(excel_path)
    if store.kind == "sqlite":
        import fsr_sqlite_store
        return storage.ControlKeyed({
            str(row["Control #"]).strip(): str(row.get("Last Saved"))
            for row in store._headers(fsr_sqlite_store.MAIN)
            if row.get("Control #")
        })
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


_MISSING = object()


def _change_value(value):
    """A stable, display-ready value for one side of an import change."""
    if value is _MISSING:
        return "(not present)"
    if value is None:
        return "(blank)"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value)
    return text if text else "(blank)"


def report_changes(previous, imported):
    """Return every field changed between an Owner copy and an import.

    Each entry has a machine-readable path plus display-ready ``previous``
    and ``imported`` values.  Lists include a count change and then the
    individual added, removed, or edited values, so an item-list expansion
    cannot be hidden behind a single ``Updated`` count.
    """
    result = []

    def add(path, before, after):
        result.append({
            "path": path,
            "previous": _change_value(before),
            "imported": _change_value(after),
        })

    def walk(before, after, path):
        if before is _MISSING and isinstance(after, dict):
            for key in sorted(after, key=str.casefold):
                walk(_MISSING, after[key], path + (str(key),))
            return
        if after is _MISSING and isinstance(before, dict):
            for key in sorted(before, key=str.casefold):
                walk(before[key], _MISSING, path + (str(key),))
            return
        if before is _MISSING and isinstance(after, list):
            add(path + ("count",), 0, len(after))
            for index, value in enumerate(after):
                walk(_MISSING, value, path + (index,))
            return
        if after is _MISSING and isinstance(before, list):
            add(path + ("count",), len(before), 0)
            for index, value in enumerate(before):
                walk(value, _MISSING, path + (index,))
            return
        if type(before) is not type(after):
            add(path, before, after)
            return
        if isinstance(before, dict):
            for key in sorted(set(before) | set(after), key=str.casefold):
                walk(before.get(key, _MISSING), after.get(key, _MISSING),
                     path + (str(key),))
            return
        if isinstance(before, list):
            if len(before) != len(after):
                add(path + ("count",), len(before), len(after))
            for index in range(max(len(before), len(after))):
                left = before[index] if index < len(before) else _MISSING
                right = after[index] if index < len(after) else _MISSING
                walk(left, right, path + (index,))
            return
        if before != after:
            add(path, before, after)

    walk(previous, imported, ())
    return result


def _update_changes(store, ledger, plan):
    """report_changes() for every report this import will update.

    Built from the final plan, so a report sent twice in one file is compared
    in the copy that is actually saved.  Several updates share one read of
    the workbook or database instead of loading it once per report.
    """
    updates = [(item["report"], item["key"]) for item in plan
               if item["editing"]]
    if not updates:
        return []
    if len(updates) == 1:
        read = store.read_report
    else:
        current = storage.ControlKeyed(
            (saved["control_no"], saved) for saved in store.read_all_reports())
        read = current.get
    changes = []
    for report, key in updates:
        previous = copy.deepcopy(read(report["control_no"]) or {})
        # Last Saved belongs to the sending copy's import identity and is
        # kept in the ledger, rather than in the Owner's report row.
        previous.setdefault("last_saved",
                            ledger.get(key, {}).get("phone_saved") or "")
        changes.append({
            "control": report["control_no"],
            "fields": report_changes(previous, report),
        })
    return changes


# ---------- permanent identity, revisions and import history ----------
#
# A report that carries a permanent "report_id" (and its file a
# "location_id") is recognised by location + report, whatever its Control #,
# phone or Location text. Each copy carries a "revision"; a fingerprint of
# its content tells whether a revision is what was received before.
#
#   new report              -> added (renumbered when its number is taken)
#   same content            -> unchanged
#   older revision          -> left alone (older_revisions)
#   same revision, other
#     content               -> refused (invalid_revisions)
#   newer revision          -> waits for the Owner (pending_review); the
#                              Owner's copy is not changed until accepted
#
# Reports without a report_id keep the device + Control # matching above.
# Every decision is added to the import history, which is never rewritten.

ID_PREFIX = "id:"
HISTORY_SUFFIX = "_import_history.jsonl"
REVIEW_SUFFIX = "_import_review.json"
# Carried by a report handed over to another inspector (fsr_handover): it
# keeps the location where it was first handed over, and the phone or PC +
# Control # it had there.
HANDOVER_KEYS = ("location_id", "location_name", "handover_origin")
# Bookkeeping of a report, not what the inspector wrote: never compared,
# and not part of its fingerprint.
_NOT_CONTENT = frozenset({"control_no", "last_saved", "revision",
                          "report_id", "incident_error", *HANDOVER_KEYS})


def identity_key(location_id, report_id):
    """The ledger key of a report with a permanent identity."""
    return ID_PREFIX + json.dumps([str(location_id), str(report_id)],
                                  ensure_ascii=False)


def report_location(data, report):
    """(location id, location name) of a report of this file. A handed-over
    report names its own location (where it was first handed over), so it
    stays one report whichever location sends it."""
    own = str(report.get("location_id") or "").strip()
    if own:
        return own, str(report.get("location_name") or "").strip()
    return (str(data.get("location_id") or "").strip(),
            str(data.get("location_name") or "").strip())


def report_identity(data, report):
    """identity_key() of a report of this file, or None (no report_id)."""
    report_id = str(report.get("report_id") or "").strip()
    if not report_id:
        return None
    return identity_key(report_location(data, report)[0], report_id)


def _handover_origin(report):
    """[(device, Control #)] where a handed-over report was before."""
    origin = report.get("handover_origin")
    if not isinstance(origin, dict):
        return []
    device = str(origin.get("device") or "").strip()
    control = str(origin.get("control") or "").strip()
    return [(device, control)] if device and control else []


def _as_revision(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except ValueError:
        return None
    return number if number >= 0 else None


def report_revision(report):
    """The revision number a report was sent with (None: not given)."""
    return _as_revision(report.get("revision"))


def report_fingerprint(report):
    """One value for what the inspector wrote in a report: its Control #,
    Last Saved time, revision and identity are left out, so the same
    content saved again (or kept under another number) is the same."""
    return _whole_fingerprint({key: value for key, value in report.items()
                               if key not in _NOT_CONTENT})


def _whole_fingerprint(report):
    """The fingerprint of the whole report as it was sent (how the first
    Phase 7 build recorded it; still recognised)."""
    text = json.dumps(report, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def history_path(excel_path):
    excel_path = Path(excel_path)
    return (fsr_paths.json_dir_for_workbook(excel_path)
            / f"{excel_path.stem}{HISTORY_SUFFIX}")


def review_path(excel_path):
    excel_path = Path(excel_path)
    return (fsr_paths.json_dir_for_workbook(excel_path)
            / f"{excel_path.stem}{REVIEW_SUFFIX}")


def load_import_history(excel_path):
    """Every recorded import decision, oldest first."""
    path = history_path(excel_path)
    if not path.exists():
        return []
    events = []
    with open(path, "r", encoding="utf-8") as file:
        for number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                # a line cut off by a power failure; the others still count
                log.warning("Import history line %d of %s is unreadable",
                            number, path)
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def _append_history(excel_path, events):
    """Add events at the end of the history; nothing before is changed."""
    if not events:
        return
    path = history_path(excel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(event, ensure_ascii=False, default=str) + "\n"
                   for event in events)
    torn = False
    if path.exists() and path.stat().st_size:
        with open(path, "rb") as file:
            file.seek(-1, os.SEEK_END)
            torn = file.read(1) != b"\n"
    with open(path, "a", encoding="utf-8", newline="\n") as file:
        if torn:            # an earlier append was cut off mid-line
            file.write("\n")
        file.write(text)
        file.flush()
        os.fsync(file.fileno())


def load_review(excel_path):
    """{"bases": {key: last accepted revision},
    "pending": {key: revision waiting for the Owner}}."""
    path = review_path(excel_path)
    review = {}
    if path.exists():
        try:
            review = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise MasterDataError(
                f"The import review record could not be read:\n{path}\n"
                f"{error}") from error
    if not isinstance(review, dict):
        review = {}
    for part in ("bases", "pending"):
        if not isinstance(review.get(part), dict):
            review[part] = {}
    return review


def _save_review(excel_path, review):
    path = review_path(excel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json_atomic(path, review)


def _revision_decision(entry, pending, revision, fingerprint, also=()):
    """What to do with a received copy of a report already imported.
    `also`: other fingerprints the same copy may have been recorded with."""
    known = [(_as_revision(entry.get("revision")), entry.get("fingerprint"))]
    if pending:
        known.append((_as_revision(pending.get("revision")),
                      pending.get("fingerprint")))
    mine = {fingerprint, *also}
    if any(seen in mine for _, seen in known if seen):
        return "unchanged"
    if revision is not None:
        if any(revision == number for number, _ in known):
            return "invalid"
        newest = max((number for number, _ in known if number is not None),
                     default=None)
        if newest is not None and revision < newest:
            return "older"
    return "review"


def _move_ledger_entries(excel_path, moved):
    """Put ledger entries kept by phone + Control # under their permanent
    identity - one write."""
    ledger = load_ledger(excel_path)
    for old_key, (new_key, entry) in moved.items():
        ledger.pop(old_key, None)
        ledger[new_key] = entry
    storage.write_json_atomic(ledger_path(excel_path), ledger)


def _identity_winners(data):
    """{identity: index of the copy kept} - a report sent twice in one file
    counts once, in its highest revision (the later copy when equal)."""
    winners = {}
    for index, report in enumerate(data["reports"]):
        identity = report_identity(data, report)
        if identity is None:
            continue
        earlier = winners.get(identity)
        if earlier is not None:
            old = report_revision(data["reports"][earlier])
            new = report_revision(report)
            if old is not None and new is not None and new < old:
                continue
        winners[identity] = index
    return winners


# ---------- three-way review ----------

def path_text(path):
    """("general_information", "so_number") -> "general_information.so_number",
    ("findings_and_remarks", 0) -> "findings_and_remarks[0]"."""
    text = ""
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else str(part)
    return text


def _get(value, path):
    for part in path:
        if isinstance(part, int):
            if not isinstance(value, list) or part >= len(value):
                return _MISSING
            value = value[part]
        else:
            if not isinstance(value, dict) or part not in value:
                return _MISSING
            value = value[part]
    return value


def _set(target, path, value):
    """Put `value` at `path`; False when the place does not exist."""
    *parents, last = path
    for part in parents:
        target = _get(target, (part,))
        if target is _MISSING:
            return False
    if isinstance(last, int):
        if not isinstance(target, list) or last >= len(target) \
                or value is _MISSING:
            return False
        target[last] = copy.deepcopy(value)
        return True
    if not isinstance(target, dict):
        return False
    if value is _MISSING:
        target.pop(last, None)
    else:
        target[last] = copy.deepcopy(value)
    return True


def _anchor(path):
    """A change of a list's length concerns the whole list."""
    return path[:-1] if path and path[-1] == "count" else path


def _overlap(a, b):
    a, b = _anchor(a), _anchor(b)
    size = min(len(a), len(b))
    return a[:size] == b[:size]


def _content_changes(before, after):
    keys = (set(before) & set(after)) - _NOT_CONTENT
    return report_changes({key: before[key] for key in keys},
                          {key: after[key] for key in keys})


class RevisionComparison:
    """What changed since the last accepted revision, and by whom.

    user_only / owner_only / conflicts: path_text() of the fields.
    fields: one dict per field for the review screen - path, kind ("user",
    "owner", "conflict"), and the base, user and owner values to show."""

    def __init__(self, user_only, owner_only, conflicts, fields, has_base):
        self.user_only = user_only
        self.owner_only = owner_only
        self.conflicts = conflicts
        self.fields = fields
        self.has_base = has_base

    def __repr__(self):
        return (f"RevisionComparison(user_only={self.user_only!r}, "
                f"owner_only={self.owner_only!r}, "
                f"conflicts={self.conflicts!r})")


def compare_revisions(base, user, owner):
    """Three-way comparison of the last accepted revision (`base`), the
    revision just received (`user`) and the Owner's copy now (`owner`).
    Without a base nobody can tell who changed what, so every difference
    is a conflict."""
    def show(value):
        return _change_value(value)

    if base is None:
        fields = [{"path": change["path"], "kind": "conflict",
                   "base": "(unknown)", "user": change["imported"],
                   "owner": change["previous"]}
                  for change in _content_changes(owner, user)]
        return RevisionComparison(
            [], [], [path_text(f["path"]) for f in fields], fields, False)

    user_changes = [c["path"] for c in _content_changes(base, user)]
    owner_changes = [c["path"] for c in _content_changes(base, owner)]
    clash_user, clash_owner, agreed = set(), set(), set()
    for mine in user_changes:
        for theirs in owner_changes:
            if not _overlap(mine, theirs):
                continue
            common = min(_anchor(mine), _anchor(theirs), key=len)
            if _get(user, common) == _get(owner, common):
                agreed.update((mine, theirs))      # both made the same edit
            else:
                clash_user.add(mine)
                clash_owner.add(theirs)

    fields = []

    def field(path, kind):
        fields.append({"path": path, "kind": kind,
                       "base": show(_get(base, path)),
                       "user": show(_get(user, path)),
                       "owner": show(_get(owner, path))})

    user_only = [p for p in user_changes
                 if p not in clash_user and p not in agreed]
    owner_only = [p for p in owner_changes
                  if p not in clash_owner and p not in agreed]
    conflicts = []
    for path in [*user_changes, *owner_changes]:
        if (path in clash_user or path in clash_owner) \
                and path not in conflicts:
            conflicts.append(path)
    for path in user_only:
        field(path, "user")
    for path in owner_only:
        field(path, "owner")
    for path in conflicts:
        field(path, "conflict")
    return RevisionComparison(
        [path_text(p) for p in user_only], [path_text(p) for p in owner_only],
        [path_text(p) for p in conflicts], fields, True)


def merged_revision(base, user, owner):
    """The received revision, keeping the Owner's own changes to fields the
    user did not touch. Where both changed a field, the user's value is
    taken (that is what accepting the revision means)."""
    result = copy.deepcopy(user)
    if base is None:
        return result
    for item in compare_revisions(base, user, owner).fields:
        if item["kind"] != "owner":
            continue
        anchor = _anchor(item["path"])
        if not _set(result, anchor, _get(owner, anchor)):
            log.warning("Owner change at %s could not be kept",
                        path_text(item["path"]))
    return result


# ---------- import ------------------------------------------

def _new_summary():
    return {"added": [], "updated": [], "unchanged": [], "renumbered": [],
            "conflicts": [], "deleted_here": [], "pending_review": [],
            "invalid_revisions": [], "older_revisions": [], "accepted": [],
            "backup": None, "saved_reports": [], "changes": [],
            "item_lists_failed": None}


def _backup(excel_path, store):
    """One checked copy of the workbook or database before a write."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if store.kind == "sqlite":
        # beside the workbook in Documents, like the copy of a workbook
        # (the database itself is in Local AppData)
        target = excel_path.with_name(
            f"{excel_path.stem}_before_import_{stamp}"
            f"{store.db_path.suffix}")
        store.copy_to(target)
        return str(target)
    if excel_path.exists():
        target = excel_path.with_name(
            f"{excel_path.stem}_before_import_{stamp}{excel_path.suffix}")
        import fsr_backup
        fsr_backup.verified_copy(excel_path, target)    # checked copy
        return str(target)
    return None


def _ledger_entry(item, stamp, imported):
    return {"phone_control": item["phone_no"], "inspector": item["inspector"],
            "phone_saved": item["phone_saved"], "pc_saved": str(stamp),
            "imported": imported, **item["extra"]}


def _base_of(item):
    """The accepted revision kept for the next three-way review."""
    if not item["extra"].get("report_id"):
        return None
    return {"revision": item["extra"].get("revision"),
            "fingerprint": item["extra"].get("fingerprint"),
            "report": item.get("base_report")}


def _write_plan(excel_path, store, plan, summary, journal, stores, mysql,
                progress, review, events):
    """Write the planned reports in ONE workbook/database write, then their
    side files, the ledger, the review record and the history."""
    import fsr_save_journal as journal_module

    # One Last Saved time for the whole import, chosen before the write:
    # it is how the record recognises the write afterwards.
    now = datetime.now()
    stamp = now.replace(microsecond=now.microsecond // 1000 * 1000)
    imported = now.isoformat(timespec="seconds")
    records = None
    if journal is not None:
        records = journal.begin_batch(
            [(item["report"], item["editing"],
              journal_module.steps_for(item["report"], False, mysql)
              + ["import_ledger"],
              {"import": {"key": item["key"],
                          "entry": _ledger_entry(item, stamp, imported),
                          "base": _base_of(item),
                          "clears_pending": bool(item.get("clears_pending")),
                          "event": item["event"]}})
             for item in plan],
            now=stamp)

    progress(f"Writing {len(plan)} report(s) into the Excel file ...", 0,
             len(plan))
    write = (lambda: store.write_reports(
        [(item["report"], item["editing"], stamp) for item in plan]))
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
            # Broad on purpose: the error being raised is the one that
            # matters; a failing clean-up must not replace it.
            except Exception:
                log.debug("Import records not discarded", exc_info=True)
        raise

    entries = {}
    written = []
    review_changed = False
    for number, (item, result) in enumerate(zip(plan, results), start=1):
        control = result["control"]
        report = item["report"]
        report["control_no"] = control
        progress(f"Writing the files of {control} ...", number, len(plan))
        write_side_files(excel_path, control, report)
        entries[item["key"]] = dict(_ledger_entry(item, stamp, imported),
                                    control=control)
        base = _base_of(item)
        if base is not None:
            base_report = copy.deepcopy(base["report"] or report)
            base_report["control_no"] = control
            review["bases"][item["key"]] = dict(base, control=control,
                                                report=base_report)
            review_changed = True
        if item.get("clears_pending"):
            review["pending"].pop(item["key"], None)
            review_changed = True
        summary[item["list"]].append(control)
        summary["saved_reports"].append(report)
        written.append(dict(item["event"], owner_control=control,
                            time=imported))
    progress("Updating the record of imported reports ...", len(plan),
             len(plan))
    record_imports(excel_path, entries)
    if review_changed:
        _save_review(excel_path, review)
    _append_history(excel_path, [*written, *events])

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


def repair_import_record(excel_path, key, entry, info, data):
    """What an import cut off after its workbook write still owes for one
    report: its ledger entry, its accepted revision and its history event
    (called by the save record; safe to run twice)."""
    record_imports(excel_path, {key: entry})
    base = info.get("base")
    if base is not None or info.get("clears_pending"):
        review = load_review(excel_path)
        if base is not None:
            report = copy.deepcopy(base.get("report") or data)
            report["control_no"] = entry["control"]
            review["bases"][key] = dict(base, control=entry["control"],
                                        report=report)
        pending = review["pending"].get(key)
        if pending is not None and \
                pending.get("fingerprint") == entry.get("fingerprint"):
            review["pending"].pop(key)
        _save_review(excel_path, review)
    event = info.get("event")
    if event and not any(seen.get("id") == event.get("id")
                         for seen in load_import_history(excel_path)):
        _append_history(excel_path,
                        [dict(event, owner_control=entry["control"])])


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
    import fsr_store

    progress = progress or _quiet
    excel_path = Path(excel_path)
    store = fsr_store.open_store(excel_path)
    device = str(data["device_id"]).strip()
    inspector = str(data.get("inspector") or "").strip()
    ledger = load_ledger(excel_path)
    review = load_review(excel_path)
    summary = _new_summary()
    received = datetime.now().isoformat(timespec="seconds")

    total = len(data["reports"])
    progress(f"Checking {total} report(s) against the Excel file ...", 0,
             total)
    saved = _last_saved_by_control(excel_path)
    # Numbers of the PO-linked Withdrawal workbook: never reused by an import.
    elsewhere = store.withdrawal_numbers()
    taken_elsewhere = {storage.control_key(n) for n in elsewhere}
    # numbers given to new reports of this file
    assigned = storage.ControlKeyed()
    plan = []          # the reports to write (dicts, see below)
    planned_keys = {}  # ledger key -> its place in plan
    events = []        # decisions that write no report
    review_changed = False
    moved = {}         # ledger key by phone + Control # -> (identity, entry)
    winners = _identity_winners(data)

    def event(result, original, owner_control, fingerprint, revision,
              **more):
        place, place_name = report_location(data, original)
        return {"id": uuid.uuid4().hex, "time": received, "result": result,
                "owner_control": owner_control,
                "source_control": str(original.get("control_no") or "")
                .strip(),
                "device": device, "location_id": place,
                "location_name": place_name, "inspector": inspector,
                "report_id": str(original.get("report_id") or "").strip(),
                "revision": revision, "fingerprint": fingerprint,
                "exported_at": data.get("exported_at"), **more}

    for index, original in enumerate(data["reports"]):
        # A copy: renumbering must never change the caller's data, so the same
        # data can be imported again (and its master lists read) unchanged.
        report = copy.deepcopy(original)
        phone_no = str(report["control_no"]).strip()
        phone_saved = str(report.get("last_saved") or "")
        fingerprint = report_fingerprint(original)
        revision = report_revision(original)
        identity = report_identity(data, original)
        extra = {}
        editing = False

        if identity is not None:
            if winners[identity] != index:
                continue            # a copy superseded later in this file
            key = identity
            place, place_name = report_location(data, original)
            extra = {"report_id": str(original["report_id"]).strip(),
                     "location_id": place,
                     "location_name": place_name, "device": device,
                     "revision": revision, "fingerprint": fingerprint}
            entry = ledger.get(key)
            legacy = None
            if entry is None:
                # this phone's number, then - for a handed-over report -
                # the phone or PC and number it was handed over from
                for owner, number in [(device, phone_no),
                                      *_handover_origin(original)]:
                    old_key = _ledger_key(ledger, owner, number)
                    if old_key not in moved and old_key in ledger:
                        legacy = ledger[old_key]
                        break
            if legacy is not None:
                # Imported before the phone sent identities: still found by
                # phone + Control #, and its record moves to the permanent
                # identity. Unchanged since then: that copy is the accepted
                # revision. Changed: nobody can tell who changed what, so it
                # waits for the Owner with every difference listed.
                same = phone_saved == legacy.get("phone_saved")
                entry = dict(legacy, **extra)
                if not same:
                    entry.update(revision=None, fingerprint=None)
                moved[old_key] = (key, entry)
                local = entry["control"]
                if same and local in saved:
                    base_report = copy.deepcopy(report)
                    _renumbered(base_report, phone_no, saved.name(local))
                    review["bases"][key] = {
                        "control": saved.name(local), "revision": revision,
                        "fingerprint": fingerprint, "report": base_report}
                    review_changed = True
            if entry is not None:
                local = entry["control"]
                # also as it reads under the Owner's number: a copy that was
                # renumbered elsewhere (its Receiving Refs follow) is the same
                as_here = copy.deepcopy(original)
                _renumbered(as_here, phone_no, str(local))
                decision = _revision_decision(
                    entry, review["pending"].get(key), revision, fingerprint,
                    also=(_whole_fingerprint(original),
                          report_fingerprint(as_here)))
                result = {"unchanged": "unchanged", "older": "older_revision",
                          "invalid": "invalid_revision"}.get(decision)
                if result is None and local not in saved:
                    result = "deleted_here"
                if result is not None:
                    summary[{"unchanged": "unchanged",
                             "older_revision": "older_revisions",
                             "invalid_revision": "invalid_revisions",
                             "deleted_here": "deleted_here"}[result]
                            ].append(local)
                    events.append(event(result, original, local, fingerprint,
                                        revision))
                    continue
                # A newer revision: kept for the Owner's review; the
                # Owner's copy stays as it is until it is accepted.
                local = saved.name(local)
                _renumbered(report, phone_no, local)
                review["pending"][key] = {
                    "control": local, "source_control": phone_no,
                    "phone_saved": phone_saved, "received": received,
                    "inspector": inspector, "previous_revision":
                        _as_revision(entry.get("revision")),
                    **extra, "report": report}
                review_changed = True
                summary["pending_review"].append(local)
                events.append(event(
                    "pending_review", original, local, fingerprint, revision,
                    previous_revision=_as_revision(entry.get("revision"))))
                continue
        else:
            key = _ledger_key(ledger, device, phone_no)
            if key not in planned_keys:
                # the same phone number in another letter case, earlier in
                # this file, is the same report
                for planned in planned_keys:
                    if planned.startswith(ID_PREFIX):
                        continue
                    owner, _, number = planned.rpartition("|")
                    if owner == device and storage.control_key(
                            number) == storage.control_key(phone_no):
                        key = planned
                        break
            if key in planned_keys:
                # The same phone report twice in one file: as before, the
                # later one is what the PC keeps - one report, not two.
                earlier = plan[planned_keys[key]]
                _renumbered(report, phone_no, earlier["report"]["control_no"])
                earlier.update(report=report, phone_no=phone_no,
                               phone_saved=phone_saved,
                               event=event(
                                   earlier["event"]["result"], original, None,
                                   fingerprint, revision,
                                   renumbered=earlier["event"]["renumbered"]))
                continue
            entry = ledger.get(key)
            if entry is not None:
                local = entry["control"]
                result = None
                if phone_saved == entry.get("phone_saved"):
                    result, listed = "unchanged", "unchanged"
                elif local not in saved:
                    result, listed = "deleted_here", "deleted_here"
                elif saved[local] != entry.get("pc_saved"):
                    result, listed = "conflict", "conflicts"
                if result is not None:
                    summary[listed].append(local)
                    events.append(event(result, original, local, fingerprint,
                                        revision))
                    continue
                editing = True
                local = saved.name(local)   # as it is spelled in the workbook
                _renumbered(report, phone_no, local)

        renumbered = False
        if not editing:
            local = phone_no
            if local in saved or local in assigned or \
                    storage.control_key(local) in taken_elsewhere:
                # The report keeps the initials of the inspector who made it.
                local = storage.next_control_number(
                    [*saved, *elsewhere, *assigned],
                    storage.control_initials_of(phone_no))
                _renumbered(report, phone_no, local)
                summary["renumbered"].append((phone_no, local))
                renumbered = True
        assigned[local] = True
        planned_keys[key] = len(plan)
        result = "updated" if editing else "added"
        plan.append({
            "report": report, "editing": editing, "key": key,
            "phone_no": phone_no, "phone_saved": phone_saved,
            "inspector": inspector, "extra": extra, "list": result,
            "base_report": None,
            "event": event(result, original, None, fingerprint, revision,
                           renumbered=renumbered)})

    if moved:
        _move_ledger_entries(excel_path, moved)
    if not plan:
        if review_changed:
            _save_review(excel_path, review)
        _append_history(excel_path, events)
        return summary

    summary["changes"] = _update_changes(store, ledger, plan)
    summary["backup"] = _backup(excel_path, store)
    if review_changed:
        # the waiting revisions are kept even if the write below fails
        _save_review(excel_path, review)
    _write_plan(excel_path, store, plan, summary, journal, stores, mysql,
                progress, review, events)

    if on_saved is not None:
        for report in summary["saved_reports"]:
            on_saved(report)
    return summary


# ---------- the Owner's review ----------

def pending_reviews(excel_path):
    """The revisions waiting for the Owner, oldest first."""
    review = load_review(excel_path)
    waiting = []
    for key, pending in review["pending"].items():
        waiting.append({
            "key": key, "control": pending.get("control"),
            "source_control": pending.get("source_control"),
            "location_id": pending.get("location_id") or "",
            "location_name": pending.get("location_name") or "",
            "inspector": pending.get("inspector") or "",
            "revision": pending.get("revision"),
            "previous_revision": pending.get("previous_revision"),
            "received": pending.get("received") or "",
            "has_base": key in review["bases"]})
    waiting.sort(key=lambda item: (item["received"], str(item["control"])))
    return waiting


def review_comparison(excel_path, key):
    """compare_revisions() of a waiting revision against the Owner's copy
    now. None when the Owner's copy is no longer in the file."""
    import fsr_store
    review = load_review(excel_path)
    pending = review["pending"].get(key)
    if pending is None:
        raise MasterDataError("This change is no longer waiting for review.")
    owner = fsr_store.open_store(excel_path).read_report(pending["control"])
    if owner is None:
        return None
    base = (review["bases"].get(key) or {}).get("report")
    return compare_revisions(base, pending["report"], owner)


def _review_event(pending, result, owner_control):
    return {"id": uuid.uuid4().hex,
            "time": datetime.now().isoformat(timespec="seconds"),
            "result": result, "owner_control": owner_control,
            "source_control": pending.get("source_control"),
            "device": pending.get("device"),
            "location_id": pending.get("location_id") or "",
            "location_name": pending.get("location_name") or "",
            "inspector": pending.get("inspector") or "",
            "report_id": pending.get("report_id") or "",
            "revision": pending.get("revision"),
            "fingerprint": pending.get("fingerprint"),
            "previous_revision": pending.get("previous_revision")}


def accept_revision(excel_path, key, journal=None, stores=None, mysql=False,
                    progress=None, on_saved=None):
    """Apply a waiting revision to the Owner's copy: the user's changes,
    keeping the Owner's own changes to fields the user did not touch."""
    import fsr_store
    progress = progress or _quiet
    excel_path = Path(excel_path)
    store = fsr_store.open_store(excel_path)
    review = load_review(excel_path)
    pending = review["pending"].get(key)
    if pending is None:
        raise MasterDataError("This change is no longer waiting for review.")
    saved = _last_saved_by_control(excel_path)
    if pending["control"] not in saved:
        raise MasterDataError(
            f"Report {pending['control']} is no longer in this file, so the "
            "change cannot be applied. Choose Keep My Version instead.")
    control = saved.name(pending["control"])
    owner = store.read_report(control)
    base = (review["bases"].get(key) or {}).get("report")
    report = merged_revision(base, pending["report"], owner)
    report["control_no"] = control
    extra = {name: pending.get(name) for name in (
        "report_id", "location_id", "location_name", "device", "revision",
        "fingerprint")}
    item = {"report": report, "editing": True, "key": key,
            "phone_no": pending.get("source_control") or control,
            "phone_saved": pending.get("phone_saved") or "",
            "inspector": pending.get("inspector") or "", "extra": extra,
            "list": "accepted", "clears_pending": True,
            "base_report": pending["report"],
            "event": _review_event(pending, "accepted", control)}
    summary = _new_summary()
    summary["backup"] = _backup(excel_path, store)
    _write_plan(excel_path, store, [item], summary, journal, stores, mysql,
                progress, review, [])
    # a report the Owner handed over is back: it can be edited here again
    import fsr_handover
    try:
        fsr_handover.came_back(excel_path, pending.get("report_id"), control,
                               pending.get("revision"))
    except fsr_handover.HandoverError:
        log.exception("The hand-over record could not be updated")
    if on_saved is not None:
        for saved_report in summary["saved_reports"]:
            on_saved(saved_report)
    return summary


def record_handover(excel_path, report, control, device="", inspector="",
                    result="handed_over"):
    """The Owner handed report `control` over to an inspector, or received
    it from one directly (fsr_handover). Its import record and accepted
    revision become this copy, so when it comes back in a Master Data file
    it is recognised (unchanged, older, or waiting for review) instead of
    arriving as a second report."""
    key = report_identity({}, report)
    if key is None:
        return
    excel_path = Path(excel_path)
    now = datetime.now().isoformat(timespec="seconds")
    place, place_name = report_location({}, report)
    revision = report_revision(report)
    fingerprint = report_fingerprint(report)
    ledger = load_ledger(excel_path)
    entry = dict(ledger.get(key) or {})
    entry.update(control=control,
                 phone_control=str(report.get("control_no") or control),
                 inspector=inspector or entry.get("inspector", ""),
                 phone_saved=str(report.get("last_saved") or ""),
                 imported=now, report_id=str(report["report_id"]).strip(),
                 location_id=place, location_name=place_name,
                 device=device or entry.get("device", ""),
                 revision=revision, fingerprint=fingerprint)
    entry.setdefault("pc_saved", "")
    record_imports(excel_path, {key: entry})
    review = load_review(excel_path)
    base_report = copy.deepcopy(report)
    base_report["control_no"] = control
    review["bases"][key] = {"control": control, "revision": revision,
                            "fingerprint": fingerprint, "report": base_report}
    pending = review["pending"].get(key)
    if pending is not None and (_as_revision(pending.get("revision")) or 0) \
            <= (revision or 0):
        review["pending"].pop(key)      # this copy is as new or newer
    _save_review(excel_path, review)
    _append_history(excel_path, [{
        "id": uuid.uuid4().hex, "time": now, "result": result,
        "owner_control": control,
        "source_control": str(report.get("control_no") or ""),
        "device": device, "location_id": place, "location_name": place_name,
        "inspector": inspector, "report_id": entry["report_id"],
        "revision": revision, "fingerprint": fingerprint}])


def keep_owner_version(excel_path, key):
    """Leave the Owner's copy as it is. The revision counts as received, so
    sending it again changes nothing, and the next one is compared with it."""
    excel_path = Path(excel_path)
    review = load_review(excel_path)
    pending = review["pending"].get(key)
    if pending is None:
        raise MasterDataError("This change is no longer waiting for review.")
    ledger = load_ledger(excel_path)
    entry = dict(ledger.get(key) or {})
    entry.update(revision=pending.get("revision"),
                 fingerprint=pending.get("fingerprint"),
                 phone_saved=pending.get("phone_saved") or "")
    entry.setdefault("control", pending["control"])
    record_imports(excel_path, {key: entry})
    review["bases"][key] = {
        "control": entry["control"], "revision": pending.get("revision"),
        "fingerprint": pending.get("fingerprint"),
        "report": pending["report"]}
    review["pending"].pop(key)
    _save_review(excel_path, review)
    _append_history(excel_path,
                    [_review_event(pending, "kept_owner", entry["control"])])


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
