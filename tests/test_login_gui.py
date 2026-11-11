"""The real sign-in window, driven without a person: first set-up, the
recovery code, and the review of a changed account file."""
import json
import tkinter
from tkinter import messagebox

import pytest

import app_auth
import fsr_secrets

pytestmark = pytest.mark.gui

ADMIN_PASS = "administrator-pass"
USER_PASS = "correct-horse-1"


@pytest.fixture(scope="module")
def root():
    import ttkbootstrap as tb
    try:
        window = tb.Window(themename="flatly")
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tkinter.TclError:
        pass


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def texts(window):
    """Every text a person can read in the window."""
    found = []
    for widget in widgets(window):
        if isinstance(widget, tkinter.Text):
            found.append(widget.get("1.0", "end").strip())
            continue
        try:
            found.append(str(widget.cget("text")))
        except tkinter.TclError:
            pass
    return "\n".join(t for t in found if t)


def entries(window):
    return [w for w in widgets(window) if w.winfo_class() == "TEntry"]


def click(window, label):
    for widget in widgets(window):
        if widget.winfo_class() == "TButton" and \
                str(widget.cget("text")) == label:
            widget.invoke()
            return
    raise AssertionError(f"no button {label!r} in:\n{texts(window)}")


def fill(window, *values):
    boxes = entries(window)
    assert len(boxes) == len(values), texts(window)
    for box, value in zip(boxes, values):
        box.delete(0, "end")
        box.insert(0, value)


def run(root, store, monkeypatch, steps):
    """Open the sign-in window; every time the program waits for the
    person, the next step is played on the window that is waiting."""
    script = list(steps)
    seen = []

    def wait_window(self, window=None):
        target = window or self
        while target.winfo_exists():
            assert script, "the window is still open:\n" + texts(target)
            step = script.pop(0)
            seen.append(texts(target))
            step(target)
            root.update()

    monkeypatch.setattr(tkinter.Misc, "wait_window", wait_window)
    monkeypatch.setattr(tkinter.Misc, "grab_set", lambda self: None)
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    user = app_auth.run_login(root, store)
    assert not script, f"{len(script)} step(s) were never reached"
    return user, seen


def close(window):
    window.destroy()


def new_pc(tmp_path):
    secrets = fsr_secrets.MemorySecretStore()
    path = tmp_path / "users.json"

    def open_store(secret_store=None):
        return app_auth.UserStore(
            path, secrets=secret_store or secrets, use_seed=False)

    return open_store, path


def set_up_pc(tmp_path):
    open_store, path = new_pc(tmp_path)
    store = open_store()
    store.create_administrator("Site", "", "Admin", "SA",
                               "admin@example.invalid", ADMIN_PASS,
                               ADMIN_PASS)
    store.mark_code_shown()
    store.sign_up("Test", "", "User", "TU", "user@example.invalid",
                  USER_PASS, USER_PASS)
    store.set_status("user@example.invalid", "approved")
    return open_store, path, store.recovery_code()


def make_tu_admin(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    document["users"][1]["role"] = "admin"
    path.write_text(json.dumps(document), encoding="utf-8")


def test_fresh_user_install_shows_the_one_time_setup(root, tmp_path,
                                                     monkeypatch):
    open_store, path = new_pc(tmp_path)
    store = open_store()
    shown = {}

    def create(window):
        shown["setup"] = texts(window)
        fill(window, "Site", "", "Admin", "SA", "admin@example.invalid",
             ADMIN_PASS, ADMIN_PASS)
        click(window, "Create Administrator Account")

    def note_code(window):                      # the recovery code window
        shown["code"] = texts(window)
        shown["value"] = entries(window)[0].get()
        click(window, "I have written it down")

    def sign_in(window):
        shown["sign_in"] = texts(window)
        fill(window, "SA", ADMIN_PASS)
        click(window, "Sign In")

    user, _ = _play_setup(root, store, monkeypatch, create, note_code,
                          sign_in)

    assert "Set Up This PC" in shown["setup"]
    assert "ADMINISTRATOR of this PC" in shown["setup"]
    assert "shown only once" in shown["setup"]
    assert "Create an account" not in shown["setup"]
    assert "Write this code down" in shown["code"]
    assert shown["value"] == store.recovery_code()
    assert "The Administrator account was created" in shown["sign_in"]
    assert user["role"] == "admin" and user["initials"] == "SA"
    assert store.code_shown

    # the next start goes straight to Sign In, with no set-up
    def look(window):
        shown["next"] = texts(window)
        close(window)

    user, _ = run(root, open_store(), monkeypatch, [look])
    assert user is None
    assert "Set Up This PC" not in shown["next"]
    assert "Create an account" in shown["next"]


def _play_setup(root, store, monkeypatch, create, note_code, sign_in):
    """Three waits: the set-up page, the code window that opens inside it,
    then the sign-in page."""
    state = {"stage": 0}

    def step(window):
        if "Recovery code of this PC" in texts(window):
            note_code(window)
        elif state["stage"] == 0:
            state["stage"] = 1
            create(window)
        else:
            sign_in(window)

    return run(root, store, monkeypatch, [step, step, step])


def test_administrator_sees_the_code_once_after_an_update(root, tmp_path,
                                                         monkeypatch):
    """An earlier users.json: signed at start, code shown at the first
    Administrator sign in, not again."""
    salt, digest = app_auth.hash_password("owner-password-1")
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": [{
        "first_name": "Old", "middle_name": "", "last_name": "Owner",
        "initials": "OO", "email": "owner@example.invalid", "salt": salt,
        "hash": digest, "role": "owner", "status": "approved"}]}),
        encoding="utf-8")
    secrets = fsr_secrets.MemorySecretStore()
    store = app_auth.UserStore(path, secrets=secrets, use_seed=False)
    codes = []

    def step(window):
        if "Recovery code of this PC" in texts(window):
            codes.append(entries(window)[0].get())
            click(window, "I have written it down")
        else:
            fill(window, "OO", "owner-password-1")
            click(window, "Sign In")

    user, _ = run(root, store, monkeypatch, [step, step])
    assert user["role"] == "owner" and codes == [store.recovery_code()]

    again = app_auth.UserStore(path, secrets=secrets, use_seed=False)
    user, _ = run(root, again, monkeypatch, [step])
    assert user["role"] == "owner" and len(codes) == 1


def test_changed_file_review_and_restore(root, tmp_path, monkeypatch):
    open_store, path, _ = set_up_pc(tmp_path)
    good = path.read_bytes()
    make_tu_admin(path)
    store = open_store()
    shown = {}
    state = {"stage": 0}

    def step(window):
        state["stage"] += 1
        if state["stage"] == 1:                 # the changed account tries
            shown["blocked"] = texts(window)
            fill(window, "TU", USER_PASS)
            click(window, "Sign In")
            shown["refused"] = texts(window)
            fill(window, "SA", ADMIN_PASS)      # the trusted Administrator
            click(window, "Sign In")
            shown["review"] = texts(window)
            click(window, "Restore the last good copy")
            shown["after"] = texts(window)
            fill(window, "SA", ADMIN_PASS)
            click(window, "Sign In")

    user, _ = run(root, store, monkeypatch, [step])

    assert "changed outside the program" in shown["blocked"]
    assert "Create an account" not in shown["blocked"]
    assert "Only an Administrator can sign in" in shown["refused"]
    assert "Review the Account File" in shown["review"]
    assert "role User -> Administrator" in shown["review"]
    assert "Accept the changed file" in shown["review"]
    assert "Start again with no accounts" not in shown["review"]
    assert "last good copy was restored" in shown["after"]
    assert user["initials"] == "SA" and store.problem is None
    assert path.read_bytes() != b"" and json.loads(good)["users"][1][
        "role"] == "user"
    assert open_store().find("user@example.invalid")["role"] == "user"


def test_changed_file_can_be_accepted(root, tmp_path, monkeypatch):
    open_store, path, _ = set_up_pc(tmp_path)
    make_tu_admin(path)
    store = open_store()

    def step(window):
        fill(window, "SA", ADMIN_PASS)
        click(window, "Sign In")
        click(window, "Accept the changed file")
        assert "changed file was accepted" in texts(window)
        fill(window, "TU", USER_PASS)
        click(window, "Sign In")

    user, _ = run(root, store, monkeypatch, [step])
    assert user["role"] == "admin" and store.problem is None


def test_moved_pc_asks_for_the_recovery_code(root, tmp_path, monkeypatch):
    open_store, path, code = set_up_pc(tmp_path)
    moved = open_store(fsr_secrets.MemorySecretStore())
    shown = {}

    def step(window):
        shown["first"] = texts(window)
        fill(window, "WRONG-CODE")
        click(window, "Continue")
        shown["wrong"] = texts(window)
        fill(window, code.lower())
        click(window, "Continue")
        shown["verified"] = texts(window)
        fill(window, "TU", USER_PASS)
        click(window, "Sign In")

    user, _ = run(root, moved, monkeypatch, [step])

    assert "Recovery Code" in shown["first"]
    assert "cannot be checked with this Windows login" in shown["first"]
    assert "Back to Sign In" not in shown["first"]
    assert "not the recovery code of this account file" in shown["wrong"]
    assert "checked with the recovery code" in shown["verified"]
    assert user["initials"] == "TU" and moved.problem is None


def test_missing_file_without_a_copy_starts_again_with_the_code(
        root, tmp_path, monkeypatch):
    open_store, path, code = set_up_pc(tmp_path)
    path.unlink()
    path.with_name("users.lastgood.json").unlink()
    store = open_store()
    shown = {}
    state = {"stage": 0}

    def step(window):
        if "Recovery code of this PC" in texts(window):
            click(window, "I have written it down")
            return
        state["stage"] += 1
        if state["stage"] == 1:
            shown["blocked"] = texts(window)
            click(window, "Use the recovery code instead")
            fill(window, code)
            click(window, "Continue")
            shown["review"] = texts(window)
            click(window, "Start again with no accounts")
            shown["setup"] = texts(window)
            fill(window, "New", "", "Admin", "NA", "new@example.invalid",
                 ADMIN_PASS, ADMIN_PASS)
            click(window, "Create Administrator Account")
        else:
            fill(window, "NA", ADMIN_PASS)
            click(window, "Sign In")

    # the review, the code window of the new set-up, the sign in
    user, _ = run(root, store, monkeypatch, [step, step, step])

    assert "missing, but this PC was already set up" in shown["blocked"]
    assert "Set Up This PC" not in shown["blocked"]
    assert "Restore the last good copy" not in shown["review"]
    assert "Accept the changed file" not in shown["review"]
    assert "Set Up This PC" in shown["setup"]
    assert user["initials"] == "NA" and user["role"] == "admin"
