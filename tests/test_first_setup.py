"""A PC installed without any account (User edition): the first account is
its Administrator, once - and the build check that keeps accounts out of
the User installer."""
import json
import zipfile
from pathlib import Path

import pytest

import app_auth
import fsr_build_check
import fsr_secrets

ROOT = Path(__file__).resolve().parent.parent
ADMIN = ("Site", "", "Admin", "SA", "admin@example.invalid",
         "administrator-pass", "administrator-pass")


def new_store(tmp_path, secrets=None, **kw):
    return app_auth.UserStore(
        tmp_path / "users.json",
        secrets=secrets if secrets is not None
        else fsr_secrets.MemorySecretStore(), **kw)


def test_fresh_user_install_asks_for_the_administrator_once(tmp_path):
    store = new_store(tmp_path, use_seed=False)
    assert store.needs_setup
    assert store.list_users() == []

    store.create_administrator(*ADMIN)

    assert not store.needs_setup
    user = store.sign_in("SA", "administrator-pass")
    assert user["role"] == "admin" and user["status"] == "approved"
    assert app_auth.is_admin(user)
    assert app_auth.role_text(user) == "Administrator"
    with pytest.raises(app_auth.AuthError, match="already has an Admin"):
        store.create_administrator(
            "Other", "", "Person", "OP", "other@example.invalid",
            "another-password", "another-password")


def test_user_edition_ignores_a_seed(tmp_path, monkeypatch):
    salt, digest = app_auth.hash_password("owner-password")
    monkeypatch.setattr(app_auth, "OWNER", {
        "first_name": "Test", "middle_name": "", "last_name": "Owner",
        "initials": "TO", "email": "owner@example.invalid",
        "salt": salt, "hash": digest})
    store = new_store(tmp_path, use_seed=False)
    assert store.list_users() == []
    assert store.needs_setup


def test_administrator_approves_later_accounts(tmp_path):
    store = new_store(tmp_path, use_seed=False)
    store.create_administrator(*ADMIN)
    store.sign_up("Test", "", "User", "TU", "user@example.invalid",
                  "correct-horse", "correct-horse")
    with pytest.raises(app_auth.AuthError, match="waiting"):
        store.sign_in("TU", "correct-horse")
    store.set_status("user@example.invalid", "approved")
    user = store.sign_in("TU", "correct-horse")
    assert user["role"] == "user" and not app_auth.is_admin(user)


def test_administrator_account_is_protected(tmp_path):
    store = new_store(tmp_path, use_seed=False)
    store.create_administrator(*ADMIN)
    with pytest.raises(app_auth.AuthError, match="Administrator account"):
        store.set_status("admin@example.invalid", "disabled")
    with pytest.raises(app_auth.AuthError, match="Administrator account"):
        store.delete("admin@example.invalid")


def test_setup_checks_the_account_like_a_sign_up(tmp_path):
    store = new_store(tmp_path, use_seed=False)
    with pytest.raises(app_auth.AuthError, match="at least 12"):
        store.create_administrator(
            "Site", "", "Admin", "SA", "admin@example.invalid",
            "short", "short")
    assert store.needs_setup and store.list_users() == []


def test_deleting_users_json_does_not_offer_the_setup_again(tmp_path):
    secrets = fsr_secrets.MemorySecretStore()
    store = new_store(tmp_path, secrets, use_seed=False)
    store.create_administrator(*ADMIN)

    (tmp_path / "users.json").unlink()
    (tmp_path / "users.lastgood.json").unlink()

    again = new_store(tmp_path, secrets, use_seed=False)
    assert again.problem["kind"] == "missing"
    assert "already set up" in again.problem["text"]
    assert not again.needs_setup                 # no second set-up screen
    with pytest.raises(app_auth.AuthError):
        again.create_administrator(
            "Other", "", "Person", "OP", "other@example.invalid",
            "another-password", "another-password")
    with pytest.raises(app_auth.AuthError, match="reviewed"):
        again.sign_up("Other", "", "Person", "OP", "other@example.invalid",
                      "another-password", "another-password")
    assert not (tmp_path / "users.json").exists()


def test_existing_install_is_recorded_as_set_up(tmp_path):
    """An upgrade over an install that already has its owner account."""
    salt, digest = app_auth.hash_password("owner-password")
    (tmp_path / "users.json").write_text(json.dumps({"users": [{
        "first_name": "Old", "middle_name": "", "last_name": "Owner",
        "initials": "OO", "email": "owner@example.invalid", "salt": salt,
        "hash": digest, "role": "owner", "status": "approved"}]}),
        encoding="utf-8")
    secrets = fsr_secrets.MemorySecretStore()
    store = new_store(tmp_path, secrets, use_seed=False)
    assert not store.needs_setup
    assert store.sign_in("OO", "owner-password")["role"] == "owner"

    (tmp_path / "users.json").unlink()
    again = new_store(tmp_path, secrets, use_seed=False)
    assert again.problem["kind"] == "missing" and not again.needs_setup


# ---------- secret stores ----------

def test_file_secret_store_round_trip(tmp_path):
    store = fsr_secrets.FileSecretStore(tmp_path / "deep" / "secrets.json")
    assert store.get("a") is None
    store.set("a", "one")
    store.set("b", "two")
    assert store.get("a") == "one"
    store.delete("a")
    store.delete("missing")
    assert store.get("a") is None and store.get("b") == "two"


def test_tests_and_sandboxes_never_get_the_credential_manager(tmp_path):
    memory = fsr_secrets.default_store(
        tmp_path, environ={"FSR_SECRET_STORE": "memory"}, frozen=False)
    assert isinstance(memory, fsr_secrets.MemorySecretStore)
    sandbox = fsr_secrets.default_store(
        tmp_path, environ={"FSR_HOME": str(tmp_path)}, frozen=True)
    assert isinstance(sandbox, fsr_secrets.FileSecretStore)
    # the installed program does not obey the test switch
    installed = fsr_secrets.default_store(
        tmp_path, environ={"FSR_SECRET_STORE": "memory"}, frozen=True)
    assert not isinstance(installed, fsr_secrets.MemorySecretStore)


# ---------- the build check ----------

VALUES = {"owner@example.invalid": "email of an account in auth_seed.json",
          "ab" * 32: "hash of an account in auth_seed.json"}


def test_build_check_passes_a_clean_folder(tmp_path):
    (tmp_path / "_internal").mkdir()
    (tmp_path / "_internal" / "edition.json").write_text('{"edition":"user"}')
    (tmp_path / "FieldSurveyReport.exe").write_bytes(b"MZ\x00\x01binary")
    assert fsr_build_check.find_problems(tmp_path, VALUES) == []


@pytest.mark.parametrize("name", fsr_build_check.FORBIDDEN_NAMES)
def test_build_check_rejects_account_files(tmp_path, name):
    folder = tmp_path / "_internal" / "data" / "json" / "private"
    folder.mkdir(parents=True)
    (folder / name).write_text("{}")
    problems = fsr_build_check.find_problems(tmp_path, VALUES)
    assert len(problems) == 1 and name in problems[0]


def test_build_check_finds_a_hash_inside_any_file(tmp_path):
    (tmp_path / "notes.bin").write_bytes(
        b"\x00\x01" + ("AB" * 32).encode() + b"\x02")
    (tmp_path / "wide.dat").write_bytes(
        "x Owner@Example.invalid y".lower().encode("utf-16-le"))
    with zipfile.ZipFile(tmp_path / "base_library.zip", "w") as archive:
        archive.writestr("inner/seed.txt", "owner@example.invalid")
    problems = "\n".join(fsr_build_check.find_problems(tmp_path, VALUES))
    assert "notes.bin: contains the hash" in problems
    assert "wide.dat: contains the email" in problems
    assert "inner/seed.txt: contains the email" in problems


def test_build_check_reads_the_private_account_files(tmp_path):
    (tmp_path / "auth_seed.json").write_text(json.dumps({
        "owner": {"email": "owner@example.invalid", "salt": "c" * 32,
                  "hash": "d" * 64, "initials": "TO"}}))
    (tmp_path / "users.json").write_text(json.dumps({"users": [
        {"email": "site@example.invalid", "salt": "e" * 32,
         "hash": "f" * 64}]}))
    values = fsr_build_check.private_values(tmp_path)
    assert set(values) == {"owner@example.invalid", "c" * 32, "d" * 64,
                           "site@example.invalid", "e" * 32, "f" * 64}


def test_build_check_exit_codes(tmp_path, capsys):
    assert fsr_build_check.main([str(tmp_path / "missing")]) == 1
    (tmp_path / "users.json").write_text("{}")
    assert fsr_build_check.main([str(tmp_path)]) == 1
    (tmp_path / "users.json").unlink()
    assert fsr_build_check.main([str(tmp_path)]) == 0
    assert "clean" in capsys.readouterr().out


def test_installer_script_keeps_the_seed_out_of_the_user_edition():
    script = (ROOT / "build_installer.bat").read_text(encoding="utf-8")
    seed_lines = [line for line in script.splitlines()
                  if "auth_seed.json" in line and not
                  line.lstrip().lower().startswith("rem")]
    assert len(seed_lines) == 1
    assert seed_lines[0].lstrip().startswith('if /i "%ED%"=="Owner"')
    assert 'fsr_build_check.py "dist\\User\\FieldSurveyReport"' in script


def test_credential_manager_reads_back_what_it_wrote():
    """The real Windows store, with a throwaway entry: reading an existing
    entry needs win32timezone, which an installer once left out."""
    try:
        store = fsr_secrets.WindowsCredentialStore()
    except fsr_secrets.SecretStoreError:
        pytest.skip("no Windows Credential Manager here")
    name = "selftest-delete-me"
    try:
        store.set(name, "v\u00e4lue 1")
        assert store.get(name) == "v\u00e4lue 1"
        store.set(name, "value 2")
        assert store.get(name) == "value 2"
    finally:
        store.delete(name)
    assert store.get(name) is None


def test_installer_script_bundles_what_the_credential_manager_needs():
    script = (ROOT / "build_installer.bat").read_text(encoding="utf-8")
    for module in ("win32cred", "win32timezone"):
        assert f"--hidden-import {module} " in script
    source = (ROOT / "fsr_secrets.py").read_text(encoding="utf-8")
    assert "import win32timezone" in source
