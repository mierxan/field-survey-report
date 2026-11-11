"""users.json is signed: a file changed outside the program blocks sign in
until an Administrator of the LAST GOOD COPY has reviewed it; the recovery
code brings a moved PC back."""
import json
import shutil

import pytest

import app_auth
import fsr_secrets

ADMIN_PASS = "administrator-pass"
USER_PASS = "correct-horse-1"


@pytest.fixture
def pc(tmp_path):
    """A set-up PC: Administrator SA, approved user TU, pending user PE."""
    secrets = fsr_secrets.MemorySecretStore()
    path = tmp_path / "users.json"

    def open_store(secret_store=None):
        return app_auth.UserStore(
            path, secrets=secrets if secret_store is None else secret_store,
            use_seed=False)

    store = open_store()
    store.create_administrator("Site", "", "Admin", "SA",
                               "admin@example.invalid", ADMIN_PASS,
                               ADMIN_PASS)
    store.sign_up("Test", "", "User", "TU", "user@example.invalid",
                  USER_PASS, USER_PASS)
    store.set_status("user@example.invalid", "approved")
    store.sign_up("Pat", "", "Ending", "PE", "pending@example.invalid",
                  USER_PASS, USER_PASS)
    return store, path, open_store, secrets


def edit_by_hand(path, change):
    """What a person with a text editor does: the signature stays as is."""
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def make_self_admin(document):
    user = next(u for u in document["users"] if u["initials"] == "TU")
    user["role"] = "admin"


def approve_pending(document):
    user = next(u for u in document["users"] if u["initials"] == "PE")
    user["status"] = "approved"


# ---------- the signature itself ----------

def test_every_save_is_signed_and_copied(pc):
    store, path, open_store, _ = pc
    document = json.loads(path.read_text(encoding="utf-8"))
    code = store.recovery_code()
    assert app_auth.signature_ok(document, code)
    assert not app_auth.signature_ok(document, app_auth.new_recovery_code())
    assert path.read_bytes() == store.last_good_path.read_bytes()
    assert code not in path.read_text(encoding="utf-8")
    assert len(code) == 29 and code.count("-") == 5

    again = open_store()
    assert again.problem is None
    assert again.sign_in("TU", USER_PASS)["role"] == "user"
    assert path.read_bytes() == again.last_good_path.read_bytes()


def test_recovery_code_is_shown_once_to_an_administrator(pc):
    store, _, open_store, _ = pc
    assert not store.code_shown
    store.mark_code_shown()
    assert open_store().code_shown
    assert open_store().recovery_code() == store.recovery_code()


def test_typed_code_may_have_spaces_and_lower_case():
    assert app_auth.format_recovery_code(" abcd efgh-ijkl ") == \
        "ABCD-EFGH-IJKL"


# ---------- upgrade: an unsigned file of an earlier program ----------

def test_unsigned_file_of_an_earlier_program_is_adopted(tmp_path):
    salt, digest = app_auth.hash_password("owner-password-1")
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": [{
        "first_name": "Old", "middle_name": "", "last_name": "Owner",
        "initials": "OO", "email": "owner@example.invalid", "salt": salt,
        "hash": digest, "role": "owner", "status": "approved"}]}),
        encoding="utf-8")
    secrets = fsr_secrets.MemorySecretStore()

    store = app_auth.UserStore(path, secrets=secrets, use_seed=False)

    assert store.problem is None
    document = json.loads(path.read_text(encoding="utf-8"))
    assert app_auth.signature_ok(document, store.recovery_code())
    assert store.last_good_path.exists() and store.backup_path.exists()
    assert not store.code_shown            # the Administrator still has to
    assert store.sign_in("OO", "owner-password-1")["role"] == "owner"


def test_file_of_the_first_build_of_this_update_is_adopted(tmp_path):
    """Version 2 without a signature, set-up record without a code."""
    path = tmp_path / "users.json"
    fields = app_auth.new_password_fields(ADMIN_PASS)
    path.write_text(json.dumps({"version": 2, "users": [{
        "first_name": "Site", "middle_name": "", "last_name": "Admin",
        "initials": "SA", "email": "admin@example.invalid", **fields,
        "role": "admin", "status": "approved"}]}), encoding="utf-8")
    secrets = fsr_secrets.MemorySecretStore()
    secrets.set("accounts-" + __import__("hashlib").sha256(
        str(path.resolve()).casefold().encode("utf-8")).hexdigest()[:16],
        json.dumps({"setup": True}))

    store = app_auth.UserStore(path, secrets=secrets, use_seed=False)

    assert store.problem is None and store.backup_path is None
    assert store.sign_in("SA", ADMIN_PASS)["role"] == "admin"


def test_interrupted_first_signature_is_simply_repeated(pc, tmp_path):
    """The code was stored but the signed file never written."""
    _, path, _, _ = pc
    secrets = fsr_secrets.MemorySecretStore()
    document = json.loads(path.read_text(encoding="utf-8"))
    del document["signature"]
    other = tmp_path / "second" / "users.json"
    other.parent.mkdir()
    other.write_text(json.dumps(document), encoding="utf-8")
    name = "accounts-" + __import__("hashlib").sha256(
        str(other.resolve()).casefold().encode("utf-8")).hexdigest()[:16]
    secrets.set(name, json.dumps(
        {"setup": True, "code": app_auth.new_recovery_code(),
         "pending": True}))

    store = app_auth.UserStore(other, secrets=secrets, use_seed=False)

    assert store.problem is None
    assert "pending" not in json.loads(secrets.get(name))
    assert store.sign_in("SA", ADMIN_PASS)


# ---------- a file edited by hand after signing ----------

@pytest.mark.parametrize("change", [make_self_admin, approve_pending])
def test_hand_edit_blocks_every_sign_in_but_the_trusted_admin(pc, change):
    _, path, open_store, _ = pc
    edit_by_hand(path, change)

    store = open_store()

    assert store.problem["kind"] == "changed"
    assert not store.needs_setup
    # normal users - and the account that made itself admin - stay out
    for initials in ("TU", "PE"):
        with pytest.raises(app_auth.AuthError, match="Only an Administrator"):
            store.sign_in(initials, USER_PASS)
    # nothing can be changed while it is not reviewed
    with pytest.raises(app_auth.AuthError, match="reviewed"):
        store.set_status("pending@example.invalid", "approved")
    with pytest.raises(app_auth.AuthError, match="Sign in as an Admin"):
        store.accept_current()
    # the Administrator of the last good copy gets in, to review only
    reviewer = store.sign_in("SA", ADMIN_PASS)
    assert reviewer["role"] == "admin" and store.problem is not None


def test_edit_while_the_program_is_open_is_noticed_at_sign_in(pc):
    store, path, _, _ = pc
    assert store.problem is None
    edit_by_hand(path, make_self_admin)
    with pytest.raises(app_auth.AuthError, match="Only an Administrator"):
        store.sign_in("TU", USER_PASS)
    assert store.problem["kind"] == "changed"


def test_administrator_is_taken_from_the_trusted_copy_not_the_file(pc):
    """Replacing the Administrator's password in the file does not help."""
    _, path, open_store, _ = pc
    intruder = app_auth.new_password_fields("intruder-password")

    def take_over(document):
        document["users"][0].update(intruder)           # SA's password
        make_self_admin(document)

    edit_by_hand(path, take_over)
    store = open_store()
    with pytest.raises(app_auth.AuthError):
        store.sign_in("SA", "intruder-password")
    with pytest.raises(app_auth.AuthError):
        store.sign_in("TU", USER_PASS)
    assert store.sign_in("SA", ADMIN_PASS)["email"] == "admin@example.invalid"


def test_review_lists_what_was_changed(pc):
    _, path, open_store, _ = pc

    def several(document):
        make_self_admin(document)
        approve_pending(document)
        document["users"].append({
            "first_name": "Extra", "middle_name": "", "last_name": "Person",
            "initials": "EX", "email": "extra@example.invalid",
            **app_auth.new_password_fields("x" * 12), "role": "admin",
            "status": "approved"})
        document["users"][0].update(app_auth.new_password_fields("y" * 12))

    edit_by_hand(path, several)
    lines = "\n".join(open_store().changes())
    assert "NEW account: Extra Person (EX, extra@example.invalid) - " \
           "Administrator, Approved" in lines
    assert "CHANGED account: Test User (TU, user@example.invalid) - " \
           "role User -> Administrator" in lines
    assert "status pending -> approved" in lines
    assert "CHANGED account: Site Admin (SA, admin@example.invalid) - " \
           "password changed" in lines

    edit_by_hand(path, lambda d: d["users"].pop(1))
    assert "REMOVED account: Test User" in "\n".join(open_store().changes())


def test_restore_the_last_good_copy(pc):
    _, path, open_store, _ = pc
    good = path.read_bytes()
    edit_by_hand(path, make_self_admin)
    bad = path.read_bytes()
    store = open_store()
    store.sign_in("SA", ADMIN_PASS)
    assert store.can_restore() and store.can_accept()
    assert not store.can_start_over()

    kept = store.restore_last_good()

    assert store.problem is None
    assert path.read_bytes() == good
    assert kept.read_bytes() == bad and kept.name.startswith("users.rejected_")
    assert store.sign_in("TU", USER_PASS)["role"] == "user"
    assert open_store().problem is None


def test_accept_the_changed_file(pc):
    _, path, open_store, _ = pc
    edit_by_hand(path, approve_pending)
    store = open_store()
    store.sign_in("SA", ADMIN_PASS)

    store.accept_current()

    assert store.problem is None
    assert store.sign_in("PE", USER_PASS)["status"] == "approved"
    again = open_store()
    assert again.problem is None
    assert path.read_bytes() == again.last_good_path.read_bytes()


def test_wrong_passwords_at_the_review_are_slowed_down(pc):
    _, path, open_store, _ = pc
    edit_by_hand(path, make_self_admin)
    store = open_store()
    for _ in range(2):
        with pytest.raises(app_auth.AuthError, match="Only an Admin"):
            store.sign_in("SA", "wrong-password")
    with pytest.raises(app_auth.AuthError, match="Please wait"):
        store.sign_in("SA", ADMIN_PASS)


# ---------- the file is gone / replaced ----------

def test_deleted_file_is_tampering_and_can_be_restored(pc):
    _, path, open_store, _ = pc
    good = path.read_bytes()
    path.unlink()

    store = open_store()

    assert store.problem["kind"] == "missing" and not store.needs_setup
    assert not path.exists()
    assert not store.can_accept()
    store.sign_in("SA", ADMIN_PASS)
    assert store.restore_last_good() is None
    assert path.read_bytes() == good and store.problem is None


def test_file_replaced_by_an_unsigned_one(pc):
    """For example a users.json copied in from somewhere else."""
    _, path, open_store, _ = pc
    path.write_text(json.dumps({"users": [{
        "first_name": "In", "middle_name": "", "last_name": "Truder",
        "initials": "IT", "email": "intruder@example.invalid",
        **app_auth.new_password_fields("intruder-password"),
        "role": "owner", "status": "approved"}]}), encoding="utf-8")

    store = open_store()

    assert store.problem["kind"] == "unsigned"
    with pytest.raises(app_auth.AuthError):
        store.sign_in("IT", "intruder-password")
    assert "NEW account: In Truder" in "\n".join(store.changes())
    store.sign_in("SA", ADMIN_PASS)
    store.restore_last_good()
    assert store.sign_in("SA", ADMIN_PASS)["role"] == "admin"


def test_both_files_changed_needs_the_recovery_code(pc):
    """No trusted copy is left: nobody is an Administrator by password."""
    store, path, open_store, _ = pc
    code = store.recovery_code()
    edit_by_hand(path, make_self_admin)
    shutil.copyfile(path, store.last_good_path)

    store = open_store()

    assert store.problem["kind"] == "changed"
    assert store.trusted_users() is None and not store.can_restore()
    for initials, password in (("SA", ADMIN_PASS), ("TU", USER_PASS)):
        with pytest.raises(app_auth.AuthError):
            store.sign_in(initials, password)
    with pytest.raises(app_auth.AuthError, match="not the recovery code"):
        store.unlock_with_code("AAAA-AAAA-AAAA-AAAA-AAAA-AAAA")
    assert store.unlock_with_code(code.lower().replace("-", " ")) == "review"
    assert "no trusted earlier copy" in store.changes()[0]
    assert store.can_accept() and store.can_start_over()


def test_start_over_with_the_recovery_code(pc):
    store, path, open_store, _ = pc
    code = store.recovery_code()
    path.unlink()
    store.last_good_path.unlink()
    store = open_store()
    assert store.problem["kind"] == "missing"
    with pytest.raises(app_auth.AuthError, match="Sign in as an Admin"):
        store.start_over()
    store.unlock_with_code(code)

    store.start_over()

    assert store.problem is None and store.list_users() == []
    assert store.needs_setup
    store.create_administrator("New", "", "Admin", "NA",
                               "new@example.invalid", ADMIN_PASS, ADMIN_PASS)
    assert store.sign_in("NA", ADMIN_PASS)["role"] == "admin"
    assert store.recovery_code() == code


def test_start_over_is_not_offered_when_a_good_copy_exists(pc):
    store, path, open_store, _ = pc
    code = store.recovery_code()
    edit_by_hand(path, make_self_admin)
    store = open_store()
    store.unlock_with_code(code)
    assert store.can_restore() and not store.can_start_over()
    with pytest.raises(app_auth.AuthError, match="only offered"):
        store.start_over()


# ---------- a moved PC / restored backup ----------

def test_moved_pc_is_recovered_with_the_code(pc):
    """users.json arrives on a PC whose protected storage is empty."""
    store, path, open_store, _ = pc
    code = store.recovery_code()
    new_pc = fsr_secrets.MemorySecretStore()

    moved = open_store(new_pc)

    assert moved.problem["kind"] == "no_key"
    assert not moved.needs_setup
    with pytest.raises(app_auth.AuthError):
        moved.sign_in("SA", ADMIN_PASS)       # no key: nobody is trusted
    with pytest.raises(app_auth.AuthError, match="not the recovery code"):
        moved.unlock_with_code(app_auth.new_recovery_code())
    assert moved.problem is not None

    assert moved.unlock_with_code(code) == "verified"

    assert moved.problem is None
    assert moved.sign_in("SA", ADMIN_PASS)["role"] == "admin"
    assert moved.sign_in("TU", USER_PASS)["role"] == "user"
    assert open_store(new_pc).problem is None           # stays recovered
    assert open_store(new_pc).recovery_code() == code


def test_moved_and_edited_file_is_not_accepted_by_the_code(pc):
    store, path, open_store, _ = pc
    code = store.recovery_code()
    edit_by_hand(path, make_self_admin)
    moved = open_store(fsr_secrets.MemorySecretStore())
    with pytest.raises(app_auth.AuthError, match="not the recovery code"):
        moved.unlock_with_code(code)
    assert moved.problem["kind"] == "no_key"


def test_restored_backup_of_the_signed_file_just_works(pc):
    """An older users.json written by this program on this PC."""
    store, path, open_store, _ = pc
    backup = path.read_bytes()
    store.set_status("user@example.invalid", "disabled")
    path.write_bytes(backup)
    again = open_store()
    assert again.problem is None
    assert again.sign_in("TU", USER_PASS)["status"] == "approved"


def test_restored_backup_from_before_the_update_goes_to_review(tmp_path):
    """The users.before_update_... file put back over users.json."""
    salt, digest = app_auth.hash_password("owner-password-1")
    old = json.dumps({"users": [{
        "first_name": "Old", "middle_name": "", "last_name": "Owner",
        "initials": "OO", "email": "owner@example.invalid", "salt": salt,
        "hash": digest, "role": "owner", "status": "approved"}]})
    path = tmp_path / "users.json"
    path.write_text(old, encoding="utf-8")
    secrets = fsr_secrets.MemorySecretStore()
    first = app_auth.UserStore(path, secrets=secrets, use_seed=False)
    first.sign_in("OO", "owner-password-1")           # re-hashed at 600,000
    shutil.copyfile(first.backup_path, path)

    store = app_auth.UserStore(path, secrets=secrets, use_seed=False)

    assert store.problem["kind"] == "unsigned"
    store.sign_in("OO", "owner-password-1")
    store.accept_current()
    assert store.problem is None
    assert store.sign_in("OO", "owner-password-1")["role"] == "owner"


def test_broken_protected_storage_is_reported_not_ignored(tmp_path):
    class Broken(fsr_secrets.MemorySecretStore):
        def get(self, name):
            raise fsr_secrets.SecretStoreError("locked")

    with pytest.raises(app_auth.UserDataError, match="protected storage"):
        app_auth.UserStore(tmp_path / "users.json", secrets=Broken(),
                           use_seed=False)

    class ReadOnly(fsr_secrets.MemorySecretStore):
        def set(self, name, value):
            raise fsr_secrets.SecretStoreError("denied")

    store = app_auth.UserStore(tmp_path / "users.json", secrets=ReadOnly(),
                               use_seed=False)
    with pytest.raises(app_auth.UserDataError, match="was not changed"):
        store.create_administrator("Site", "", "Admin", "SA",
                                   "admin@example.invalid", ADMIN_PASS,
                                   ADMIN_PASS)
    assert not (tmp_path / "users.json").exists()
