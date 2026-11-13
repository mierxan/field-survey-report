"""The REAL test database, field_survey_test, for tests/test_real_mysql.py.

Rules this helper keeps:
  * It connects to the database named field_survey_test and to nothing
    else: the name is fixed here, not taken from a file, and every
    connection is asked "which database are you?" before it is handed out.
  * It is used only when the test copy (the project folder) is set up for
    exactly that database. The login name comes from the test copy's
    db_config.json; the password is read from where the test copy keeps it
    (the Windows Credential Manager, or the file on a PC without one). The
    password is never printed, logged or written anywhere.
  * Every report it writes carries a Control # that starts with
    FSR-ZZT-2099; those rows - and only those - are removed afterwards.
  * When the database cannot be used, the tests are SKIPPED with a reason
    that starts with SKIP_PREFIX, so the skip report names the cause.
"""
import hashlib
import json
import os
from pathlib import Path

import db_mysql
import fsr_secrets

TEST_DATABASE = "field_survey_test"
PREFIX = "FSR-ZZT-2099"
SKIP_PREFIX = "the real test database field_survey_test is not available"
# The test copy's settings. FSR_TEST_DB_CONFIG may name that file when the
# tests run in another checkout of the code (a git worktree): the password
# is then still read from the test copy's own Credential Manager entry.
CONFIG_FILE = Path(os.environ.get("FSR_TEST_DB_CONFIG") or (
    Path(__file__).resolve().parent.parent / "data" / "json" / "private"
    / "db_config.json"))
TABLES = ("incident_reports", "remarks", "item_lines", "declared_goods",
          "reports")           # children first


class NotAvailable(Exception):
    pass


def _password(config):
    if config.get("password_store") != db_mysql.PASSWORD_STORE:
        return str(config.get("password") or "")
    name = "mysql-" + hashlib.sha256(
        str(CONFIG_FILE.resolve()).casefold().encode("utf-8")
    ).hexdigest()[:16]
    try:
        return fsr_secrets.WindowsCredentialStore().get(name) or ""
    except fsr_secrets.SecretStoreError:
        return ""


def settings():
    """Connection settings for field_survey_test, or NotAvailable(why)."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            config = json.load(file)
    except (OSError, ValueError):
        raise NotAvailable("the test copy has no MySQL settings "
                           "(data/json/private/db_config.json)")
    if not isinstance(config, dict) or not config.get("user"):
        raise NotAvailable("the test copy's MySQL settings name no login")
    if str(config.get("database", "")).strip() != TEST_DATABASE:
        raise NotAvailable("the test copy is not set to the database "
                           f"{TEST_DATABASE}")
    password = _password(config)
    if not password:
        raise NotAvailable("the password of the test login is not stored "
                           "on this PC")
    return {"enabled": True, "host": config.get("host", "localhost"),
            "port": config.get("port", 3306), "user": config["user"],
            "password": password, "database": TEST_DATABASE, "timeout": 4}


def _checked(conn):
    """Hand out a connection only when it really is the test database."""
    cur = conn.cursor()
    cur.execute("SELECT DATABASE()")
    name = cur.fetchone()[0]
    cur.close()
    if name != TEST_DATABASE:
        conn.close()
        raise AssertionError(
            f"connected to '{name}', not to {TEST_DATABASE}: refused")
    return conn


class RealTestDB:
    """What the guard sees as the db_mysql module: the real functions of
    db_mysql, with connect() tied to field_survey_test. `down = True`
    behaves like a stopped MySQL service."""

    def __init__(self, config):
        self._config = dict(config, database=TEST_DATABASE)
        self.down = False

    def connect(self, config=None):
        if self.down:
            error = OSError("Can't connect to MySQL server on 'localhost'")
            error.errno = 2003
            raise error
        return _checked(db_mysql.connect(dict(self._config)))

    def is_enabled(self):
        return True

    def load_report(self, control_no, connection=None):
        own = connection is None
        conn = connection or self.connect()
        try:
            return db_mysql.load_report(control_no, conn)
        finally:
            if own:
                conn.close()

    def control_numbers(self, connection=None):
        own = connection is None
        conn = connection or self.connect()
        try:
            return db_mysql.control_numbers(conn)
        finally:
            if own:
                conn.close()

    # these all work on a connection the caller got from connect()
    lock_report = staticmethod(db_mysql.lock_report)
    unlock_report = staticmethod(db_mysql.unlock_report)
    report_exists = staticmethod(db_mysql.report_exists)
    write_report = staticmethod(db_mysql.write_report)
    is_unreachable = staticmethod(db_mysql.is_unreachable)
    explain_error = staticmethod(db_mysql.explain_error)

    def run(self, sql, params=()):
        """One statement on its own connection (the 'someone else')."""
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.with_rows else []
            cur.close()
            conn.commit()
            return rows
        finally:
            conn.close()

    def remove_test_rows(self):
        conn = self.connect()
        try:
            cur = conn.cursor()
            for table in TABLES:
                cur.execute(f"DELETE FROM {table} WHERE control_no LIKE %s",
                            (PREFIX + "%",))
            cur.close()
            conn.commit()
        finally:
            conn.close()


def open_database():
    """RealTestDB, or NotAvailable(why)."""
    database = RealTestDB(settings())
    try:
        database.connect().close()
    except AssertionError:
        raise
    except Exception as error:
        code = getattr(error, "errno", None)
        raise NotAvailable(
            "MySQL did not accept the connection"
            + (f" (error {code})" if code else "")) from None
    return database
