"""Bringing the users.json of an earlier program up to date: backup first,
the retired built-in account is removed, everything else keeps working."""
import hashlib
import json

import pytest

import app_auth
import fsr_secrets

RETIRED_EMAIL = "retired.builtin@example.invalid"


@pytest.fixture(autouse=True)
def retired(monkeypatch):
    """The tests use an invented address, not the real one."""
    monkeypatch.setattr(app_auth, "RETIRED_ACCOUNTS", frozenset({
        hashlib.sha256(RETIRED_EMAIL.encode("utf-8")).hexdigest()}))


def account(initials, email, password, role="user", status="approved"):
    salt, digest = app_auth.hash_password(password)       # as saved before
    return {"first_name": initials, "middle_name": "", "last_name": "Person",
            "initials": initials, "email": email, "salt": salt,
            "hash": digest, "role": role, "status": status,
            "created": "28-Oct-2026 10:03"}


def old_file(tmp_path, users):
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": users}, indent=2), encoding="utf-8")
    return path


def open_store(path, secrets=None):
    return app_auth.UserStore(
        path, secrets=secrets or fsr_secrets.MemorySecretStore(),
        use_seed=False)


def test_real_retired_account_is_only_a_fingerprint():
    source = open(app_auth.__file__, encoding="utf-8").read()
    assert "@" not in "".join(app_auth.RETIRED_ACCOUNTS)
    assert not hasattr(app_auth, "BUILT_IN_USERS")
    assert not hasattr(app_auth.UserStore, "ensure_built_in_users")
    assert "built_in_users" not in source


def test_upgrade_over_an_earlier_install(tmp_path):
    """Owner + the built-in account + one site user, as on 9 November."""
    users = [account("OW", "owner@example.invalid", "owner-password-1",
                     role="owner"),
             account("BI", RETIRED_EMAIL.upper(), "builtin-password"),
             account("SU", "site@example.invalid", "site-password-12"),
             account("PE", "pending@example.invalid", "pending-pass-12",
                     status="pending")]
    path = old_file(tmp_path, users)
    original = path.read_bytes()

    store = open_store(path)

    # backed up first, byte for byte
    assert store.backup_path.name.startswith("users.before_update_")
    assert store.backup_path.read_bytes() == original
    # the built-in account is gone, the others are exactly as they were
    assert [u["initials"] for u in store.removed_accounts] == ["BI"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["version"] == 2
    assert saved["users"] == [users[0], users[2], users[3]]
    assert RETIRED_EMAIL not in path.read_text(encoding="utf-8").lower()
    # nobody has to do anything: same passwords, same roles
    assert not store.needs_setup
    assert store.sign_in("OW", "owner-password-1")["role"] == "owner"
    assert store.sign_in("SU", "site-password-12")["role"] == "user"
    with pytest.raises(app_auth.AuthError, match="waiting"):
        store.sign_in("PE", "pending-pass-12")
    with pytest.raises(app_auth.AuthError, match="Incorrect"):
        store.sign_in("BI", "builtin-password")


def test_update_happens_once(tmp_path):
    path = old_file(tmp_path, [
        account("OW", "owner@example.invalid", "owner-password-1",
                role="owner"),
        account("BI", RETIRED_EMAIL, "builtin-password")])
    secrets = fsr_secrets.MemorySecretStore()
    first = open_store(path, secrets)
    after = path.read_bytes()

    second = open_store(path, secrets)

    assert second.backup_path is None and second.removed_accounts == []
    assert path.read_bytes() == after
    assert len(list(tmp_path.glob("users.before_update_*.json"))) == 1
    assert first.backup_path.exists()


def test_old_file_without_the_retired_account_keeps_every_account(tmp_path):
    users = [account("OW", "owner@example.invalid", "owner-password-1",
                     role="owner"),
             account("SU", "site@example.invalid", "site-password-12")]
    path = old_file(tmp_path, users)
    store = open_store(path)
    assert store.removed_accounts == []
    assert store.backup_path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["users"] == users


def test_retired_account_as_the_only_approved_account(tmp_path):
    """The PC is not left without a way in: it asks for its Administrator
    (the one-time set-up); other accounts are kept."""
    waiting = account("PE", "pending@example.invalid", "pending-pass-12",
                      status="pending")
    path = old_file(tmp_path, [
        account("BI", RETIRED_EMAIL, "builtin-password"), waiting])

    store = open_store(path)

    assert [u["initials"] for u in store.list_users()] == ["PE"]
    assert store.needs_setup
    store.create_administrator("Site", "", "Admin", "SA",
                               "admin@example.invalid", "administrator-pass",
                               "administrator-pass")
    assert store.sign_in("SA", "administrator-pass")["role"] == "admin"
    store.set_status("pending@example.invalid", "approved")
    assert store.sign_in("PE", "pending-pass-12")["role"] == "user"


def test_initials_of_the_removed_account_can_be_used_again(tmp_path):
    path = old_file(tmp_path, [
        account("OW", "owner@example.invalid", "owner-password-1",
                role="owner"),
        account("BI", RETIRED_EMAIL, "builtin-password")])
    store = open_store(path)
    store.sign_up("Brand", "", "Individual", "BI", "new@example.invalid",
                  "another-pass-12", "another-pass-12")
    assert store.find_by_initials("BI")["email"] == "new@example.invalid"


def test_current_file_is_never_cleaned_or_backed_up(tmp_path):
    """Only a file of an earlier program is updated."""
    path = tmp_path / "users.json"
    users = [account("OW", "owner@example.invalid", "owner-password-1",
                     role="owner"),
             account("BI", RETIRED_EMAIL, "builtin-password")]
    path.write_text(json.dumps({"version": 2, "users": users}),
                    encoding="utf-8")
    store = open_store(path)
    assert store.backup_path is None
    assert len(store.list_users()) == 2


def test_no_backup_no_change(tmp_path, monkeypatch):
    path = old_file(tmp_path, [
        account("OW", "owner@example.invalid", "owner-password-1",
                role="owner"),
        account("BI", RETIRED_EMAIL, "builtin-password")])
    original = path.read_bytes()

    def no_copy(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(app_auth.shutil, "copy2", no_copy)
    with pytest.raises(OSError, match="disk full"):
        open_store(path)
    assert path.read_bytes() == original


def test_reports_of_the_removed_account_still_open(tmp_path):
    """A report names its author only by the initials inside its Control #;
    nothing looks the account up."""
    from datetime import date

    import factories
    import fsr_storage

    workbook = tmp_path / "reports.xlsx"
    control = "FSR-BI-202610-0001"
    fsr_storage.write_report_to_excel(
        workbook, factories.rec(control, date(2026, 10, 1), "C1", 5), False)

    path = old_file(tmp_path, [
        account("OW", "owner@example.invalid", "owner-password-1",
                role="owner"),
        account("BI", RETIRED_EMAIL, "builtin-password")])
    store = open_store(path)
    assert store.find_by_initials("BI") is None

    report = fsr_storage.read_report(workbook, control)
    assert report["control_no"] == control
    assert fsr_storage.control_initials_of(control) == "BI"
    assert [r["control_no"] for r in fsr_storage.read_all_reports(workbook)
            ] == [control]
    # the next report of someone with these initials continues the series
    assert fsr_storage.next_control_number([control], "BI").startswith(
        "FSR-BI-")
