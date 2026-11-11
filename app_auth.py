"""
Sign in / sign up for the Field Survey Report.

* Accounts are kept in the application's private JSON data directory
  (passwords are stored as salted PBKDF2 hashes - never as plain text).
  users.json carries a "version"; a file written by a newer program is
  refused with a clear message instead of being misread.
* Every account stores its own PBKDF2 iteration count. Accounts saved
  before that (no "iterations") are checked with the old count and are
  re-hashed with the current one at their next successful sign in.
* The Owner account is created automatically the first time the program
  starts. A new user signs up, then waits until the Owner approves the
  account (Account menu > Manage Users).
* Roles: "owner", "admin" and "user".   Status: pending / approved /
  rejected / disabled.  Only "approved" accounts can sign in.
* Wrong passwords slow the sign in down (a short wait after the 2nd, 3rd
  and 4th) and the 5th locks the account for 15 minutes. The lock ends by
  itself, is never longer than 15 minutes - also for the Owner - and is
  kept in users.json, so restarting the program does not clear it.
* A site PC (User edition) is installed without any account. The first
  account created there becomes the Administrator ("admin") of that PC; a
  record kept outside users.json (fsr_secrets.py) remembers that the PC is
  set up, so deleting users.json does not offer the set-up again.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import tkinter
import math
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

import ttkbootstrap as tb

import fsr_secrets

ITERATIONS = 600_000               # new and changed passwords
LEGACY_ITERATIONS = 200_000        # accounts saved without "iterations"
MAX_ITERATIONS = 10_000_000        # a larger stored count is not believed
FILE_VERSION = 2                   # users.json (1 = files with no "version")

MAX_FAILURES = 5                   # wrong passwords in a row -> locked
RETRY_DELAYS = (0, 2, 5, 10)       # seconds to wait after failure 1, 2, 3, 4
LOCKOUT = timedelta(minutes=15)
CLOCK_TOLERANCE = timedelta(minutes=2)
MAX_UNKNOWN = 500                  # remembered wrong initials (memory only)
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

ADMIN_ROLES = ("owner", "admin")       # may approve and manage accounts
ROLE_TEXT = {"owner": "Owner", "admin": "Administrator", "user": "User"}


def is_admin(user):
    """The Owner, or the Administrator of a site PC."""
    return bool(user) and user.get("role") in ADMIN_ROLES


def role_text(user):
    return ROLE_TEXT.get((user or {}).get("role"), "User")


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

def hash_password(password, salt=None, iterations=LEGACY_ITERATIONS):
    """(salt, hash). Without `iterations` this is the hash of an account
    that stores no count - use new_password_fields() for a new password."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
    ).hex()
    return salt, digest


def new_password_fields(password):
    """The three fields of an account for a new or changed password."""
    salt, digest = hash_password(password, None, ITERATIONS)
    return {"salt": salt, "hash": digest, "iterations": ITERATIONS}


def user_iterations(user):
    """The count this account's hash was made with (0 = not usable)."""
    value = user.get("iterations")
    if value is None:
        return LEGACY_ITERATIONS
    if isinstance(value, int) and not isinstance(value, bool) \
            and 0 < value <= MAX_ITERATIONS:
        return value
    return 0


def password_matches(password, salt, digest, iterations=LEGACY_ITERATIONS):
    if not iterations:
        return False
    try:
        _, test = hash_password(password, salt, iterations)
    except ValueError:
        return False
    return hmac.compare_digest(test, digest or "")


def user_password_matches(user, password):
    return password_matches(password, user.get("salt", ""),
                            user.get("hash", ""), user_iterations(user))


# ---------------------------------------------------------------------
# wrong passwords: wait, then lock
# ---------------------------------------------------------------------
# A record is an account of users.json, or - for initials that have no
# account - a dictionary kept in memory. Two optional fields:
#   failed_count   wrong passwords since the last success or lock
#   blocked_until  no attempt is accepted before this time

def _time_text(moment):
    return moment.isoformat(timespec="seconds")


def _parse_time(text):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _blocked_seconds(record, now):
    """(seconds still to wait, record was corrected). A block further away
    than a full lockout cannot be real (changed clock, edited file): it is
    cut down, so nobody is ever kept out for more than 15 minutes."""
    until = _parse_time(record.get("blocked_until"))
    if until is None:
        changed = "blocked_until" in record
        record.pop("blocked_until", None)
        return 0, changed
    if until <= now:
        del record["blocked_until"]
        return 0, True
    changed = until - now > LOCKOUT
    if changed:
        until = now + LOCKOUT
        record["blocked_until"] = _time_text(until)
    return math.ceil((until - now).total_seconds()), changed


def _note_failure(record, now):
    """Count one wrong password. True when the account is now locked."""
    count = record.get("failed_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        count = 0
    count += 1
    if count >= MAX_FAILURES:
        record["failed_count"] = 0
        record["blocked_until"] = _time_text(now + LOCKOUT)
        return True
    record["failed_count"] = count
    delay = RETRY_DELAYS[min(count, len(RETRY_DELAYS)) - 1]
    if delay:
        record["blocked_until"] = _time_text(now + timedelta(seconds=delay))
    return False


def _clear_failures(record):
    had = "failed_count" in record or "blocked_until" in record
    record.pop("failed_count", None)
    record.pop("blocked_until", None)
    return had


def _wait_text(seconds):
    if seconds > 60:
        minutes = math.ceil(seconds / 60)
        return ("Too many wrong passwords. This account is locked for "
                f"{minutes} more minute{'s' if minutes != 1 else ''}.")
    return (f"Please wait {seconds} second{'s' if seconds != 1 else ''} "
            "before trying again.")


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
    def __init__(self, path, secrets=None, use_seed=True, clock=None):
        self.path = Path(path)
        self._now = clock or datetime.now
        self._time_seen = None          # newest time written to the file
        self._unknown = {}              # failures of initials with no account
        self.secrets = (secrets if secrets is not None
                        else fsr_secrets.default_store(self.path.parent))
        self._secret_name = "accounts-" + hashlib.sha256(
            str(self.path.resolve()).casefold().encode("utf-8")
        ).hexdigest()[:16]
        if not self.path.exists() and self._setup_record() is not None:
            raise UserDataError(
                f"The account file is missing: {self.path}\n"
                "This PC was already set up, so the program will not offer "
                "the first set-up again. Restore users.json from a backup "
                "before signing in.")
        if use_seed:
            self.ensure_owner()
            self.ensure_built_in_users()
        if self._has_administrator(self._read()):
            self._mark_set_up()

    # -- "this PC is set up" (kept outside users.json) --
    def _setup_record(self):
        text = self.secrets.get(self._secret_name)
        if text is None:
            return None
        try:
            record = json.loads(text)
        except ValueError:
            record = None
        return record if isinstance(record, dict) else {}

    def _mark_set_up(self):
        if self._setup_record() is None:
            self.secrets.set(self._secret_name, json.dumps({"setup": True}))

    @staticmethod
    def _has_administrator(users):
        return any(is_admin(u) and u.get("status") == "approved"
                   for u in users)

    @property
    def needs_setup(self):
        """True on a PC that has no Administrator yet: the next account is
        created with create_administrator()."""
        return not self._has_administrator(self._read())

    # -- file --
    def _read(self):
        return self._load()["users"]

    def _load(self):
        """The whole file: {"version", "users", ...}."""
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return {"version": FILE_VERSION, "users": []}
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
        version = data.get("version", 1)
        if not isinstance(version, int) or isinstance(version, bool) \
                or version < 1:
            raise UserDataError(
                f"The account file has an invalid version: {self.path}\n"
                "It has not been changed. Restore it from a backup before "
                "signing in.")
        if version > FILE_VERSION:
            raise UserDataError(
                f"The account file was written by a newer version of this "
                f"program (file version {version}, this program reads up "
                f"to {FILE_VERSION}):\n{self.path}\n"
                "It has not been changed. Install the newer program on "
                "this PC.")
        if isinstance(data.get("time_seen"), str):
            self._time_seen = data["time_seen"]
        return data

    def _write(self, users, now=None):
        if now is not None:
            self._time_seen = _time_text(now)
        document = {"version": FILE_VERSION}
        if self._time_seen:
            document["time_seen"] = self._time_seen
        document["users"] = users
        text = json.dumps(document, indent=2, ensure_ascii=False)
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
            **({"iterations": OWNER["iterations"]}
               if "iterations" in OWNER else {}),
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
        self._add_account(first, middle, last, initials, email, password,
                          confirm, role="user", status="pending")

    def create_administrator(self, first, middle, last, initials, email,
                             password, confirm):
        """The one-time set-up of a PC without an Administrator."""
        if not self.needs_setup:
            raise AuthError(
                "This PC already has an Administrator. Create a normal "
                "account and ask the Administrator to approve it.")
        self._add_account(first, middle, last, initials, email, password,
                          confirm, role="admin", status="approved")
        self._mark_set_up()

    def _add_account(self, first, middle, last, initials, email, password,
                     confirm, role, status):
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

        users = self._read()
        users.append({
            "first_name": first, "middle_name": middle, "last_name": last,
            "initials": initials, "email": email,
            **new_password_fields(password), "role": role, "status": status,
            "created": datetime.now().strftime("%d-%b-%Y %H:%M"),
        })
        self._write(users)

    def sign_in(self, initials, password):
        now = self._now()
        document = self._load()
        users = document["users"]
        changed = self._clock_went_back(document, now)
        key = (initials or "").strip().upper()
        user = next((u for u in users if key and
                     u.get("initials", "").strip().upper() == key), None)
        if user is None:
            if len(self._unknown) >= MAX_UNKNOWN:
                self._unknown.clear()
            record = self._unknown.setdefault(key, {})
        else:
            record = user

        wait, corrected = _blocked_seconds(record, now)
        if wait:
            # Saved even when nothing else changed: the time seen is what
            # keeps a lock running if the PC clock is set back afterwards.
            if changed or user is not None:
                self._write_quietly(users, now)
            raise AuthError(_wait_text(wait))

        if user is None or not user_password_matches(user, password):
            locked = _note_failure(record, now)
            if user is not None or changed:
                self._write_quietly(users, now)
            raise AuthError(
                "Incorrect initials or password." + (
                    "\nToo many wrong passwords: this account is now "
                    "locked for 15 minutes." if locked else ""))

        # The password is right: the count starts again.
        _clear_failures(record)
        status = user.get("status")
        problem = None
        if status == "pending":
            problem = ("Your account is waiting for the Owner's approval.\n"
                       "Please try again after it is approved.")
        elif status == "rejected":
            problem = "Your sign up request was not approved."
        elif status != "approved":
            problem = ("This account is disabled. Please contact the "
                       "Administrator.")
        elif user_iterations(user) < ITERATIONS:
            # proven correct just now: re-hash with the current count
            user.update(new_password_fields(password))
        # Also records the time seen. A file that cannot be written does
        # not stop the sign in; the same is done again next time.
        self._write_quietly(users, now)
        if problem:
            raise AuthError(problem)
        return dict(user)

    def _write_quietly(self, users, now):
        try:
            self._write(users, now)
        except OSError:
            pass

    def _clock_went_back(self, document, now):
        """The PC clock is earlier than a time this file has seen: a block
        keeps the time it had left (never more than a full lockout), so
        setting the clock back neither removes nor stretches it."""
        seen = _parse_time(document.get("time_seen"))
        if seen is None or now >= seen - CLOCK_TOLERANCE:
            return False
        for record in [*document["users"], *self._unknown.values()]:
            until = _parse_time(record.get("blocked_until"))
            if until is not None:
                left = min(max(until - seen, timedelta(0)), LOCKOUT)
                record["blocked_until"] = _time_text(now + left)
        return True

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
        if is_admin(user):
            raise AuthError(
                f"The {role_text(user)} account cannot be changed.")
        self._change(email, lambda u: u.__setitem__("status", status))

    def delete(self, email):
        user = self.find(email)
        if user is None:
            raise AuthError("That account was not found.")
        if is_admin(user):
            raise AuthError(
                f"The {role_text(user)} account cannot be deleted.")
        users = [u for u in self._read()
                 if u.get("email", "").lower() != email.lower()]
        self._write(users)

    def set_password(self, email, password):
        if len(password) < MIN_PASSWORD:
            raise AuthError(
                f"The password needs at least {MIN_PASSWORD} characters.")
        fields = new_password_fields(password)

        def apply(user):
            user.update(fields)
            _clear_failures(user)       # a new password also ends a lock

        self._change(email, apply)

    def change_own_password(self, email, old, new, confirm):
        user = self.find(email)
        if user is None or not user_password_matches(user, old):
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

    # ---- the boxes of a new account (sign up and first set-up) ----
    def account_form():
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

        boxes["email"] = field("Email")
        boxes["password"] = field("Password", show="*")
        boxes["confirm"] = field("Confirm Password", show="*")
        show_password_toggle(boxes["password"], boxes["confirm"])
        return boxes

    def form_values(boxes):
        return [boxes[key].get() for key in (
            "first", "middle", "last", "initials", "email", "password",
            "confirm")]

    # ---- sign up ----
    def sign_up_page():
        clear()
        fit(800)
        heading("Create Account",
                "An Administrator must approve your account before you can "
                "sign in.\nYou will sign in with your Initials.")
        boxes = account_form()

        def submit(event=None):
            try:
                store.sign_up(*form_values(boxes))
            except AuthError as error:
                show_message(str(error))
                return
            sign_in_page(
                "Account created. You can sign in after an Administrator "
                "approves it.")

        tb.Button(content, text="Send for Approval", bootstyle="info",
                  command=submit).pack(fill="x", pady=(14, 6))
        tb.Button(content, text="Back to Sign In", bootstyle="link",
                  command=lambda: sign_in_page()).pack(anchor="w")
        message_label()
        dialog.bind("<Return>", submit)
        boxes["first"].focus_set()

    # ---- first set-up of a PC that has no Administrator ----
    def setup_page():
        clear()
        fit(860)
        heading("Set Up This PC",
                "This PC has no Administrator account yet.\n"
                "The account you create now becomes the ADMINISTRATOR of "
                "this PC: it approves the other accounts and can reset "
                "their passwords.\nThis screen is shown only once.")
        boxes = account_form()

        def submit(event=None):
            if not messagebox.askyesno(
                    "Set Up This PC",
                    "Create the Administrator account of this PC now?\n\n"
                    "Keep its password safe: it is the only account that "
                    "can approve the others.", parent=dialog):
                return
            try:
                store.create_administrator(*form_values(boxes))
            except AuthError as error:
                show_message(str(error))
                return
            sign_in_page(
                "The Administrator account was created. Sign in with its "
                "Initials.")

        tb.Button(content, text="Create Administrator Account",
                  bootstyle="info", command=submit).pack(
            fill="x", pady=(14, 6))
        message_label()
        dialog.bind("<Return>", submit)
        boxes["first"].focus_set()

    if store.needs_setup:
        setup_page()
    else:
        sign_in_page()
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    dialog.lift()
    dialog.focus_force()
    dialog.wait_window()
    return result["user"]


def open_manage_users(parent, store, owner, on_change=None):
    """Owner / Administrator only: approve, reject, disable, delete."""
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
            0 if is_admin(u) else 1,
            order.get(u.get("status"), 9), u.get("last_name", "")))
        for user in users:
            tree.insert("", "end", iid=user["email"], values=(
                full_name(user), user.get("initials", ""), user["email"],
                role_text(user),
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


# ---------------------------------------------------------------------
# python app_auth.py make-seed
# ---------------------------------------------------------------------

SEED_FILE = (Path(__file__).resolve().parent / "data" / "json" / "private"
             / "auth_seed.json")


def make_seed(password, owner=None, path=SEED_FILE):
    """Write auth_seed.json: the owner's names and the HASH of `password`
    (the Owner installer creates the owner account from it on a new PC).
    Names come from `owner`, else from the seed that is already there."""
    if len(password) < MIN_PASSWORD:
        raise AuthError(
            f"The password needs at least {MIN_PASSWORD} characters.")
    path = Path(path)
    if owner is None:
        try:
            owner = json.loads(path.read_text(encoding="utf-8")).get("owner")
        except (OSError, ValueError, AttributeError):
            owner = None
    if not isinstance(owner, dict):
        raise AuthError(f"No owner was found in {path}.")
    record = {key: str(owner.get(key) or "").strip() for key in (
        "first_name", "middle_name", "last_name", "initials", "email")}
    record["initials"] = record["initials"].upper()
    record["email"] = record["email"].lower()
    if not (record["first_name"] and record["last_name"]
            and record["initials"] and EMAIL_PATTERN.match(record["email"])):
        raise AuthError("The owner needs a first name, last name, initials "
                        "and email.")
    record.update(new_password_fields(password))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps({"owner": record}, indent=2,
                               ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)
    return record


def _main(argv):
    import getpass
    if argv != ["make-seed"]:
        print("Usage:  python app_auth.py make-seed\n"
              "Asks for the owner's new password (it is not shown and is "
              "never written down) and rewrites\n" + str(SEED_FILE))
        return 2
    password = getpass.getpass("New owner password: ")
    if password != getpass.getpass("Type it again:      "):
        print("The two passwords do not match. Nothing was changed.")
        return 1
    try:
        record = make_seed(password)
    except AuthError as error:
        print(f"{error} Nothing was changed.")
        return 1
    print(f"auth_seed.json now holds the new hash for {record['initials']} "
          f"({ITERATIONS:,} iterations). Rebuild the Owner installer.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
