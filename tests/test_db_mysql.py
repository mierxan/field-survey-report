"""db_mysql with a fake connection (no MySQL server is touched): the link
columns are written only when the table has them, and read back."""

import db_mysql
from factories import rec
from datetime import date


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.result = []
        self.lastrowid = 1

    def execute(self, sql, params=()):
        self.db.statements.append((sql, params))
        if sql.startswith("SHOW COLUMNS FROM item_lines"):
            self.result = [(c,) for c in self.db.columns]
        else:
            self.result = []

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0] if self.result else None

    def close(self):
        pass


class FakeConnection:
    def __init__(self, columns):
        self.columns = columns
        self.statements = []
        self.committed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


BASE = ["id", "control_no", "item_list", "line_no", "description",
        "po_number", "packaging", "quantity", "dimensions", "weights",
        "unit_price", "total_price", "findings"]


def item_inserts(conn):
    return [(sql, p) for sql, p in conn.statements
            if sql.startswith("INSERT INTO item_lines")]


def data():
    d = rec("FSR-2026-0001", date(2026, 10, 1), "CID-9", 4, ref="RCV-X")
    return d


def test_old_table_saves_without_links_and_says_so():
    conn = FakeConnection(BASE)
    notes = db_mysql.save_report(data(), conn)
    sql, params = item_inserts(conn)[0]
    assert "cargo_id" not in sql and "CID-9" not in params
    assert conn.committed and "Excel only" in notes[0]


def test_upgraded_table_saves_links():
    conn = FakeConnection(BASE + ["cargo_id", "receiving_ref"])
    notes = db_mysql.save_report(data(), conn)
    sql, params = item_inserts(conn)[0]
    assert "cargo_id, receiving_ref" in sql
    assert "CID-9" in params and "RCV-X" in params
    assert notes == []


def test_upgrade_adds_only_missing_columns():
    conn = FakeConnection(BASE + ["cargo_id"])
    added = db_mysql.upgrade_schema(conn)
    assert added == ["receiving_ref", "uom", "currency", "unit_no",
                     "item_form"]
    alters = [s for s, _ in conn.statements if s.startswith("ALTER")]
    assert alters == ["ALTER TABLE item_lines ADD COLUMN receiving_ref "
                      "VARCHAR(100) NULL",
                      "ALTER TABLE item_lines ADD COLUMN uom VARCHAR(30) NULL",
                      "ALTER TABLE item_lines ADD COLUMN currency "
                      "VARCHAR(3) NULL",
                      "ALTER TABLE item_lines ADD COLUMN unit_no "
                      "VARCHAR(100) NULL",
                      "ALTER TABLE reports ADD COLUMN item_form "
                      "VARCHAR(20) NULL"]
