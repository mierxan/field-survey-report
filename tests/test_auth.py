"""Authentication and account-file safety tests."""

import json

import pytest

import app_auth


@pytest.fixture
def isolated_auth(monkeypatch):
    monkeypatch.setattr(app_auth, "OWNER", {})
    monkeypatch.setattr(app_auth, "BUILT_IN_USERS", [])


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '{"users": "not a list"}',
        '{"users": [null]}',
    ],
)
def test_invalid_account_file_is_not_overwritten(
        tmp_path, isolated_auth, content):
    path = tmp_path / "users.json"
    original = content.encode("utf-8")
    path.write_bytes(original)

    with pytest.raises(app_auth.UserDataError):
        app_auth.UserStore(path)

    assert path.read_bytes() == original


def test_missing_account_file_keeps_first_run_owner_setup(
        tmp_path, monkeypatch):
    salt, digest = app_auth.hash_password("owner-password")
    monkeypatch.setattr(app_auth, "OWNER", {
        "first_name": "Test", "middle_name": "", "last_name": "Owner",
        "initials": "TO", "email": "owner@example.invalid",
        "salt": salt, "hash": digest,
    })
    monkeypatch.setattr(app_auth, "BUILT_IN_USERS", [])
    path = tmp_path / "users.json"

    store = app_auth.UserStore(path)

    assert store.sign_in("TO", "owner-password")["role"] == "owner"
    assert json.loads(path.read_text(encoding="utf-8"))["users"][0][
        "email"] == "owner@example.invalid"


def test_signup_approval_and_signin(tmp_path, isolated_auth):
    store = app_auth.UserStore(tmp_path / "users.json")
    store.sign_up("Test", "", "User", "TU", "test@example.invalid",
                  "correct-horse", "correct-horse")

    with pytest.raises(app_auth.AuthError, match="waiting for the Owner"):
        store.sign_in("TU", "correct-horse")

    store.set_status("test@example.invalid", "approved")
    assert store.sign_in("TU", "correct-horse")["status"] == "approved"
    with pytest.raises(app_auth.AuthError, match="Incorrect initials"):
        store.sign_in("TU", "wrong-password")


def test_password_change_requires_current_password(
        tmp_path, isolated_auth):
    store = app_auth.UserStore(tmp_path / "users.json")
    store.sign_up("Test", "", "User", "TU", "test@example.invalid",
                  "correct-horse", "correct-horse")
    store.set_status("test@example.invalid", "approved")

    with pytest.raises(app_auth.AuthError, match="current password"):
        store.change_own_password("test@example.invalid", "wrong-password",
                                  "new-passphrase", "new-passphrase")

    store.change_own_password("test@example.invalid", "correct-horse",
                              "new-passphrase", "new-passphrase")
    assert store.sign_in("TU", "new-passphrase")["status"] == "approved"


def test_new_passwords_require_twelve_characters(tmp_path, isolated_auth):
    store = app_auth.UserStore(tmp_path / "users.json")

    with pytest.raises(app_auth.AuthError, match="at least 12 characters"):
        store.sign_up("Test", "", "User", "TU", "test@example.invalid",
                      "short-pass", "short-pass")

    store.sign_up("Test", "", "User", "TU", "test@example.invalid",
                  "long-enough-pass", "long-enough-pass")
    with pytest.raises(app_auth.AuthError, match="at least 12 characters"):
        store.set_password("test@example.invalid", "short-pass")


def test_existing_short_password_remains_valid_for_signin(
        tmp_path, monkeypatch):
    salt, digest = app_auth.hash_password("short1")
    monkeypatch.setattr(app_auth, "OWNER", {
        "first_name": "Test", "middle_name": "", "last_name": "Owner",
        "initials": "TO", "email": "owner@example.invalid",
        "salt": salt, "hash": digest,
    })
    monkeypatch.setattr(app_auth, "BUILT_IN_USERS", [])
    store = app_auth.UserStore(tmp_path / "users.json")

    assert store.sign_in("TO", "short1")["role"] == "owner"
