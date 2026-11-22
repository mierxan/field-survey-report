"""The REAL test database for the Phase 5 integration tests.

Fail-closed by design (Phase 5.2):
  * Two environment variables are MANDATORY:
      FSR_TEST_DB_NAME    must be exactly 'fsr_phase5_isolated_test'
      FSR_TEST_DB_CONFIG  path to a DEDICATED test config file
    Missing either, or a name outside the allow-list, raises NotAvailable so
    the tests SKIP with a clear reason. There is no fallback, and the
    production db_config.json is never used.
  * The only permitted database is fsr_phase5_isolated_test. field_survey
    (production) and field_survey_test (existing) are explicitly rejected,
    along with any other name.
  * Every connection is asked "which database are you?" (SELECT DATABASE())
    and refused (and closed) unless it is the approved isolated database.
  * Test rows are identified by the Control # prefix FSR-ZZT-2099; cleanup
    removes only those rows (including master_list) and only on a verified
    connection.

The login comes from the dedicated config; the password is read from where
that config keeps it (the Windows Credential Manager, or the file on a PC
without one). The password is never printed, logged or written anywhere.
"""
import hashlib
import json
import os
from pathlib import Path

import db_mysql
import fsr_secrets

# The one database this harness may use.
ISOLATED_DATABASE = "fsr_phase5_isolated_test"
ALLOWED_DATABASES = frozenset({ISOLATED_DATABASE})

# Databases that must never be touched by this harness.
PROTECTED_DATABASES = frozenset({"field_survey", "field_survey_test"})

# Every test-generated row is identified by this Control # prefix.
PREFIX = "FSR-ZZT-2099"

# Report tables cleaned by control_no, plus master_list cleaned by item_name.
CLEAN_TABLES = ("incident_reports", "remarks", "item_lines", "declared_goods",
                "reports", "master_list")

ENV_NAME = "FSR_TEST_DB_NAME"
ENV_CONFIG = "FSR_TEST_DB_CONFIG"

# The production app config; FSR_TEST_DB_CONFIG must never point here.
APP_CONFIG_FILE = (Path(__file__).resolve().parent.parent / "data" / "json"
                   / "private" / "db_config.json")

# Kept for the test modules that import it.
TEST_DATABASE = ISOLATED_DATABASE
SKIP_PREFIX = f"the isolated test database {ISOLATED_DATABASE} is not available"


class NotAvailable(Exception):
    pass


def _password(config, config_path):
    if config.get("password_store") != db_mysql.PASSWORD_STORE:
        return str(config.get("password") or "")
    name = "mysql-" + hashlib.sha256(
        str(Path(config_path).resolve()).casefold().encode("utf-8")
    ).hexdigest()[:16]
    try:
        return fsr_secrets.WindowsCredentialStore().get(name) or ""
    except fsr_secrets.SecretStoreError:
        return ""


def settings():
    """Connection settings for the approved isolated test database, or
    NotAvailable(why). Fail-closed: both env vars are mandatory, the name must
    be exactly the approved isolated database, and the config must be a
    separate file that names that database (never the production config)."""
    name = (os.environ.get(ENV_NAME) or "").strip()
    if not name:
        raise NotAvailable(f"{ENV_NAME} is not set (it must be "
                           f"'{ISOLATED_DATABASE}')")
    if name not in ALLOWED_DATABASES:
        raise NotAvailable(f"{ENV_NAME}='{name}' is not allowed; only "
                           f"{sorted(ALLOWED_DATABASES)} may be used")

    cfg_path = (os.environ.get(ENV_CONFIG) or "").strip()
    if not cfg_path:
        raise NotAvailable(f"{ENV_CONFIG} is not set (path to a dedicated "
                           "test config, never the production db_config.json)")
    config_path = Path(cfg_path)

    try:
        same_as_app = config_path.resolve() == APP_CONFIG_FILE.resolve()
    except OSError:
        same_as_app = False
    if same_as_app:
        raise NotAvailable(f"{ENV_CONFIG} points at the production config "
                           f"({APP_CONFIG_FILE}); use a separate test config")

    try:
        with open(config_path, "r", encoding="utf-8") as file:
            config = json.load(file)
    except (OSError, ValueError):
        raise NotAvailable(f"{ENV_CONFIG} is not readable JSON: {config_path}")

    if not isinstance(config, dict) or not config.get("user"):
        raise NotAvailable("the test config names no user")

    db_name = str(config.get("database", "")).strip()
    if db_name.casefold() in {d.casefold() for d in PROTECTED_DATABASES}:
        raise NotAvailable(f"refusing protected database '{db_name}'")
    if db_name != ISOLATED_DATABASE:
        raise NotAvailable(f"the test config database is '{db_name}', not "
                           f"'{ISOLATED_DATABASE}'")

    if str(config.get("user", "")).strip().casefold() == "fsr_app":
        raise NotAvailable("refusing the production application user 'fsr_app'")

    password = _password(config, config_path)
    if not password:
        raise NotAvailable("the test login's password is not available")

    return {"enabled": True, "host": config.get("host", "localhost"),
            "port": config.get("port", 3306), "user": config["user"],
            "password": password, "database": ISOLATED_DATABASE, "timeout": 4}


def _checked(conn):
    """Hand out a connection only when it really is the approved database."""
    cur = conn.cursor()
    cur.execute("SELECT DATABASE()")
    name = cur.fetchone()[0]
    cur.close()
    if name not in ALLOWED_DATABASES or name != ISOLATED_DATABASE:
        conn.close()
        raise AssertionError(
            f"connected to '{name}', not to {ISOLATED_DATABASE}: refused")
    return conn


class RealTestDB:
    """What the guard sees as the db_mysql module: the real functions of
    db_mysql, with connect() tied to the approved isolated database. `down =
    True` behaves like a stopped MySQL service."""

    def __init__(self, config):
        self._config = dict(config, database=ISOLATED_DATABASE)
        self.down = False
        self.verified = False

    def connect(self, config=None):
        if self.down:
            error = OSError("Can't connect to MySQL server on 'localhost'")
            error.errno = 2003
            raise error
        conn = _checked(db_mysql.connect(dict(self._config)))
        self.verified = True
        return conn

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
        """One statement on its own (verified) connection."""
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
        """Delete only test-generated rows (prefix FSR-ZZT-2099) from the
        report tables and master_list. Refuses to run without a verified
        connection: connect() verifies SELECT DATABASE() and raises if the
        database is not the approved isolated one."""
        conn = self.connect()          # verifies SELECT DATABASE()
        try:
            cur = conn.cursor()
            for table in CLEAN_TABLES:
                col = "item_name" if table == "master_list" else "control_no"
                cur.execute(f"DELETE FROM {table} WHERE {col} LIKE %s",
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
