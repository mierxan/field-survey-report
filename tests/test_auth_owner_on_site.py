"""The Owner account on a site PC: forced new password at its first sign
in, and nobody but the Owner can change that account."""
import json

import pytest

import app_auth
import fsr_secrets

OLD = "old-owner-password"
NEW = "new-owner-password-2"
ADMIN_PASS = "administrator-pass"
USER_PASS = "correct-horse-1"


def old_account(initials, email, password, role="user"):
    salt, digest = app_auth.hash_password(password)     # 9 November style
    return {"first_name": initials, "middle_name": "", "last_name": "Person",
            "initials": initials, "email": email, "salt": salt,
            "hash": digest, "role": role, "status": "approved"}


@pytest.fixture
def site(tmp_path):
    """A site PC as the earlier installer left it, opened by the update."""
    path = tmp_path / "users.json"
    owner = old_account("OW", "owner@example.invalid", OLD, role="owner")
    path.write_text(json.dumps({"users": [
        owner, old_account("SU", "site@example.invalid", USER_PASS)]}),
        encoding="utf-8")
    secrets = fsr_secrets.MemorySecretStore()

    def open_store(**kw):
        return app_auth.UserStore(path, secrets=secrets, use_seed=False,
                                  site_pc=True, **kw)

    return open_store(), path, owner, open_store


def everything_in(folder):
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted(folder.glob("users*.json")))


# ---------- forced new password ----------

def test_old_owner_password_only_allows_setting_a_new_one(site):
    store, path, owner, _ = site
    for _ in range(3):                    # every time, not only the first
        with pytest.raises(app_auth.MustChangePassword, match="new password"):
            store.sign_in("OW", OLD)
    saved = json.loads(path.read_text(encoding="utf-8"))["users"][0]
    assert saved["hash"] == owner["hash"] and "iterations" not in saved
    # other accounts sign in normally and are upgraded as usual
    assert store.sign_in("SU", USER_PASS)["iterations"] == 600_000


def test_new_password_removes_the_old_hash_everywhere_on_that_pc(site):
    store, path, owner, open_store = site
    folder = path.parent
    assert owner["hash"] in store.backup_path.read_text(encoding="utf-8")
    assert owner["hash"] in store.last_good_path.read_text(encoding="utf-8")

    user = store.replace_old_password("OW", OLD, NEW, NEW)

    assert user["role"] == "owner" and user["iterations"] == 600_000
    text = everything_in(folder)
    assert owner["hash"] not in text and owner["salt"] not in text
    # the backup keeps the other accounts exactly as they were
    backup = json.loads(store.backup_path.read_text(encoding="utf-8"))
    assert backup["users"][0]["hash"] == "" == backup["users"][0]["salt"]
    assert backup["users"][0]["email"] == "owner@example.invalid"
    assert backup["users"][1]["hash"] != ""
    # from now on: a normal sign in with the new password only
    assert store.sign_in("OW", NEW)["role"] == "owner"
    with pytest.raises(app_auth.AuthError, match="Incorrect"):
        store.sign_in("OW", OLD)
    assert open_store().sign_in("OW", NEW)["role"] == "owner"
    assert open_store().problem is None


@pytest.mark.parametrize("new, confirm, message", [
    ("short", "short", "at least 12"),
    (NEW, NEW + "x", "do not match"),
    (OLD, OLD, "must be different"),
])
def test_unusable_new_password_changes_nothing(site, new, confirm, message):
    store, path, owner, _ = site
    with pytest.raises(app_auth.AuthError, match=message):
        store.replace_old_password("OW", OLD, new, confirm)
    assert json.loads(path.read_text(encoding="utf-8"))["users"][0][
        "hash"] == owner["hash"]
    with pytest.raises(app_auth.MustChangePassword):
        store.sign_in("OW", OLD)


def test_wrong_old_password_cannot_set_a_new_one(site):
    store, path, owner, _ = site
    with pytest.raises(app_auth.AuthError, match="Incorrect"):
        store.replace_old_password("OW", "not-the-password", NEW, NEW)
    assert owner["hash"] in path.read_text(encoding="utf-8")


def test_lockout_applies_to_this_sign_in_too(site, tmp_path):
    from datetime import datetime, timedelta
    store, path, owner, open_store = site
    now = {"t": datetime(2026, 11, 12, 9, 0)}
    store = open_store(clock=lambda: now["t"])
    for _ in range(app_auth.MAX_FAILURES):
        with pytest.raises(app_auth.AuthError):
            store.replace_old_password("OW", "wrong-password", NEW, NEW)
        now["t"] += timedelta(seconds=11)
    with pytest.raises(app_auth.AuthError, match="locked for"):
        store.sign_in("OW", OLD)
    with pytest.raises(app_auth.AuthError, match="locked for"):
        store.replace_old_password("OW", OLD, NEW, NEW)
    assert owner["hash"] in path.read_text(encoding="utf-8")
    now["t"] += timedelta(minutes=15)
    assert store.replace_old_password("OW", OLD, NEW, NEW)["role"] == "owner"


def test_account_that_needs_no_change_is_refused(site):
    store, _, _, _ = site
    with pytest.raises(app_auth.AuthError, match="does not need"):
        store.replace_old_password("SU", USER_PASS, NEW, NEW)
    store.replace_old_password("OW", OLD, NEW, NEW)
    with pytest.raises(app_auth.AuthError, match="does not need"):
        store.replace_old_password("OW", NEW, "another-password-3",
                                   "another-password-3")


def test_owner_pc_is_not_forced(tmp_path):
    """On the owner's own PC the old password is upgraded as before."""
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": [
        old_account("OW", "owner@example.invalid", OLD, role="owner")]}),
        encoding="utf-8")
    store = app_auth.UserStore(path, secrets=fsr_secrets.MemorySecretStore(),
                               use_seed=False)
    assert store.sign_in("OW", OLD)["iterations"] == 600_000


def test_rejected_copies_lose_the_old_hash_as_well(site):
    store, path, owner, _ = site
    rejected = path.with_name("users.rejected_20261112_090000.json")
    rejected.write_text(json.dumps({"users": [dict(owner)]}),
                        encoding="utf-8")
    store.replace_old_password("OW", OLD, NEW, NEW)
    assert owner["hash"] not in rejected.read_text(encoding="utf-8")


# ---------- nobody but the Owner changes the Owner account ----------

@pytest.fixture
def with_admin(tmp_path):
    """A site PC with the Owner, a site Administrator and a user. (The
    Administrator is written straight into the file: the program itself
    never creates one while an Owner exists.)"""
    path = tmp_path / "users.json"
    admin = {"first_name": "Site", "middle_name": "", "last_name": "Admin",
             "initials": "SA", "email": "admin@example.invalid",
             **app_auth.new_password_fields(ADMIN_PASS), "role": "admin",
             "status": "approved"}
    owner = {**old_account("OW", "owner@example.invalid", OLD, "owner"),
             **app_auth.new_password_fields(NEW)}
    path.write_text(json.dumps({"version": 2, "users": [
        owner, admin, old_account("SU", "site@example.invalid", USER_PASS)]}),
        encoding="utf-8")
    store = app_auth.UserStore(path, secrets=fsr_secrets.MemorySecretStore(),
                               use_seed=False, site_pc=True)
    assert store.sign_in("SA", ADMIN_PASS)["role"] == "admin"
    return store, path


def owner_record(path):
    return json.loads(path.read_text(encoding="utf-8"))["users"][0]


def test_site_administrator_cannot_remove_the_owner(with_admin):
    store, path = with_admin
    before = owner_record(path)
    with pytest.raises(app_auth.AuthError, match="Owner account cannot"):
        store.delete("owner@example.invalid")
    assert owner_record(path) == before


@pytest.mark.parametrize("status", ["disabled", "rejected", "pending"])
def test_site_administrator_cannot_disable_the_owner(with_admin, status):
    store, path = with_admin
    before = owner_record(path)
    with pytest.raises(app_auth.AuthError, match="Owner account cannot"):
        store.set_status("owner@example.invalid", status)
    assert owner_record(path) == before


def test_site_administrator_cannot_reset_the_owner_password(with_admin):
    store, path = with_admin
    before = owner_record(path)
    with pytest.raises(app_auth.AuthError, match="Only the Owner can"):
        store.set_password("owner@example.invalid", "taken-over-pass-1")
    assert owner_record(path) == before
    assert store.sign_in("OW", NEW)["role"] == "owner"
    with pytest.raises(app_auth.AuthError, match="Incorrect"):
        store.sign_in("OW", "taken-over-pass-1")


def test_owner_password_change_needs_the_owner_password(with_admin):
    store, path = with_admin
    with pytest.raises(app_auth.AuthError, match="current password"):
        store.change_own_password("owner@example.invalid", ADMIN_PASS,
                                  "taken-over-pass-1", "taken-over-pass-1")
    store.change_own_password("owner@example.invalid", NEW,
                              "owner-third-pass-3", "owner-third-pass-3")
    assert store.sign_in("OW", "owner-third-pass-3")["role"] == "owner"


def test_there_is_no_way_to_change_a_role(with_admin):
    """No function of the account store changes a role (so the Owner cannot
    be demoted and nobody can be promoted); an edit of the file itself is
    caught by the signature."""
    store, path = with_admin
    public = [name for name in dir(store) if not name.startswith("_")]
    assert not [name for name in public if "role" in name.lower()]
    for email in ("owner@example.invalid", "admin@example.invalid",
                  "site@example.invalid"):
        role = store.find(email)["role"]
        for action in (lambda: store.set_status(email, "approved"),  # noqa: B023 - used in this same pass
                       lambda: store.set_password(email, "some-password-9")):  # noqa: B023 - used in this same pass
            try:
                action()
            except app_auth.AuthError:
                pass
        assert store.find(email)["role"] == role

    document = json.loads(path.read_text(encoding="utf-8"))
    document["users"][0]["role"] = "user"              # demote by hand
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(app_auth.AuthError, match="Only an Administrator"):
        store.sign_in("SU", USER_PASS)
    assert store.problem["kind"] == "changed"
    # in the review the Owner of the last good copy is still the Owner
    assert store.sign_in("OW", NEW)["role"] == "owner"


def test_site_administrator_can_still_manage_normal_users(with_admin):
    store, _ = with_admin
    store.set_status("site@example.invalid", "disabled")
    store.set_password("site@example.invalid", "reset-by-admin-1")
    store.set_status("site@example.invalid", "approved")
    assert store.sign_in("SU", "reset-by-admin-1")["role"] == "user"


# ---------- the recovery code needs the password again ----------

def test_recovery_code_needs_the_administrator_password_again(with_admin):
    store, _ = with_admin
    admin = store.find("admin@example.invalid")
    user = store.find("site@example.invalid")
    code = store.recovery_code()

    assert store.recovery_code_for(admin, ADMIN_PASS) == code
    with pytest.raises(app_auth.AuthError, match="Incorrect"):
        store.recovery_code_for(admin, "wrong-password")
    with pytest.raises(app_auth.AuthError, match="Only an Administrator"):
        store.recovery_code_for(user, USER_PASS)
    # a user's session cannot borrow the Administrator's name
    with pytest.raises(app_auth.AuthError):
        store.recovery_code_for({**admin, "initials": "SU"}, USER_PASS)
    with pytest.raises(app_auth.AuthError):
        store.recovery_code_for({**user, "role": "admin"}, USER_PASS)


def test_wrong_passwords_for_the_code_lock_the_account(with_admin):
    store, _ = with_admin
    admin = store.find("admin@example.invalid")
    with pytest.raises(app_auth.AuthError, match="Incorrect"):
        store.recovery_code_for(admin, "wrong-password")
    with pytest.raises(app_auth.AuthError, match="Incorrect"):
        store.recovery_code_for(admin, "wrong-password")
    with pytest.raises(app_auth.AuthError, match="Please wait"):
        store.recovery_code_for(admin, ADMIN_PASS)
