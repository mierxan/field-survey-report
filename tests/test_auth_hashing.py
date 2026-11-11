"""Password hashes: per-account iteration count, upgrade at sign in, the
users.json version number, and the owner seed command."""
import json

import pytest

import app_auth
import fsr_secrets


def legacy_user(password="old-password-1", **extra):
    """An account exactly as the earlier program saved it (no iterations)."""
    salt, digest = app_auth.hash_password(password)
    return {"first_name": "Old", "middle_name": "", "last_name": "User",
            "initials": "OU", "email": "old@example.invalid", "salt": salt,
            "hash": digest, "role": "owner", "status": "approved", **extra}


def store_with(tmp_path, document):
    path = tmp_path / "users.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return app_auth.UserStore(path, secrets=fsr_secrets.MemorySecretStore(),
                              use_seed=False), path


def test_default_hash_is_the_legacy_one():
    """Old files and the old seed carry hashes made with 200,000."""
    assert app_auth.LEGACY_ITERATIONS == 200_000
    assert app_auth.ITERATIONS == 600_000
    salt, digest = app_auth.hash_password("pass", "00" * 16)
    assert app_auth.hash_password("pass", "00" * 16, 200_000) == (salt, digest)
    assert app_auth.hash_password("pass", "00" * 16, 600_000)[1] != digest


def test_new_accounts_use_600000_iterations(tmp_path):
    store, path = store_with(tmp_path, {"users": []})
    store.create_administrator("Site", "", "Admin", "SA",
                               "admin@example.invalid", "administrator-pass",
                               "administrator-pass")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["version"] == app_auth.FILE_VERSION == 2
    assert saved["users"][0]["iterations"] == 600_000
    assert store.sign_in("SA", "administrator-pass")["role"] == "admin"


def test_old_hash_still_verifies_and_is_upgraded_at_sign_in(tmp_path):
    old = legacy_user()
    store, path = store_with(tmp_path, {"users": [old]})
    assert path.read_text(encoding="utf-8").count("iterations") == 0

    with pytest.raises(app_auth.AuthError, match="Incorrect"):
        store.sign_in("OU", "wrong-password")
    assert json.loads(path.read_text(encoding="utf-8"))["users"][0][
        "hash"] == old["hash"]                 # a failure upgrades nothing

    user = store.sign_in("OU", "old-password-1")

    saved = json.loads(path.read_text(encoding="utf-8"))["users"][0]
    assert user["iterations"] == saved["iterations"] == 600_000
    assert saved["hash"] != old["hash"] and saved["salt"] != old["salt"]
    assert old["hash"] not in path.read_text(encoding="utf-8")
    assert store.sign_in("OU", "old-password-1")["hash"] == saved["hash"]
    with pytest.raises(app_auth.AuthError, match="Incorrect"):
        store.sign_in("OU", "wrong-password")


def test_changed_password_uses_the_current_count(tmp_path):
    store, path = store_with(tmp_path, {"users": [legacy_user()]})
    store.change_own_password("old@example.invalid", "old-password-1",
                              "new-passphrase-2", "new-passphrase-2")
    saved = json.loads(path.read_text(encoding="utf-8"))["users"][0]
    assert saved["iterations"] == 600_000
    assert store.sign_in("OU", "new-passphrase-2")


@pytest.mark.parametrize("bad", [0, -5, "600000", True, 10**9, 1.5])
def test_unusable_iteration_count_never_matches(tmp_path, bad):
    store, _ = store_with(tmp_path, {"users": [legacy_user(iterations=bad)]})
    with pytest.raises(app_auth.AuthError, match="Incorrect"):
        store.sign_in("OU", "old-password-1")


def test_file_without_version_and_new_fields_loads_unchanged(tmp_path):
    document = {"users": [legacy_user()]}
    store, path = store_with(tmp_path, document)
    before = path.read_bytes()
    assert [u["initials"] for u in store.list_users()] == ["OU"]
    assert store.find("old@example.invalid")["role"] == "owner"
    assert path.read_bytes() == before         # reading changes nothing


@pytest.mark.parametrize("version", [3, 99])
def test_newer_file_is_refused_with_a_clear_message(tmp_path, version):
    path = tmp_path / "users.json"
    original = json.dumps({"version": version, "users": [legacy_user()]})
    path.write_text(original, encoding="utf-8")
    with pytest.raises(app_auth.UserDataError, match="newer version"):
        app_auth.UserStore(path, secrets=fsr_secrets.MemorySecretStore(),
                           use_seed=False)
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("version", [0, "2", None, True])
def test_invalid_version_is_refused(tmp_path, version):
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"version": version, "users": []}),
                    encoding="utf-8")
    with pytest.raises(app_auth.UserDataError, match="invalid version"):
        app_auth.UserStore(path, secrets=fsr_secrets.MemorySecretStore(),
                           use_seed=False)


def test_seed_with_iterations_creates_a_working_owner(tmp_path, monkeypatch):
    seed = tmp_path / "auth_seed.json"
    record = app_auth.make_seed("brand-new-owner-pass", owner={
        "first_name": "Test", "middle_name": "Q", "last_name": "Owner",
        "initials": "to", "email": "Owner@Example.invalid"}, path=seed)
    written = json.loads(seed.read_text(encoding="utf-8"))
    assert set(written) == {"owner"}            # no other accounts
    assert written["owner"]["iterations"] == 600_000
    assert record["initials"] == "TO"
    assert record["email"] == "owner@example.invalid"
    assert "brand-new-owner-pass" not in seed.read_text(encoding="utf-8")

    monkeypatch.setattr(app_auth, "OWNER", written["owner"])
    store = app_auth.UserStore(tmp_path / "users.json",
                               secrets=fsr_secrets.MemorySecretStore())
    user = store.sign_in("TO", "brand-new-owner-pass")
    assert user["role"] == "owner" and user["iterations"] == 600_000


def test_make_seed_keeps_the_names_of_the_existing_seed(tmp_path):
    seed = tmp_path / "auth_seed.json"
    seed.write_text(json.dumps({
        "owner": {"first_name": "Test", "middle_name": "", "last_name":
                  "Owner", "initials": "TO", "email": "owner@example.invalid",
                  "salt": "00" * 16, "hash": "11" * 32},
        "built_in_users": [{"initials": "XX"}]}), encoding="utf-8")
    app_auth.make_seed("another-owner-pass", path=seed)
    written = json.loads(seed.read_text(encoding="utf-8"))
    assert set(written) == {"owner"}
    assert written["owner"]["last_name"] == "Owner"
    assert written["owner"]["hash"] != "11" * 32

    with pytest.raises(app_auth.AuthError, match="at least 12"):
        app_auth.make_seed("short", path=seed)
    assert json.loads(seed.read_text(encoding="utf-8")) == written
