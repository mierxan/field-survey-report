"""Loading the transaction data + the warehouse side file.

The inspection reports stay where they are (the Excel file, or MySQL) and
are only READ here. What the warehouse modules add themselves is kept in
one small JSON file beside the Excel file:

    Warehouse Data/<Excel file name>.warehouse.json
        reconciliation   append-only log of decisions (audit trail)
        case_status      append-only log of Bad Order case statuses
        settings         aging thresholds

Nothing in this file changes a report; reconciliation decisions are applied
on top of the original records every time the ledger is built.
"""

import json
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import fsr_storage

from .inventory import (ACCEPTED, CONFIRMED, DEFAULT_AGING_THRESHOLDS,
                        EXCLUDED, OPEN, PROPOSED, REJECTED, LineDecision,
                        build_inventory)
from .transactions import build_transactions

SIDE_FOLDER = "Warehouse Data"
CASE_STATUSES = ["Open", "Under Review", "Resolved"]
UNRESOLVED_CASE_STATUSES = {"Open", "Under Review"}
CASE_NOT_RECORDED = "Not recorded"

ACTIONS = {
    "propose": PROPOSED, "confirm": CONFIRMED, "reject": REJECTED,
    "exclude": EXCLUDED, "accept": ACCEPTED, "reopen": OPEN, "note": None,
}
# Decisions that change the inventory: only an owner may record them.
OWNER_ACTIONS = {"confirm", "reject", "exclude", "accept", "reopen"}


def side_file_path(excel_path):
    excel_path = Path(excel_path)
    return (excel_path.parent / SIDE_FOLDER
            / f"{excel_path.stem}.warehouse.json")


class SideStore:
    """The warehouse side file of one Excel data file."""

    def __init__(self, excel_path):
        self.path = side_file_path(excel_path)
        self._lock = threading.Lock()
        self.data = self._read()

    def _read(self):
        empty = {"version": 1, "reconciliation": [], "case_status": [],
                 "settings": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return empty
        except (OSError, ValueError) as error:
            raise ValueError(f"{self.path.name} cannot be read: {error}") \
                from error
        if not isinstance(data, dict):
            raise ValueError(f"{self.path.name} has an unexpected layout")
        for key, value in empty.items():
            data.setdefault(key, value)
        return data

    def reload(self):
        self.data = self._read()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fsr_storage.write_json_atomic(self.path, self.data)

    # ---- reconciliation ----
    def add_decision(self, subject_id, action, user="", role="user",
                     target=None, note=""):
        """Record one decision. Raises ValueError when it is not allowed."""
        if action not in ACTIONS:
            raise ValueError(f"Unknown action: {action}")
        if action in OWNER_ACTIONS and role != "owner":
            raise ValueError("Only an owner account may confirm, reject, "
                             "exclude, accept or reopen a reconciliation.")
        current = self.decisions().get(subject_id, LineDecision())
        if action == "propose" and not target:
            raise ValueError("A proposed match needs a target item.")
        if action == "confirm" and not (target or current.target):
            raise ValueError("Propose a match before confirming it.")
        if action == "reject" and current.state != PROPOSED:
            raise ValueError("There is no proposed match to reject.")
        if action in ("exclude", "note") and not note.strip():
            raise ValueError("Please write a note explaining the decision.")
        with self._lock:
            log = self.data["reconciliation"]
            entry = {
                "id": f"REC-{len(log) + 1:05d}",
                "subject": subject_id,
                "action": action,
                "target": target or (current.target
                                     if action == "confirm" else None),
                "note": note.strip(),
                "user": user,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
            log.append(entry)
            self._save()
        return entry

    def decisions(self):
        """{subject id: LineDecision} - the latest state of every subject."""
        result = {}
        for entry in self.data["reconciliation"]:
            state = ACTIONS.get(entry.get("action"))
            current = result.setdefault(entry.get("subject"), LineDecision())
            if entry.get("note"):
                current.note = entry["note"]
            if state is None:
                continue
            current.state = state
            if state in (PROPOSED, CONFIRMED):
                current.target = entry.get("target") or current.target
            elif state in (REJECTED, OPEN):
                current.target = None
        return result

    def history(self, subject_id=None):
        return [e for e in self.data["reconciliation"]
                if subject_id is None or e.get("subject") == subject_id]

    # ---- Bad Order case status ----
    def set_case_status(self, control_no, status, user="", note=""):
        if status not in CASE_STATUSES:
            raise ValueError(f"Unknown case status: {status}")
        with self._lock:
            self.data["case_status"].append({
                "control_no": control_no, "status": status,
                "note": note.strip(), "user": user,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            })
            self._save()

    def case_statuses(self):
        """{Control #: latest entry}. A report that is not listed has no
        recorded status (it is NOT counted as unresolved)."""
        latest = {}
        for entry in self.data["case_status"]:
            latest[entry.get("control_no")] = entry
        return latest

    def case_history(self, control_no):
        return [e for e in self.data["case_status"]
                if e.get("control_no") == control_no]

    # ---- settings ----
    def aging_thresholds(self):
        values = self.data["settings"].get("aging_thresholds")
        try:
            values = tuple(sorted({int(v) for v in values}))
            if values and values[0] > 0:
                return values
        except (TypeError, ValueError):
            pass
        return DEFAULT_AGING_THRESHOLDS

    def set_aging_thresholds(self, values):
        values = sorted({int(v) for v in values})
        if not values or values[0] <= 0:
            raise ValueError("Thresholds must be whole numbers above 0.")
        with self._lock:
            self.data["settings"]["aging_thresholds"] = values
            self._save()


def load_reports(excel_path, source="excel"):
    """All saved inspection reports of the chosen source."""
    if source == "mysql":
        import db_mysql
        return db_mysql.load_all_reports()
    return fsr_storage.read_all_reports(excel_path)


@dataclass
class Snapshot:
    """Everything the warehouse pages show, built from one load."""
    excel_path: Path
    source: str
    loaded_at: datetime
    reports: list
    transactions: list
    inventory: object
    side: SideStore

    @property
    def lines(self):
        return [line for tx in self.transactions for line in tx.lines]


def load_snapshot(excel_path, source="excel", as_of=None, reports=None):
    side = SideStore(excel_path)
    if reports is None:
        reports = load_reports(excel_path, source)
    transactions = build_transactions(reports)
    inventory = build_inventory(transactions, side.decisions(),
                                as_of or date.today(), side.aging_thresholds())
    return Snapshot(Path(excel_path), source, datetime.now(), reports,
                    transactions, inventory, side)


def rebuild_inventory(snapshot, as_of=None):
    """After a reconciliation decision: same reports, new ledger."""
    snapshot.side.reload()
    snapshot.inventory = build_inventory(
        snapshot.transactions, snapshot.side.decisions(),
        as_of or date.today(), snapshot.side.aging_thresholds())
    return snapshot
