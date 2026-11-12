"""The test copy: a program run from the source folder does not connect to
the real database, and the script for the test database."""
import re
import sys
import types

import pytest

import db_mysql
import fsr_test_db_script as script

REAL = {"enabled": True, "host": "localhost", "port": 3306,
        "user": "fsr_app", "password": "x", "database": "field_survey"}


@pytest.fixture
def connector(monkeypatch):
    """A stand-in for mysql.connector that records every connection."""
    seen = []
    module = types.ModuleType("mysql.connector")
    module.connect = lambda **kw: seen.append(kw) or "connection"
    package = types.ModuleType("mysql")
    package.connector = module
    monkeypatch.setitem(sys.modules, "mysql", package)
    monkeypatch.setitem(sys.modules, "mysql.connector", module)
    return seen


# ---------- run from source: the real database is refused ----------

def test_source_copy_refuses_the_real_database(connector):
    assert db_mysql.is_test_copy()              # the tests run from source
    with pytest.raises(db_mysql.RealDatabaseRefused, match="TEST COPY"):
        db_mysql.connect(dict(REAL))
    assert connector == []                      # not even tried


@pytest.mark.parametrize("name", ["field_survey", "FIELD_SURVEY",
                                  " Field_Survey "])
def test_refusal_does_not_depend_on_spelling(connector, name):
    with pytest.raises(db_mysql.RealDatabaseRefused):
        db_mysql.connect({**REAL, "database": name})


def test_missing_database_name_means_the_real_one(connector):
    config = {k: v for k, v in REAL.items() if k != "database"}
    with pytest.raises(db_mysql.RealDatabaseRefused):
        db_mysql.connect(config)


def test_source_copy_connects_to_a_test_database(connector):
    assert db_mysql.connect({**REAL, "database": "field_survey_test",
                             "user": "fsr_test"}) == "connection"
    assert connector[0]["database"] == "field_survey_test"


@pytest.mark.parametrize("value", [False, None, "true", 1, "yes"])
def test_only_an_explicit_true_allows_the_real_database(connector, value):
    with pytest.raises(db_mysql.RealDatabaseRefused):
        db_mysql.connect({**REAL, "allow_real_database": value})


def test_explicit_setting_allows_it(connector):
    assert db_mysql.connect({**REAL, "allow_real_database": True}) == \
        "connection"


def test_status_check_explains_the_refusal(connector):
    ok, message = db_mysql.test_connection(dict(REAL))
    assert not ok and "TEST COPY" in message
    assert "will not connect to the real database" in message
    assert "field_survey_test" in message


def test_mysql_settings_window_does_not_keep_the_permission(tmp_path,
                                                            monkeypatch):
    """Saving from MySQL Settings writes only the fields of that window, so
    the permission cannot be switched on by accident there."""
    monkeypatch.setattr(db_mysql, "CONFIG_FILE", tmp_path / "db_config.json")
    monkeypatch.setattr(db_mysql, "SECRET_STORE", None)
    db_mysql.write_config({**REAL, "allow_real_database": True})
    shown = db_mysql.read_raw_config()
    from_window = {key: shown[key] for key in (
        "enabled", "host", "port", "user", "password", "database")}
    db_mysql.write_config(from_window)
    assert "allow_real_database" not in db_mysql.read_raw_config()


# ---------- the installed program is not affected ----------

def test_installed_program_connects_to_the_real_database(connector,
                                                         monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert not db_mysql.is_test_copy()
    assert db_mysql.connect(dict(REAL)) == "connection"
    assert connector[0]["database"] == "field_survey"
    assert connector[0]["user"] == "fsr_app"


# ---------- the helpers the guard uses ----------

class Cursor:
    def __init__(self, rows):
        self.rows, self.statements = rows, []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class Connection:
    database = "field_survey_test"

    def __init__(self, rows):
        self.last = Cursor(rows)

    def cursor(self):
        return self.last


def test_lock_is_a_mysql_lock_on_the_control_number():
    conn = Connection([(1,)])
    assert db_mysql.lock_report(conn, "FSR-MPR-202611-0001") is True
    sql, (name, timeout) = conn.last.statements[0]
    assert sql == "SELECT GET_LOCK(%s, %s)" and timeout == 10
    assert name.startswith("fsr-") and len(name) <= 64
    # the same report in another letter case is the same lock ...
    other = Connection([(1,)])
    db_mysql.lock_report(other, " fsr-mpr-202611-0001 ")
    assert other.last.statements[0][1][0] == name
    # ... another report, or the same number in another database, is not
    db_mysql.lock_report(other, "FSR-MPR-202611-0002")
    assert other.last.statements[1][1][0] != name
    elsewhere = Connection([(1,)])
    elsewhere.database = "field_survey"
    db_mysql.lock_report(elsewhere, "FSR-MPR-202611-0001")
    assert elsewhere.last.statements[0][1][0] != name

    assert db_mysql.lock_report(Connection([(0,)]), "X") is False   # held
    assert db_mysql.lock_report(Connection([(None,)]), "X") is False

    conn = Connection([(1,)])
    db_mysql.unlock_report(conn, "FSR-MPR-202611-0001")
    assert conn.last.statements == [("SELECT RELEASE_LOCK(%s)", (name,))]


def test_check_reads_the_row_for_update_inside_the_transaction():
    conn = Connection([("FSR-MPR-202611-0001",)])
    assert db_mysql.report_exists(conn, "FSR-MPR-202611-0001") is True
    sql = conn.last.statements[0][0]
    assert "FROM reports WHERE control_no = %s" in sql
    assert sql.rstrip().endswith("FOR UPDATE")
    assert db_mysql.report_exists(Connection([]), "X") is False


def test_control_numbers_lists_every_report():
    conn = Connection([("A-1",), ("A-2",)])
    assert db_mysql.control_numbers(conn) == ["A-1", "A-2"]
    assert conn.last.statements[0][0] == "SELECT control_no FROM reports"


# ---------- the script for the test database ----------

def test_script_on_disk_is_made_from_the_current_schema():
    made = script.build(script.SOURCE.read_text(encoding="utf-8"))
    assert script.TARGET.read_text(encoding="utf-8").replace(
        "\r\n", "\n") == made


def statements(text):
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("--"))


def test_script_contains_no_password_and_creates_no_login():
    text = script.TARGET.read_text(encoding="utf-8")
    live = statements(text)
    assert "IDENTIFIED" not in live.upper()
    assert "CREATE USER" not in live.upper()
    assert "ALTER USER" not in live.upper()
    assert "PASSWORD" not in live.upper()
    assert "fsr_app" not in live          # only named in a comment


def test_script_never_names_the_real_database():
    text = script.TARGET.read_text(encoding="utf-8")
    assert not re.search(r"\bfield_survey\b(?!_test)", statements(text))
    assert "CREATE DATABASE IF NOT EXISTS field_survey_test" in text
    assert "\nUSE field_survey_test;" in text


def test_script_grants_the_test_login_the_test_database_only():
    live = statements(script.TARGET.read_text(encoding="utf-8"))
    grants = [line for line in live.splitlines() if line.startswith("GRANT")]
    assert grants == ["GRANT SELECT, INSERT, UPDATE, DELETE ON "
                      "field_survey_test.* TO 'fsr_test'@'localhost';"]
    assert "SHOW GRANTS FOR 'fsr_test'@'localhost';" in live
    assert "ALL PRIVILEGES" not in live.upper() and "*.*" not in live


def test_script_has_every_table_of_the_real_schema():
    real = script.SOURCE.read_text(encoding="utf-8")
    test = script.TARGET.read_text(encoding="utf-8")
    pattern = r"CREATE TABLE IF NOT EXISTS (\w+)"
    assert re.findall(pattern, test) == re.findall(pattern, real)
    assert len(re.findall(pattern, real)) == 7
    assert test.count("FOREIGN KEY") == real.count("FOREIGN KEY")
    assert "CREATE OR REPLACE VIEW v_item_report" in test
