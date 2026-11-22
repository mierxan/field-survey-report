"""Offline tests for the Phase 5.2 fail-closed isolated MySQL harness.

These never connect to MySQL: settings() is tested with temporary config
files and environment variables, and every connection is a fake object.
"""
import json
import re

import pytest

import fsr_test_db_script as script
import real_mysql

ENV_NAME = real_mysql.ENV_NAME
ENV_CONFIG = real_mysql.ENV_CONFIG
DB = real_mysql.ISOLATED_DATABASE


def write_cfg(tmp_path, data, name="cfg.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def good_config(**over):
    base = {"enabled": True, "host": "localhost", "port": 3306,
            "user": "fsr_phase5", "password": "pw", "database": DB}
    base.update(over)
    return base


# ---------- settings(): mandatory environment ----------

def test_missing_name_fails_closed(monkeypatch, tmp_path):
    monkeypatch.delenv(ENV_NAME, raising=False)
    monkeypatch.setenv(ENV_CONFIG, str(write_cfg(tmp_path, good_config())))
    with pytest.raises(real_mysql.NotAvailable, match=ENV_NAME):
        real_mysql.settings()


def test_missing_config_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_NAME, DB)
    monkeypatch.delenv(ENV_CONFIG, raising=False)
    with pytest.raises(real_mysql.NotAvailable, match=ENV_CONFIG):
        real_mysql.settings()


@pytest.mark.parametrize("bad", ["field_survey", "field_survey_test",
                                 "some_other_db", ""])
def test_name_must_be_the_isolated_database(monkeypatch, tmp_path, bad):
    monkeypatch.setenv(ENV_NAME, bad)
    monkeypatch.setenv(ENV_CONFIG, str(write_cfg(tmp_path, good_config())))
    with pytest.raises(real_mysql.NotAvailable):
        real_mysql.settings()


def test_correct_isolated_name_accepted(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_NAME, DB)
    monkeypatch.setenv(ENV_CONFIG, str(write_cfg(tmp_path, good_config())))
    settings = real_mysql.settings()
    assert settings["database"] == DB
    assert settings["user"] == "fsr_phase5"


# ---------- settings(): config content ----------

@pytest.mark.parametrize("db", ["field_survey", "field_survey_test",
                                "other_db"])
def test_config_database_must_match(monkeypatch, tmp_path, db):
    monkeypatch.setenv(ENV_NAME, DB)
    monkeypatch.setenv(ENV_CONFIG,
                       str(write_cfg(tmp_path, good_config(database=db))))
    with pytest.raises(real_mysql.NotAvailable, match="protected|not"):
        real_mysql.settings()


def test_config_may_not_be_the_production_config(monkeypatch):
    monkeypatch.setenv(ENV_NAME, DB)
    monkeypatch.setenv(ENV_CONFIG, str(real_mysql.APP_CONFIG_FILE))
    with pytest.raises(real_mysql.NotAvailable, match="production config"):
        real_mysql.settings()


def test_production_user_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_NAME, DB)
    monkeypatch.setenv(ENV_CONFIG,
                       str(write_cfg(tmp_path, good_config(user="fsr_app"))))
    with pytest.raises(real_mysql.NotAvailable, match="fsr_app"):
        real_mysql.settings()


def test_missing_password_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_NAME, DB)
    cfg = good_config()
    cfg["password"] = ""
    monkeypatch.setenv(ENV_CONFIG, str(write_cfg(tmp_path, cfg)))
    with pytest.raises(real_mysql.NotAvailable, match="password"):
        real_mysql.settings()


def test_no_fallback_to_production_config(monkeypatch, tmp_path):
    """With the config env unset, settings() never reads db_config.json."""
    monkeypatch.setenv(ENV_NAME, DB)
    monkeypatch.delenv(ENV_CONFIG, raising=False)
    with pytest.raises(real_mysql.NotAvailable, match=ENV_CONFIG):
        real_mysql.settings()


# ---------- _checked(): SELECT DATABASE() guard ----------

class FakeCursor:
    def __init__(self, rows=None, record=None):
        self.rows = rows
        self.record = record
        self.closed = False

    def execute(self, sql, params=()):
        if self.record is not None:
            self.record.append((sql, params))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows or []

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, db_name=None, record=None):
        self._cur = FakeCursor([(db_name,)] if db_name is not None else None,
                               record)
        self.closed = False
        self.committed = False

    def cursor(self):
        return self._cur

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


@pytest.mark.parametrize("actual", ["field_survey", "field_survey_test",
                                    "other_db"])
def test_checked_rejects_wrong_database(actual):
    conn = FakeConn(db_name=actual)
    with pytest.raises(AssertionError):
        real_mysql._checked(conn)
    assert conn.closed is True


def test_checked_accepts_isolated_database():
    conn = FakeConn(db_name=DB)
    assert real_mysql._checked(conn) is conn
    assert conn.closed is False


# ---------- remove_test_rows(): unified prefix + master_list ----------

def make_db():
    return real_mysql.RealTestDB({"host": "x", "port": 3306,
                                  "user": "fsr_phase5", "password": "pw",
                                  "database": DB})


def test_cleanup_is_scoped_to_the_test_prefix():
    db = make_db()
    record = []
    fake = FakeConn(db_name=DB, record=record)
    db.connect = lambda config=None: fake
    db.remove_test_rows()

    assert len(record) == len(real_mysql.CLEAN_TABLES)
    for (sql, params), table in zip(record, real_mysql.CLEAN_TABLES):
        col = "item_name" if table == "master_list" else "control_no"
        assert f"DELETE FROM {table}" in sql
        assert col in sql and "LIKE" in sql
        assert params == (real_mysql.PREFIX + "%",)
    assert "master_list" in real_mysql.CLEAN_TABLES
    assert fake.committed is True


def test_cleanup_refuses_without_a_verified_connection():
    db = make_db()

    def boom(config=None):
        raise OSError("no connection")

    db.connect = boom
    with pytest.raises(OSError):
        db.remove_test_rows()


# ---------- schema generation ----------

def live(text):
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("--"))


def test_isolated_schema_names_only_the_isolated_database():
    text = script.build_isolated()
    assert f"CREATE DATABASE IF NOT EXISTS {DB}" in text
    assert f"\nUSE {DB};" in text
    assert not re.search(r"\bfield_survey\b(?!_)", live(text))
    assert "ALL PRIVILEGES" not in live(text).upper()
    assert "*.*" not in live(text)


def test_isolated_schema_grants_only_the_isolated_database():
    grants = [line for line in live(script.build_isolated()).splitlines()
              if line.startswith("GRANT")]
    assert grants == [
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {DB}.* "
        f"TO '{script.ISOLATED_LOGIN}'@'localhost';"]


def test_isolated_schema_has_every_table_of_the_real_schema():
    real = script.SOURCE.read_text(encoding="utf-8")
    pattern = r"CREATE TABLE IF NOT EXISTS (\w+)"
    assert re.findall(pattern, script.build_isolated()) == \
        re.findall(pattern, real)
    assert len(re.findall(pattern, real)) == 7


def test_existing_test_schema_is_unchanged():
    made = script.build(script.SOURCE.read_text(encoding="utf-8"))
    assert script.TARGET.read_text(encoding="utf-8").replace(
        "\r\n", "\n") == made
