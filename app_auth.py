"""
Sign in / sign up for the Field Survey Report.

* Accounts are kept in the application's private JSON data directory
  (passwords are stored as salted PBKDF2 hashes - never as plain text).
* The Owner account is created automatically the first time the program
  starts. A new user signs up, then waits until the Owner approves the
  account (Account menu > Manage Users).
* Roles: "owner" and "user".   Status: pending / approved / rejected /
  disabled.  Only "approved" accounts can sign in.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import tkinter
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import ttkbootstrap as tb

ITERATIONS = 200_000
MIN_PASSWORD = 12
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Accounts created on first start come from data/json/private/auth_seed.json
# (not in source control; only password HASHES are kept there). Without the
# file no account is created here; the owner creates and approves accounts
# from Manage Users.
def _load_seed():
    path = (Path(__file__).resolve().parent / "data" / "json" / "private"
            / "auth_seed.json")
    try:
        with open(path, "r", encoding="utf-8") as file:
            seed = json.load(file)
    except (OSError, ValueError):
        return {}, []
    return seed.get("owner") or {}, seed.get("built_in_users") or []


OWNER, BUILT_IN_USERS = _load_seed()

STATUS_TEXT = {
    "pending": "Waiting for approval",
    "approved": "Approved",
    "rejected": "Rejected",
    "disabled": "Disabled",
}


class AuthError(Exception):
    """A problem that can be shown to the user as it is."""


class UserDataError(AuthError):
    """The account file could not be safely read."""


# ---------------------------------------------------------------------
# passwords + names
# ---------------------------------------------------------------------

def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS
    ).hex()
    return salt, digest


def password_matches(password, salt, digest):
    try:
        _, test = hash_password(password, salt)
    except ValueError:
        return False
    return hmac.compare_digest(test, digest or "")


def full_name(user):
    """'Mierxan P. Rojo' - the name printed on the forms."""
    middle = (user.get("middle_name") or "").strip()
    middle = (middle[0].upper() + ".") if middle else ""
    parts = [user.get("first_name", "").strip(), middle,
             user.get("last_name", "").strip()]
    return " ".join(part for part in parts if part)


def suggest_initials(first, middle, last):
    return "".join(
        part.strip()[0].upper() for part in (first, middle, last)
        if part and part.strip()
    )


# ---------------------------------------------------------------------
# the user file
# ---------------------------------------------------------------------

class UserStore:
    def __init__(self, path):
        self.path = Path(path)
        self.ensure_owner()
        self.ensure_built_in_users()

    # -- file --
    def _read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise UserDataError(
                f"The account file could not be read: {self.path}\n"
                "It has not been changed. Restore it from a backup before "
                "signing in."
            ) from error
        if (not isinstance(data, dict)
                or not isinstance(data.get("users"), list)
                or any(not isinstance(user, dict)
                       for user in data["users"])):
            raise UserDataError(
                f"The account file has an invalid format: {self.path}\n"
                "It has not been changed. Restore it from a backup before "
                "signing in."
            )
        return data["users"]

    def _write(self, users):
        text = json.dumps({"users": users}, indent=2, ensure_ascii=False)
        fd, temp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix="users_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(text)
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.remove(temp)

    # -- owner --
    def ensure_owner(self):
        users = self._read()
        if not OWNER or any(user.get("role") == "owner" for user in users):
            return
        users = [u for u in users
                 if u.get("email", "").lower() != OWNER["email"]]
        users.insert(0, {
            "first_name": OWNER["first_name"],
            "middle_name": OWNER["middle_name"],
            "last_name": OWNER["last_name"],
            "initials": OWNER["initials"],
            "email": OWNER["email"],
            "salt": OWNER["salt"],
            "hash": OWNER["hash"],
            "role": "owner",
            "status": "approved",
            "created": datetime.now().strftime("%d-%b-%Y %H:%M"),
        })
        self._write(users)

    def ensure_built_in_users(self):
        users = self._read()
        emails = {u.get("email", "").lower() for u in users}
        initials = {u.get("initials", "").strip().upper() for u in users}
        added = False
        for built_in in BUILT_IN_USERS:
            if (built_in["email"].lower() in emails
                    or built_in["initials"].upper() in initials):
                continue
            users.append(dict(
                built_in, role="user", status="approved",
                created=datetime.now().strftime("%d-%b-%Y %H:%M")))
            added = True
        if added:
            self._write(users)

    # -- lookups --
    def list_users(self):
        return self._read()

    def find(self, email):
        email = (email or "").strip().lower()
        for user in self._read():
            if user.get("email", "").lower() == email:
                return user
        return None

    def find_by_initials(self, initials):
        initials = (initials or "").strip().upper()
        if not initials:
            return None
        for user in self._read():
            if user.get("initials", "").strip().upper() == initials:
                return user
        return None

    def pending_count(self):
        return sum(1 for u in self._read() if u.get("status") == "pending")

    # -- sign up / sign in --
    def sign_up(self, first, middle, last, initials, email, password,
                confirm):
        first, middle, last = first.strip(), middle.strip(), last.strip()
        email = email.strip().lower()
        initials = (initials.strip().upper()
                    or suggest_initials(first, middle, last))

        if not first or not last:
            raise AuthError("Please enter your First Name and Last Name.")
        if not EMAIL_PATTERN.match(email):
            raise AuthError("Please enter a valid email address.")
        if len(password) < MIN_PASSWORD:
            raise AuthError(
                f"The password needs at least {MIN_PASSWORD} characters.")
        if password != confirm:
            raise AuthError("The two passwords do not match.")
        if not re.fullmatch(r"[A-Z0-9]{2,6}", initials):
            raise AuthError("The Initials need 2 to 6 letters or numbers.")
        if self.find_by_initials(initials):
            raise AuthError(
                f"The initials {initials} are already used by another "
                "account. Please type different initials.")
        if self.find(email):
            raise AuthError("This email already has an account.")

        salt, digest = hash_password(password)
        users = self._read()
        users.append({
            "first_name": first, "middle_name": middle, "last_name": last,
            "initials": initials, "email": email, "salt": salt,
            "hash": digest, "role": "user", "status": "pending",
            "created": datetime.now().strftime("%d-%b-%Y %H:%M"),
        })
        self._write(users)

    def sign_in(self, initials, password):
        user = self.find_by_initials(initials)
        if user is None or not password_matches(
                password, user.get("salt", ""), user.get("hash", "")):
            raise AuthError("Incorrect initials or password.")
        status = user.get("status")
        if status == "pending":
            raise AuthError(
                "Your account is waiting for the Owner's approval.\n"
                "Please try again after it is approved.")
        if status == "rejected":
            raise AuthError("Your sign up request was not approved.")
        if status != "approved":
            raise AuthError("This account is disabled. Please contact "
                            "the Owner.")
        return user

    # -- owner actions --
    def _change(self, email, func):
        users = self._read()
        for user in users:
            if user.get("email", "").lower() == email.lower():
                func(user)
                self._write(users)
                return
        raise AuthError("That account was not found.")

    def set_status(self, email, status):
        user = self.find(email)
        if user and user.get("role") == "owner":
            raise AuthError("The Owner account cannot be changed.")
        self._change(email, lambda u: u.__setitem__("status", status))

    def delete(self, email):
        user = self.find(email)
        if user is None:
            raise AuthError("That account was not found.")
        if user.get("role") == "owner":
            raise AuthError("The Owner account cannot be deleted.")
        users = [u for u in self._read()
                 if u.get("email", "").lower() != email.lower()]
        self._write(users)

    def set_password(self, email, password):
        if len(password) < MIN_PASSWORD:
            raise AuthError(
                f"The password needs at least {MIN_PASSWORD} characters.")
        salt, digest = hash_password(password)

        def apply(user):
            user["salt"], user["hash"] = salt, digest

        self._change(email, apply)

    def change_own_password(self, email, old, new, confirm):
        user = self.find(email)
        if user is None or not password_matches(
                old, user.get("salt", ""), user.get("hash", "")):
            raise AuthError("The current password is not correct.")
        if new != confirm:
            raise AuthError("The two new passwords do not match.")
        self.set_password(email, new)


# ---------------------------------------------------------------------
# windows
# ---------------------------------------------------------------------

def _center(win, width, height):
    win.update_idletasks()
    x = max((win.winfo_screenwidth() - width) // 2, 0)
    y = max((win.winfo_screenheight() - height) // 3, 0)
    win.geometry(f"{width}x{height}+{x}+{y}")


def run_login(parent, store, icon=None, last_initials="", on_icon=None):
    """Show the Sign In / Sign Up window and wait.
    Returns the signed-in user (dict) or None when it was closed."""
    result = {"user": None}
    dialog = tb.Toplevel(parent)
    dialog.title("Field Survey Report - Sign In")
    dialog.resizable(False, False)
    if on_icon:
        on_icon(dialog)
    _center(dialog, 460, 540)

    def fit(height):
        """Make the window tall enough for the page being shown."""
        height = min(height, dialog.winfo_screenheight() - 90)
        _center(dialog, 460, height)

    content = tb.Frame(dialog, padding=(36, 28))
    content.pack(fill="both", expand=True)

    def clear():
        for child in content.winfo_children():
            child.destroy()

    def heading(title, subtitle):
        tb.Label(content, text=" FSR ", font=("Segoe UI", 16, "bold"),
                 bootstyle="inverse-info", padding=(8, 2)).pack(anchor="w")
        tb.Label(content, text=title, font=("Segoe UI", 18, "bold")).pack(
            anchor="w", pady=(14, 0))
        tb.Label(content, text=subtitle, bootstyle="secondary",
                 wraplength=380, justify="left").pack(
            anchor="w", pady=(2, 10))

    def field(label, show=None, value=""):
        tb.Label(content, text=label).pack(anchor="w", pady=(6, 0))
        entry = tb.Entry(content, show=show or "")
        entry.pack(fill="x", pady=(2, 0))
        if value:
            entry.insert(0, value)
        return entry

    message = {"label": None}

    def show_message(text, style="danger"):
        if message["label"] is not None:
            message["label"].configure(text=text, bootstyle=style)

    def message_label():
        label = tb.Label(content, text="", bootstyle="danger",
                         wraplength=380, justify="left")
        label.pack(anchor="w", pady=(10, 0))
        message["label"] = label

    def show_password_toggle(*entries):
        var = tkinter.BooleanVar(value=False)

        def toggle():
            for entry in entries:
                entry.configure(show="" if var.get() else "*")

        tb.Checkbutton(content, text="Show password", variable=var,
                       command=toggle).pack(anchor="w", pady=(8, 0))

    # ---- sign in ----
    def sign_in_page(notice=""):
        clear()
        fit(540)
        heading("Sign In", "Field Survey Report")
        initials = field("Initials", value=last_initials)
        password = field("Password", show="*")
        show_password_toggle(password)

        def upper_initials(event=None):
            text = initials.get()
            if text != text.upper():
                position = initials.index("insert")
                initials.delete(0, "end")
                initials.insert(0, text.upper())
                initials.icursor(position)

        initials.bind("<KeyRelease>", upper_initials, add="+")

        def submit(event=None):
            try:
                user = store.sign_in(initials.get(), password.get())
            except AuthError as error:
                show_message(str(error))
                password.delete(0, "end")
                password.focus_set()
                return
            result["user"] = user
            dialog.destroy()

        tb.Button(content, text="Sign In", bootstyle="info",
                  command=submit).pack(fill="x", pady=(16, 6))
        tb.Button(content, text="Create an account", bootstyle="link",
                  command=sign_up_page).pack(anchor="w")
        message_label()
        if notice:
            show_message(notice, "success")
        dialog.bind("<Return>", submit)
        (password if last_initials else initials).focus_set()

    # ---- sign up ----
    def sign_up_page():
        clear()
        fit(800)
        heading("Create Account",
                "The Owner must approve your account before you can sign in.\n"
                "You will sign in with your Initials.")
        row = tb.Frame(content)
        row.pack(fill="x")
        row.columnconfigure((0, 1), weight=1, uniform="n")
        boxes = {}
        for col, (key, label) in enumerate(
                (("first", "First Name"), ("middle", "Middle Name"))):
            box = tb.Frame(row)
            box.grid(row=0, column=col, sticky="we",
                     padx=(0, 6) if col == 0 else (6, 0))
            tb.Label(box, text=label).pack(anchor="w", pady=(6, 0))
            entry = tb.Entry(box)
            entry.pack(fill="x", pady=(2, 0))
            boxes[key] = entry
        row2 = tb.Frame(content)
        row2.pack(fill="x")
        row2.columnconfigure(0, weight=3, uniform="m")
        row2.columnconfigure(1, weight=1, uniform="m")
        for col, (key, label) in enumerate(
                (("last", "Last Name"), ("initials", "Initials"))):
            box = tb.Frame(row2)
            box.grid(row=0, column=col, sticky="we",
                     padx=(0, 6) if col == 0 else (6, 0))
            tb.Label(box, text=label).pack(anchor="w", pady=(6, 0))
            entry = tb.Entry(box)
            entry.pack(fill="x", pady=(2, 0))
            boxes[key] = entry

        def auto_initials(event=None):
            if not boxes["initials"].get().strip() or \
                    getattr(boxes["initials"], "auto", True):
                boxes["initials"].delete(0, "end")
                boxes["initials"].insert(0, suggest_initials(
                    boxes["first"].get(), boxes["middle"].get(),
                    boxes["last"].get()))
                boxes["initials"].auto = True

        def typed_initials(event=None):
            boxes["initials"].auto = False

        for key in ("first", "middle", "last"):
            boxes[key].bind("<KeyRelease>", auto_initials, add="+")
        boxes["initials"].bind("<Key>", typed_initials, add="+")

        email = field("Email")
        password = field("Password", show="*")
        confirm = field("Confirm Password", show="*")
        show_password_toggle(password, confirm)

        def submit(event=None):
            try:
                store.sign_up(
                    boxes["first"].get(), boxes["middle"].get(),
                    boxes["last"].get(), boxes["initials"].get(),
                    email.get(), password.get(), confirm.get())
            except AuthError as error:
                show_message(str(error))
                return
            sign_in_page(
                "Account created. You can sign in after the Owner "
                "approves it.")

        tb.Button(content, text="Send for Approval", bootstyle="info",
                  command=submit).pack(fill="x", pady=(14, 6))
        tb.Button(content, text="Back to Sign In", bootstyle="link",
                  command=lambda: sign_in_page()).pack(anchor="w")
        message_label()
        dialog.bind("<Return>", submit)
        boxes["first"].focus_set()

    sign_in_page()
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    dialog.lift()
    dialog.focus_force()
    dialog.wait_window()
    return result["user"]


def open_manage_users(parent, store, owner, on_change=None):
    """Owner only: approve / reject / disable / delete accounts."""
    dialog = tb.Toplevel(parent)
    dialog.title("Manage Users")
    dialog.transient(parent)
    _center(dialog, 860, 460)

    tb.Label(
        dialog, text="Approve or reject sign up requests and manage "
                     "who can use the program.",
        bootstyle="secondary"
    ).pack(anchor="w", padx=16, pady=(14, 6))

    columns = ("name", "initials", "email", "role", "status", "created")
    headings = ("Name", "Initials", "Email", "Role", "Status", "Created")
    widths = (190, 70, 220, 70, 150, 130)
    holder = tb.Frame(dialog)
    holder.pack(fill="both", expand=True, padx=16, pady=4)
    tree = ttk.Treeview(holder, columns=columns, show="headings",
                        selectmode="browse")
    for column, heading, width in zip(columns, headings, widths):
        tree.heading(column, text=heading)
        tree.column(column, width=width, anchor="w")
    scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    def refresh(select=None):
        tree.delete(*tree.get_children())
        order = {"pending": 0, "approved": 1, "disabled": 2, "rejected": 3}
        users = sorted(store.list_users(), key=lambda u: (
            0 if u.get("role") == "owner" else 1,
            order.get(u.get("status"), 9), u.get("last_name", "")))
        for user in users:
            tree.insert("", "end", iid=user["email"], values=(
                full_name(user), user.get("initials", ""), user["email"],
                user.get("role", "user").title(),
                STATUS_TEXT.get(user.get("status"), user.get("status")),
                user.get("created", "")))
        if select and tree.exists(select):
            tree.selection_set(select)
        if on_change:
            on_change()

    def selected():
        picked = tree.selection()
        if not picked:
            messagebox.showinfo("Manage Users", "Select an account first.",
                                parent=dialog)
            return None
        return picked[0]

    def act(func, *args, confirm=None):
        email = selected()
        if email is None:
            return
        if confirm and not messagebox.askyesno(
                "Manage Users", confirm.format(email), parent=dialog):
            return
        try:
            func(email, *args)
        except AuthError as error:
            messagebox.showwarning("Manage Users", str(error), parent=dialog)
        refresh(email)

    def reset_password():
        email = selected()
        if email is None:
            return
        new = _ask_password(dialog, f"New password for {email}")
        if new is None:
            return
        try:
            store.set_password(email, new)
            messagebox.showinfo(
                "Manage Users",
                "The password was changed. Tell the user the new password.",
                parent=dialog)
        except AuthError as error:
            messagebox.showwarning("Manage Users", str(error), parent=dialog)

    buttons = tb.Frame(dialog)
    buttons.pack(fill="x", padx=16, pady=(8, 14))
    for text, style, command in (
        ("Approve", "success", lambda: act(store.set_status, "approved")),
        ("Reject", "danger-outline",
         lambda: act(store.set_status, "rejected")),
        ("Disable", "secondary-outline",
         lambda: act(store.set_status, "disabled")),
        ("Enable", "secondary-outline",
         lambda: act(store.set_status, "approved")),
        ("Reset Password", "secondary-outline", reset_password),
        ("Delete", "danger-outline",
         lambda: act(store.delete, confirm="Delete the account {0}?")),
    ):
        tb.Button(buttons, text=text, bootstyle=style, command=command,
                  width=14).pack(side="left", padx=(0, 6))
    tb.Button(buttons, text="Close", bootstyle="secondary",
              command=dialog.destroy, width=10).pack(side="right")

    refresh()
    dialog.bind("<Escape>", lambda e: dialog.destroy())


def _ask_password(parent, title):
    """Small window asking for a new password. Returns text or None."""
    result = {"value": None}
    dialog = tb.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.resizable(False, False)
    _center(dialog, 380, 230)
    body = tb.Frame(dialog, padding=20)
    body.pack(fill="both", expand=True)
    tb.Label(body, text=title, font=("Segoe UI", 11, "bold")).pack(anchor="w")
    tb.Label(body, text="New password").pack(anchor="w", pady=(10, 0))
    first = tb.Entry(body, show="*")
    first.pack(fill="x")
    tb.Label(body, text="Confirm").pack(anchor="w", pady=(8, 0))
    second = tb.Entry(body, show="*")
    second.pack(fill="x")
    note = tb.Label(body, text="", bootstyle="danger")
    note.pack(anchor="w", pady=(6, 0))

    def ok(event=None):
        if len(first.get()) < MIN_PASSWORD:
            note.configure(text=f"At least {MIN_PASSWORD} characters.")
        elif first.get() != second.get():
            note.configure(text="The two passwords do not match.")
        else:
            result["value"] = first.get()
            dialog.destroy()

    row = tb.Frame(body)
    row.pack(fill="x", pady=(8, 0))
    tb.Button(row, text="OK", bootstyle="info", command=ok,
              width=10).pack(side="right")
    tb.Button(row, text="Cancel", bootstyle="secondary-outline",
              command=dialog.destroy, width=10).pack(side="right", padx=8)
    dialog.bind("<Return>", ok)
    first.focus_set()
    dialog.grab_set()
    dialog.wait_window()
    return result["value"]


def open_change_password(parent, store, user):
    dialog = tb.Toplevel(parent)
    dialog.title("Change Password")
    dialog.transient(parent)
    dialog.resizable(False, False)
    _center(dialog, 380, 330)
    body = tb.Frame(dialog, padding=20)
    body.pack(fill="both", expand=True)
    entries = []
    for label in ("Current password", "New password", "Confirm new password"):
        tb.Label(body, text=label).pack(anchor="w", pady=(8, 0))
        entry = tb.Entry(body, show="*")
        entry.pack(fill="x")
        entries.append(entry)
    note = tb.Label(body, text="", bootstyle="danger", wraplength=320)
    note.pack(anchor="w", pady=(8, 0))

    def ok(event=None):
        try:
            store.change_own_password(
                user["email"], entries[0].get(), entries[1].get(),
                entries[2].get())
        except AuthError as error:
            note.configure(text=str(error), bootstyle="danger")
            return
        messagebox.showinfo("Change Password", "Your password was changed.",
                            parent=dialog)
        dialog.destroy()

    row = tb.Frame(body)
    row.pack(fill="x", pady=(12, 0))
    tb.Button(row, text="Change", bootstyle="info", command=ok,
              width=10).pack(side="right")
    tb.Button(row, text="Cancel", bootstyle="secondary-outline",
              command=dialog.destroy, width=10).pack(side="right", padx=8)
    dialog.bind("<Return>", ok)
    entries[0].focus_set()
    dialog.grab_set()
