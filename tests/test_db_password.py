"""The MySQL password lives in the protected store, not in db_config.json.
A fake store stands in for the Windows Credential Manager."""
import json

import pytest

import db_mysql
import fsr_secrets

PLAIN = {"enabled": True, "host": "localhost", "port": 3306,
         "user": "fsr_app", "password": "s3cret-Pass word!",
         "database": "field_survey"}


class FakeCredentialManager(fsr_secrets.MemorySecretStore):
    protected = True


class BrokenOnWrite(FakeCredentialManager):
    def set(self, name, value):
        raise fsr_secrets.SecretStoreError("no access")


class LosesTheValue(FakeCredentialManager):
    """Accepts the password but does not give it back."""
    def get(self, name):
        return None


class GivesBackSomethingElse(FakeCredentialManager):
    def get(self, name):
        value = super().get(name)
        return None if value is None else value[:-1]


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "private" / "db_config.json"
    monkeypatch.setattr(db_mysql, "CONFIG_FILE", path)
    store = FakeCredentialManager()
    monkeypatch.setattr(db_mysql, "SECRET_STORE", store)
    return path, store


def on_disk(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_plain(path, data=PLAIN):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_saving_puts_the_password_in_the_store_not_the_file(config_file):
    path, store = config_file
    db_mysql.write_config(dict(PLAIN))
    saved = on_disk(path)
    assert saved["password"] == ""
    assert saved["password_store"] == "credential-manager"
    assert PLAIN["password"] not in path.read_text(encoding="utf-8")
    assert list(store.values.values()) == [PLAIN["password"]]
    # the program still gets the real password
    assert db_mysql.load_config() == PLAIN
    assert db_mysql.read_raw_config()["password"] == PLAIN["password"]
    assert db_mysql.is_enabled()


def test_existing_plain_password_is_moved_at_start(config_file):
    path, store = config_file
    write_plain(path)
    assert db_mysql.load_config()["password"] == PLAIN["password"]  # before

    assert db_mysql.move_password_to_store() == "moved"

    assert on_disk(path)["password"] == ""
    assert PLAIN["password"] not in path.read_text(encoding="utf-8")
    assert db_mysql.load_config() == PLAIN                          # after
    assert db_mysql.move_password_to_store() == "nothing"           # once


@pytest.mark.parametrize("store_class", [
    BrokenOnWrite, LosesTheValue, GivesBackSomethingElse])
def test_file_is_blanked_only_after_a_successful_read_back(
        config_file, monkeypatch, store_class):
    path, _ = config_file
    monkeypatch.setattr(db_mysql, "SECRET_STORE", store_class())
    write_plain(path)
    before = path.read_bytes()

    assert db_mysql.move_password_to_store() == "kept"

    assert path.read_bytes() == before
    assert db_mysql.load_config()["password"] == PLAIN["password"]

    db_mysql.write_config(dict(PLAIN))              # MySQL Settings > Save
    assert on_disk(path)["password"] == PLAIN["password"]
    assert "password_store" not in on_disk(path)


def test_without_a_credential_manager_the_file_keeps_the_password(
        config_file, monkeypatch):
    path, _ = config_file
    plain_store = fsr_secrets.MemorySecretStore()        # protected = False
    monkeypatch.setattr(db_mysql, "SECRET_STORE", plain_store)
    write_plain(path)
    assert db_mysql.move_password_to_store() == "kept"
    db_mysql.write_config(dict(PLAIN))
    assert on_disk(path)["password"] == PLAIN["password"]
    assert plain_store.values == {}
    assert db_mysql.load_config() == PLAIN


def test_nothing_to_move(config_file):
    path, store = config_file
    assert db_mysql.move_password_to_store() == "nothing"      # no file
    write_plain(path, {**PLAIN, "password": ""})
    before = path.read_bytes()
    assert db_mysql.move_password_to_store() == "nothing"
    assert path.read_bytes() == before and store.values == {}
    path.write_text("{not json", encoding="utf-8")
    assert db_mysql.move_password_to_store() == "nothing"


def test_changing_the_password_replaces_the_stored_one(config_file):
    path, store = config_file
    db_mysql.write_config(dict(PLAIN))
    db_mysql.write_config({**db_mysql.read_raw_config(),
                           "password": "another-One"})
    assert list(store.values.values()) == ["another-One"]
    assert db_mysql.load_config()["password"] == "another-One"
    assert "another-One" not in path.read_text(encoding="utf-8")


def test_saving_other_settings_keeps_the_password(config_file):
    """MySQL Settings shows the saved password and writes it back."""
    path, _ = config_file
    db_mysql.write_config(dict(PLAIN))
    shown = db_mysql.read_raw_config()
    assert "password_store" not in shown
    db_mysql.write_config({**shown, "host": "127.0.0.1"})
    assert db_mysql.load_config() == {**PLAIN, "host": "127.0.0.1"}
    assert on_disk(path)["password"] == ""


def test_file_copied_to_another_pc_has_no_password(config_file, monkeypatch):
    """The Credential Manager entry does not travel with the file."""
    path, _ = config_file
    db_mysql.write_config(dict(PLAIN))
    monkeypatch.setattr(db_mysql, "SECRET_STORE", FakeCredentialManager())
    assert db_mysql.load_config()["password"] == ""
    assert db_mysql.read_raw_config()["password"] == ""
    assert "typed again" in db_mysql.explain_error(
        type("E", (Exception,), {"errno": 1045})())


def test_each_config_file_has_its_own_entry(config_file, monkeypatch,
                                            tmp_path):
    path, store = config_file
    db_mysql.write_config(dict(PLAIN))
    other = tmp_path / "demo" / "db_config.json"
    monkeypatch.setattr(db_mysql, "CONFIG_FILE", other)
    db_mysql.write_config({**PLAIN, "password": "demo-password"})
    assert len(store.values) == 2
    assert db_mysql.load_config()["password"] == "demo-password"
    monkeypatch.setattr(db_mysql, "CONFIG_FILE", path)
    assert db_mysql.load_config()["password"] == PLAIN["password"]


def test_connect_uses_the_stored_password(config_file, monkeypatch):
    import sys
    import types
    db_mysql.write_config(dict(PLAIN))
    seen = {}
    connector = types.ModuleType("mysql.connector")
    connector.connect = lambda **kw: seen.update(kw) or "connection"
    package = types.ModuleType("mysql")
    package.connector = connector
    monkeypatch.setitem(sys.modules, "mysql", package)
    monkeypatch.setitem(sys.modules, "mysql.connector", connector)
    assert db_mysql.connect() == "connection"
    assert seen["password"] == PLAIN["password"] and seen["user"] == "fsr_app"
