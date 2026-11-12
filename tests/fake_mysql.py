"""An in-memory MySQL server for tests: several copies of the program can
connect to one FakeServer, as several PCs connect to one database.

It keeps reports the way db_mysql does: by Control # (case-insensitive, like
the real column), a write replaces the whole report, numbers come back as
MySQL shows them ('0.00' is stored as a number and read back as '0').
"""
import copy
from decimal import Decimal, InvalidOperation

import fsr_storage as s

NUMERIC = set(s.NUMERIC_ITEM_HEADERS) | set(s.MONEY_ITEM_HEADERS)


def _as_mysql_shows(report):
    """What load_report() would give back for a saved report."""
    report = copy.deepcopy(report)
    report.pop("other_item_forms", None)        # not stored in MySQL
    report.pop("last_saved", None)
    for section in report.get("item_lists") or []:
        for row in section.get("rows") or []:
            for field in NUMERIC:
                text = str(row.get(field) or "").strip()
                if not text:
                    continue
                try:
                    number = Decimal(text.replace(",", ""))
                except InvalidOperation:
                    continue
                row[field] = format(number.normalize(), "f")
    return report


class FakeServer:
    """The database itself (shared by every connection)."""

    def __init__(self):
        self.reports = {}               # control key -> report
        self.locks = {}                 # control key -> connection
        self.down = False
        self.writes = []                # Control #s written, in order
        self.master_lists = 0

    def put(self, report):
        """Put a report straight into the database (as another PC did)."""
        self.reports[s.control_key(report["control_no"])] = \
            _as_mysql_shows(report)

    def get(self, control):
        return self.reports.get(s.control_key(control))

    def client(self, enabled=True):
        return FakeDB(self, enabled)


class FakeConnection:
    def __init__(self, server):
        self.server = server
        self.pending = {}
        self.closed = False
        self.database = "field_survey_test"

    def commit(self):
        for key, report in self.pending.items():
            self.server.reports[key] = report
            self.server.writes.append(report["control_no"])
        self.pending = {}

    def rollback(self):
        self.pending = {}

    def close(self):
        self.rollback()
        for key in [k for k, owner in self.server.locks.items()
                    if owner is self]:
            del self.server.locks[key]          # as MySQL does on disconnect
        self.closed = True


class FakeDB:
    """What the program sees as the db_mysql module."""

    def __init__(self, server, enabled=True):
        self.server = server
        self.enabled = enabled
        self.connections = 0

    def is_enabled(self):
        return self.enabled

    def connect(self, config=None):
        if self.server.down:
            error = OSError("Can't connect to MySQL server on 'localhost'")
            error.errno = 2003
            raise error
        self.connections += 1
        return FakeConnection(self.server)

    @staticmethod
    def explain_error(error):
        return str(error)

    @staticmethod
    def is_unreachable(error):
        return getattr(error, "errno", None) == 2003

    def test_connection(self, config=None):
        if self.server.down:
            return False, "The program cannot reach the MySQL server."
        return True, (f"Connected. The database has "
                      f"{len(self.server.reports)} report(s).")

    def check_connection(self, config=None):
        ok, message = self.test_connection(config)
        return ok, message, self.server.down

    # ---- the guarded interface ----
    def lock_report(self, conn, control, timeout=10):
        key = s.control_key(control)
        holder = self.server.locks.get(key)
        if holder is not None and holder is not conn:
            return False
        self.server.locks[key] = conn
        return True

    def unlock_report(self, conn, control):
        key = s.control_key(control)
        if self.server.locks.get(key) is conn:
            del self.server.locks[key]

    def report_exists(self, conn, control):
        return s.control_key(control) in self.server.reports

    has_report = report_exists

    def load_report(self, control, connection=None):
        if connection is None:
            self.connect()              # a stopped server cannot be read
        report = self.server.reports.get(s.control_key(control))
        if report is None:
            raise ValueError(f"Control # {control} was not found in MySQL.")
        return copy.deepcopy(report)

    def write_report(self, conn, data):
        conn.pending[s.control_key(data["control_no"])] = \
            _as_mysql_shows(data)
        return []

    # ---- the rest of db_mysql the program uses ----
    def save_report(self, data, connection=None):
        """The unguarded write (overwrites) - the program must not use it."""
        conn = connection or self.connect()
        self.write_report(conn, data)
        conn.commit()
        return []

    def save_master_lists(self, master_data, connection=None):
        if self.server.down:
            self.connect()
        self.server.master_lists += 1

    def control_numbers(self, connection=None):
        if connection is None:
            self.connect()
        return [r["control_no"] for r in self.server.reports.values()]

    def list_reports(self, connection=None):
        if connection is None:
            self.connect()
        rows = [(r["control_no"],
                 r["general_information"].get("so_number", ""),
                 r["general_information"].get("inspection_date", ""),
                 r["general_information"].get("consignee", ""), "")
                for r in self.server.reports.values()]
        return sorted(rows, key=lambda row: s.control_sort_key(row[0]),
                      reverse=True)

    def load_all_reports(self, connection=None):
        return [self.load_report(row[0]) for row in self.list_reports()]

    def sync_reports(self, reports):
        raise AssertionError("the unguarded sync must not be used any more")
