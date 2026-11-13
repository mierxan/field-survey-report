"""Account windows, driven without a person: Manage Users (approve, reject,
disable, enable, reset password, delete - and what the Administrator and
Owner accounts refuse), the new-password prompt, and Change Password.
Invented accounts in a temporary folder; secrets stay in memory."""
import tkinter
from tkinter import messagebox

import pytest

import app_auth
from test_login_gui import (ADMIN_PASS, USER_PASS, click, entries, fill,
                            root, set_up_pc, texts)

pytestmark = pytest.mark.gui
assert root                     # the shared window fixture (imported)

USER = "user@example.invalid"
ADMIN = "admin@example.invalid"


class Boxes:
    """Message boxes answered and recorded."""

    def __init__(self, monkeypatch, yes=True):
        self.calls = []
        self.yes = yes
        for name in ("showinfo", "showwarning", "showerror"):
            monkeypatch.setattr(messagebox, name, self._show(name))
        monkeypatch.setattr(messagebox, "askyesno", self._ask)

    def _show(self, name):
        def show(title, message, **_):
            self.calls.append((name, message))
        return show

    def _ask(self, title, message, **_):
        self.calls.append(("askyesno", message))
        return self.yes


def no_waiting(monkeypatch, root, script):
    """Each time a window waits for the person, play the next step."""
    def wait_window(self, window=None):
        target = window or self
        while target.winfo_exists():
            assert script, "still open:\n" + texts(target)
            script.pop(0)(target)
            root.update()
    monkeypatch.setattr(tkinter.Misc, "wait_window", wait_window)
    monkeypatch.setattr(tkinter.Misc, "grab_set", lambda self: None)


def manage(root, store, changes=None):
    before = set(root.winfo_children())
    app_auth.open_manage_users(root, store, store.find(ADMIN),
                               on_change=((lambda: changes.append(1))
                                          if changes is not None else None))
    (dialog,) = set(root.winfo_children()) - before
    tree = next(w for w in _all(dialog) if w.winfo_class() == "Treeview")
    return dialog, tree


def _all(parent):
    for child in parent.winfo_children():
        yield child
        yield from _all(child)


def rows(tree):
    return [tree.item(i, "values") for i in tree.get_children()]


def press(dialog, tree, label, email=None):
    if email:
        tree.selection_set(email)
    click(dialog, label)


def test_manage_users_lists_the_administrator_first(root, tmp_path,
                                                     monkeypatch):
    open_store, _, _ = set_up_pc(tmp_path)
    store = open_store()
    store.sign_up("Pat", "Q", "Pending", "PP", "pending@example.invalid",
                  USER_PASS, USER_PASS)
    changes = []
    dialog, tree = manage(root, store, changes)
    try:
        listed = rows(tree)
        assert [r[2] for r in listed] == [ADMIN, "pending@example.invalid",
                                          USER]
        assert listed[0][3] == app_auth.role_text(store.find(ADMIN))
        assert listed[1][0] == app_auth.full_name(
            store.find("pending@example.invalid"))
        assert listed[1][1] == "PP"
        assert listed[1][4] == app_auth.STATUS_TEXT["pending"]
        assert changes == [1]           # the program is told once
    finally:
        dialog.destroy()


def test_approve_disable_enable_reject(root, tmp_path, monkeypatch):
    open_store, _, _ = set_up_pc(tmp_path)
    store = open_store()
    store.sign_up("Pat", "", "Pending", "PP", "pending@example.invalid",
                  USER_PASS, USER_PASS)
    boxes = Boxes(monkeypatch)
    dialog, tree = manage(root, store)
    try:
        for label, status in (("Approve", "approved"),
                              ("Disable", "disabled"),
                              ("Enable", "approved"),
                              ("Reject", "rejected")):
            press(dialog, tree, label, "pending@example.invalid")
            assert open_store().find("pending@example.invalid")[
                "status"] == status, label
            assert tree.selection() == ("pending@example.invalid",)
        assert boxes.calls == []
    finally:
        dialog.destroy()


def test_nothing_selected_says_so(root, tmp_path, monkeypatch):
    open_store, _, _ = set_up_pc(tmp_path)
    boxes = Boxes(monkeypatch)
    dialog, tree = manage(root, open_store())
    try:
        tree.selection_set(())
        for label in ("Approve", "Delete", "Reset Password"):
            click(dialog, label)
        assert boxes.calls == [("showinfo", "Select an account first.")] * 3
    finally:
        dialog.destroy()


def test_the_administrator_account_cannot_be_changed_or_deleted(
        root, tmp_path, monkeypatch):
    open_store, _, _ = set_up_pc(tmp_path)
    boxes = Boxes(monkeypatch)
    dialog, tree = manage(root, open_store())
    try:
        press(dialog, tree, "Disable", ADMIN)
        press(dialog, tree, "Delete", ADMIN)
        warnings = [m for kind, m in boxes.calls if kind == "showwarning"]
        assert warnings == ["The Administrator account cannot be changed.",
                            "The Administrator account cannot be deleted."]
        assert open_store().find(ADMIN)["status"] == "approved"
    finally:
        dialog.destroy()


def test_delete_asks_first_and_no_keeps_the_account(root, tmp_path,
                                                    monkeypatch):
    open_store, _, _ = set_up_pc(tmp_path)
    boxes = Boxes(monkeypatch, yes=False)
    dialog, tree = manage(root, open_store())
    try:
        press(dialog, tree, "Delete", USER)
        assert boxes.calls == [("askyesno", f"Delete the account {USER}?")]
        assert open_store().find(USER) is not None
        boxes.yes = True
        press(dialog, tree, "Delete", USER)
        assert open_store().find(USER) is None
        assert [r[2] for r in rows(tree)] == [ADMIN]
    finally:
        dialog.destroy()


def test_reset_password_through_the_prompt(root, tmp_path, monkeypatch):
    open_store, _, _ = set_up_pc(tmp_path)
    boxes = Boxes(monkeypatch)
    seen = []

    def too_short_then_mismatch_then_ok(window):
        seen.append(texts(window))
        fill(window, "short", "short")
        click(window, "OK")
        seen.append(texts(window))
        fill(window, "new-password-1", "new-password-2")
        click(window, "OK")
        seen.append(texts(window))
        fill(window, "new-password-1", "new-password-1")
        click(window, "OK")

    no_waiting(monkeypatch, root, [too_short_then_mismatch_then_ok])
    dialog, tree = manage(root, open_store())
    try:
        press(dialog, tree, "Reset Password", USER)
        assert f"New password for {USER}" in seen[0]
        assert f"At least {app_auth.MIN_PASSWORD} characters." in seen[1]
        assert "The two passwords do not match." in seen[2]
        assert boxes.calls == [("showinfo", "The password was changed. "
                                "Tell the user the new password.")]
        store = open_store()
        assert store.sign_in("TU", "new-password-1")["email"] == USER
    finally:
        dialog.destroy()


def test_reset_password_cancelled_changes_nothing(root, tmp_path,
                                                  monkeypatch):
    open_store, _, _ = set_up_pc(tmp_path)
    boxes = Boxes(monkeypatch)
    no_waiting(monkeypatch, root, [lambda w: click(w, "Cancel")])
    dialog, tree = manage(root, open_store())
    try:
        press(dialog, tree, "Reset Password", USER)
        assert boxes.calls == []
        assert open_store().sign_in("TU", USER_PASS)["email"] == USER
    finally:
        dialog.destroy()


def test_the_owners_password_is_not_reset_here(root, tmp_path, monkeypatch):
    open_store, path, _ = set_up_pc(tmp_path)
    store = open_store()
    # USER stands in for an Owner account (an Owner comes from the seed).
    real_find = store.find
    monkeypatch.setattr(store, "find", lambda email: dict(
        real_find(email), role="owner") if email == USER else real_find(email))
    boxes = Boxes(monkeypatch)

    def ok(window):
        fill(window, "new-password-1", "new-password-1")
        click(window, "OK")
    no_waiting(monkeypatch, root, [ok])
    before = path.read_bytes()
    dialog, tree = manage(root, store)
    try:
        press(dialog, tree, "Reset Password", USER)
        ((kind, message),) = boxes.calls
        assert kind == "showwarning"
        assert message.startswith("The Owner account cannot be changed.")
        assert path.read_bytes() == before
    finally:
        dialog.destroy()


# ---------- Change Password ----------

def change_window(root, store, email):
    before = set(root.winfo_children())
    app_auth.open_change_password(root, store, store.find(email))
    (dialog,) = set(root.winfo_children()) - before
    return dialog


def test_change_password_checks_the_current_one_and_the_match(
        root, tmp_path, monkeypatch):
    open_store, _, _ = set_up_pc(tmp_path)
    monkeypatch.setattr(tkinter.Misc, "grab_set", lambda self: None)
    boxes = Boxes(monkeypatch)
    dialog = change_window(root, open_store(), USER)
    try:
        assert len(entries(dialog)) == 3
        fill(dialog, "not-the-password", "brand-new-pass", "brand-new-pass")
        click(dialog, "Change")
        assert "The current password is not correct." in texts(dialog)
        fill(dialog, USER_PASS, "brand-new-pass", "brand-new-other")
        click(dialog, "Change")
        assert "The two new passwords do not match." in texts(dialog)
        fill(dialog, USER_PASS, "short", "short")
        click(dialog, "Change")
        assert (f"at least {app_auth.MIN_PASSWORD} characters"
                in texts(dialog))
        assert boxes.calls == []
        assert open_store().sign_in("TU", USER_PASS)["email"] == USER

        fill(dialog, USER_PASS, "brand-new-pass", "brand-new-pass")
        click(dialog, "Change")
        assert boxes.calls == [("showinfo", "Your password was changed.")]
        assert not dialog.winfo_exists()
    finally:
        if dialog.winfo_exists():
            dialog.destroy()
    store = open_store()
    assert store.sign_in("TU", "brand-new-pass")["email"] == USER
    with pytest.raises(app_auth.AuthError):
        store.sign_in("TU", USER_PASS)


def test_change_password_cancel_changes_nothing(root, tmp_path, monkeypatch):
    open_store, path, _ = set_up_pc(tmp_path)
    monkeypatch.setattr(tkinter.Misc, "grab_set", lambda self: None)
    before = path.read_bytes()
    dialog = change_window(root, open_store(), ADMIN)
    fill(dialog, ADMIN_PASS, "", "")
    click(dialog, "Cancel")
    assert not dialog.winfo_exists()
    assert path.read_bytes() == before
