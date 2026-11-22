"""Offline schema-completeness tests for the shipment columns
packing_list_no / origin_line (Phase 5.6). No MySQL server is touched."""
import re
from pathlib import Path

import db_mysql

SCHEMA = Path(__file__).resolve().parent.parent / "data" / "schema"
BASE_SQL = SCHEMA / "field_survey_schema.sql"
TEST_SQL = SCHEMA / "field_survey_test_schema.sql"
ISOLATED_SQL = SCHEMA / "fsr_phase5_isolated_test_schema.sql"

ITEM_RE = re.compile(
    r"CREATE TABLE IF NOT EXISTS item_lines \((.*?)\) ENGINE=InnoDB;", re.S)

COL_RE = {
    "packing_list_no": re.compile(r"\bpacking_list_no\s+VARCHAR\(120\)\s+NULL"),
    "origin_line": re.compile(r"\borigin_line\s+VARCHAR\(120\)\s+NULL"),
}


def item_body(path):
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = ITEM_RE.search(text)
    assert m, f"item_lines not found in {path}"
    return m.group(1)


def test_base_schema_defines_both_shipment_columns():
    body = item_body(BASE_SQL)
    assert COL_RE["packing_list_no"].search(body)
    assert COL_RE["origin_line"].search(body)


def test_test_schema_defines_both_shipment_columns():
    body = item_body(TEST_SQL)
    assert COL_RE["packing_list_no"].search(body)
    assert COL_RE["origin_line"].search(body)


def test_isolated_schema_defines_both_shipment_columns():
    body = item_body(ISOLATED_SQL)
    assert COL_RE["packing_list_no"].search(body)
    assert COL_RE["origin_line"].search(body)


BASE_COLUMNS = ["id", "control_no", "item_list", "line_no", "description",
                "po_number", "packaging", "quantity", "dimensions", "weights",
                "unit_price", "total_price", "findings"]


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = []

    def execute(self, sql, params=()):
        self.conn.statements.append((sql, params))
        m = re.match(r"ALTER TABLE item_lines ADD COLUMN (\w+)", sql)
        if m:
            self.conn.item_columns.append(m.group(1))
            self.result = []
        elif sql.startswith("SHOW COLUMNS FROM item_lines"):
            self.result = [(c,) for c in self.conn.item_columns]
        elif sql.startswith("SHOW COLUMNS FROM reports"):
            self.result = [("id",), ("control_no",), ("item_form",)]
        else:
            self.result = []

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0] if self.result else None

    def close(self):
        pass


class FakeConnection:
    def __init__(self, item_columns):
        self.item_columns = list(item_columns)
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


def test_upgrade_adds_both_when_missing():
    conn = FakeConnection(BASE_COLUMNS)
    added = db_mysql.upgrade_schema(conn)
    assert "packing_list_no" in added and "origin_line" in added


def test_upgrade_adds_only_the_missing_one():
    conn = FakeConnection(BASE_COLUMNS + ["cargo_id", "receiving_ref", "uom",
                                          "currency", "unit_no",
                                          "packing_list_no"])
    added = db_mysql.upgrade_schema(conn)
    assert "origin_line" in added
    assert "packing_list_no" not in added


def test_upgrade_is_idempotent():
    conn = FakeConnection(BASE_COLUMNS)
    db_mysql.upgrade_schema(conn)
    conn.statements.clear()
    second = db_mysql.upgrade_schema(conn)
    assert "packing_list_no" not in second and "origin_line" not in second
    assert not [s for s, _ in conn.statements if "ADD COLUMN" in s]


def test_missing_link_columns_empty_when_present():
    conn = FakeConnection(BASE_COLUMNS + list(db_mysql.LINK_COLUMN_SQL))
    assert db_mysql.missing_link_columns(conn) == []


def test_missing_link_columns_reports_both_when_absent():
    conn = FakeConnection(BASE_COLUMNS)
    missing = db_mysql.missing_link_columns(conn)
    assert "packing_list_no" in missing and "origin_line" in missing
