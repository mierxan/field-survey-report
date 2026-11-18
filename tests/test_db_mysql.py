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


def test_upgrade_widens_a_short_control_no_and_restores_its_keys():
    class ShortCursor(FakeCursor):
        def execute(self, sql, params=()):
            super().execute(sql, params)
            if "character_maximum_length" in sql:
                self.result = [("reports",), ("item_lines",)]
            elif "referenced_table_name" in sql:
                self.result = [("item_lines", "fk_item_report")]

    class ShortConnection(FakeConnection):
        def cursor(self):
            return ShortCursor(self)

    conn = ShortConnection(BASE + list(db_mysql.LINK_COLUMN_SQL))
    assert "control_no" in db_mysql.upgrade_schema(conn)
    alters = [s for s, _ in conn.statements if s.startswith("ALTER TABLE")
              and "item_form" not in s]
    assert alters[0] == "ALTER TABLE item_lines DROP FOREIGN KEY fk_item_report"
    assert "ALTER TABLE reports MODIFY control_no VARCHAR(40) NOT NULL" in alters
    assert alters[-1].startswith("ALTER TABLE item_lines ADD CONSTRAINT fk_item_report")
    assert "ON DELETE CASCADE ON UPDATE CASCADE" in alters[-1]
    assert conn.committed


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
                     "packing_list_no", "origin_line", "item_form"]
    alters = [s for s, _ in conn.statements if s.startswith("ALTER")]
    assert alters == ["ALTER TABLE item_lines ADD COLUMN receiving_ref "
                      "VARCHAR(100) NULL",
                      "ALTER TABLE item_lines ADD COLUMN uom VARCHAR(30) NULL",
                      "ALTER TABLE item_lines ADD COLUMN currency "
                      "VARCHAR(3) NULL",
                      "ALTER TABLE item_lines ADD COLUMN unit_no "
                      "VARCHAR(100) NULL",
                      "ALTER TABLE item_lines ADD COLUMN packing_list_no "
                      "VARCHAR(120) NULL",
                      "ALTER TABLE item_lines ADD COLUMN origin_line "
                      "VARCHAR(120) NULL",
                      "ALTER TABLE reports ADD COLUMN item_form "
                      "VARCHAR(20) NULL"]


def test_upgrade_as_admin_uses_that_login_once_and_keeps_the_saved_one(monkeypatch):
    saved = {"user": "fsr_app", "password": "app", "database": "field_survey"}
    used = []
    conn = FakeConnection(BASE + list(db_mysql.LINK_COLUMN_SQL))

    def fake_connect(config):
        used.append(config)
        return conn

    monkeypatch.setattr(db_mysql, "load_config", lambda: saved)
    monkeypatch.setattr(db_mysql, "connect", fake_connect)
    db_mysql.upgrade_schema_as("root", "secret")
    assert used == [{"user": "root", "password": "secret",
                     "database": "field_survey"}]
    assert saved["user"] == "fsr_app" and conn.committed


def test_denied_command_is_explained(monkeypatch):
    class Denied(Exception):
        errno = db_mysql.ACCESS_DENIED

    monkeypatch.setattr(db_mysql, "load_config", lambda: {"user": "fsr_app"})
    message = db_mysql.explain_error(Denied("ALTER command denied"))
    assert "'fsr_app' is not allowed" in message and "admin login" in message


def test_saved_reports_list_is_in_order_of_age_whoever_the_inspector():
    class ListCursor(FakeCursor):
        def execute(self, sql, params=()):
            super().execute(sql, params)
            if "FROM reports ORDER BY" in sql:
                self.result = [(c, "", None, "", None) for c in
                               ("FSR-ZZ-202610-0001", "FSR-JDC-202611-0001",
                                "FSR-AB-202611-0002")]

    class ListConnection(FakeConnection):
        def cursor(self):
            return ListCursor(self)

    listed = [row[0] for row in db_mysql.list_reports(ListConnection(BASE))]
    assert listed == ["FSR-AB-202611-0002", "FSR-JDC-202611-0001", "FSR-ZZ-202610-0001"]
