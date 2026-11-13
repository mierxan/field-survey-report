"""make-seed and its command line, and the owner actions of the account
store that the windows do not reach. Every seed here is a temporary file:
the program's own data/json/private/auth_seed.json is never written."""
import json

import pytest

import app_auth
import fsr_secrets

OWNER = {"first_name": " Olga ", "middle_name": "", "last_name": "Owner",
         "initials": "oo", "email": "Olga.Owner@Example.invalid"}
GOOD = "owner-password-123"


def test_make_seed_writes_names_and_a_hash_never_the_password(tmp_path):
    seed = tmp_path / "auth_seed.json"
    record = app_auth.make_seed(GOOD, OWNER, path=seed)
    text = seed.read_text(encoding="utf-8")
    assert GOOD not in text
    saved = json.loads(text)["owner"]
    assert saved == record
    assert (saved["first_name"], saved["initials"], saved["email"]) == \
        ("Olga", "OO", "olga.owner@example.invalid")
    assert app_auth.user_password_matches(saved, GOOD)
    assert not list(tmp_path.glob("*.tmp"))


def test_make_seed_keeps_the_names_of_the_seed_already_there(tmp_path):
    seed = tmp_path / "auth_seed.json"
    first = app_auth.make_seed(GOOD, OWNER, path=seed)
    again = app_auth.make_seed("another-password-9", path=seed)
    assert again["email"] == first["email"] and again["hash"] != first["hash"]
    assert app_auth.user_password_matches(again, "another-password-9")


@pytest.mark.parametrize("content", [None, "{broken", '["a list"]',
                                     '{"owner": "text"}'])
def test_make_seed_without_an_owner_writes_nothing(tmp_path, content):
    seed = tmp_path / "auth_seed.json"
    if content is not None:
        seed.write_text(content, encoding="utf-8")
    with pytest.raises(app_auth.AuthError, match="No owner was found"):
        app_auth.make_seed(GOOD, path=seed)
    assert (seed.read_text(encoding="utf-8") if seed.exists() else None) \
        == content


def test_make_seed_refuses_a_short_password_or_missing_names(tmp_path):
    seed = tmp_path / "auth_seed.json"
    with pytest.raises(app_auth.AuthError, match="at least"):
        app_auth.make_seed("short", OWNER, path=seed)
    with pytest.raises(app_auth.AuthError, match="first name, last name"):
        app_auth.make_seed(GOOD, dict(OWNER, email="not-an-email"),
                           path=seed)
    assert not seed.exists()


# ---------- python app_auth.py make-seed ----------

@pytest.fixture
def cli(tmp_path, monkeypatch):
    """_main with the seed redirected to a temporary file and the two
    password prompts answered."""
    seed = tmp_path / "auth_seed.json"
    app_auth.make_seed(GOOD, OWNER, path=seed)
    real = app_auth.make_seed
    monkeypatch.setattr(app_auth, "make_seed",
                        lambda password: real(password, path=seed))
    answers = []
    import getpass
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": answers.pop(0))
    return seed, answers


def test_the_command_line_rewrites_the_seed(cli, capsys):
    seed, answers = cli
    answers[:] = ["new-owner-pass-1", "new-owner-pass-1"]
    assert app_auth._main(["make-seed"]) == 0
    out = capsys.readouterr().out
    assert "new hash for OO" in out and "Rebuild the Owner installer" in out
    assert "new-owner-pass-1" not in out
    saved = json.loads(seed.read_text(encoding="utf-8"))["owner"]
    assert app_auth.user_password_matches(saved, "new-owner-pass-1")


def test_the_command_line_changes_nothing_on_a_mismatch_or_error(cli,
                                                                 capsys):
    seed, answers = cli
    before = seed.read_bytes()
    answers[:] = ["new-owner-pass-1", "new-owner-pass-2"]
    assert app_auth._main(["make-seed"]) == 1
    assert "do not match. Nothing was changed." in capsys.readouterr().out
    answers[:] = ["short", "short"]
    assert app_auth._main(["make-seed"]) == 1
    assert "Nothing was changed." in capsys.readouterr().out
    assert seed.read_bytes() == before


def test_the_command_line_without_make_seed_shows_how_to_use_it(capsys):
    assert app_auth._main([]) == 2
    assert app_auth._main(["something"]) == 2
    assert "Usage:  python app_auth.py make-seed" in capsys.readouterr().out


# ---------- owner actions on accounts that are not there ----------

def store_with_user(tmp_path):
    store = app_auth.UserStore(tmp_path / "users.json",
                               secrets=fsr_secrets.MemorySecretStore(),
                               use_seed=False)
    store.create_administrator("Site", "", "Admin", "SA",
                               "admin@example.invalid", "admin-pass-123",
                               "admin-pass-123")
    store.sign_up("Test", "", "User", "TU", "user@example.invalid",
                  "user-pass-1234", "user-pass-1234")
    return store


def test_actions_on_an_unknown_account_are_refused(tmp_path):
    store = store_with_user(tmp_path)
    before = (tmp_path / "users.json").read_bytes()
    with pytest.raises(app_auth.AuthError, match="not found"):
        store.delete("nobody@example.invalid")
    with pytest.raises(app_auth.AuthError, match="not found"):
        store.set_password("nobody@example.invalid", "a-long-password")
    with pytest.raises(app_auth.AuthError, match="not correct"):
        store.change_own_password("nobody@example.invalid", "x", "y", "y")
    assert (tmp_path / "users.json").read_bytes() == before


def test_a_password_reset_also_ends_a_lock(tmp_path):
    store = store_with_user(tmp_path)
    store.set_status("user@example.invalid", "approved")
    for _ in range(app_auth.MAX_FAILURES):
        with pytest.raises(app_auth.AuthError):
            store.sign_in("TU", "wrong-password")
    with pytest.raises(app_auth.AuthError):         # locked: even the right
        store.sign_in("TU", "user-pass-1234")       # password is refused
    store.set_password("user@example.invalid", "fresh-password-1")
    assert store.sign_in("TU", "fresh-password-1")["email"] == \
        "user@example.invalid"
