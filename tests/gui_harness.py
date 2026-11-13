"""Start the real Field Survey Report program without a person at the keyboard.

The program builds its whole window when field_survey_report.py runs, so the
GUI tests run that script with:
  * FSR_HOME = a temporary folder (Excel file, settings, Report Forms and
    master lists go there - the real files are never touched; MySQL is off
    because that folder has no db_config.json),
  * the sign-in window replaced by a fixed test user,
  * message boxes answered automatically (and recorded),
  * mainloop() returning at once, so the test can drive the window.
"""

import os
import runpy
import sys
import tkinter
from pathlib import Path
from tkinter import messagebox

ROOT = Path(__file__).resolve().parent.parent
TEST_USER = {"initials": "TST", "first_name": "Test", "last_name": "User",
             "email": "test.user@example.invalid", "role": "owner",
             "status": "approved"}


class AutoAnswers:
    """Replaces the messagebox functions; every call is recorded."""

    def __init__(self, yes=True):
        self.calls = []
        self.yes = yes
        self._saved = {}

    def install(self):
        for name in ("showinfo", "showwarning", "showerror"):
            self._saved[name] = getattr(messagebox, name)
            setattr(messagebox, name, self._show(name))
        for name in ("askyesno", "askokcancel", "askyesnocancel",
                     "askquestion"):
            self._saved[name] = getattr(messagebox, name)
            setattr(messagebox, name, self._ask(name))

    def uninstall(self):
        for name, func in self._saved.items():
            setattr(messagebox, name, func)

    def _show(self, name):
        def show(title=None, message=None, **_):
            self.calls.append((name, title, message))
            return "ok"
        return show

    def _ask(self, name):
        def ask(title=None, message=None, **_):
            self.calls.append((name, title, message))
            if name == "askquestion":
                return "yes" if self.yes else "no"
            return self.yes
        return ask

    def titles(self, kind=None):
        return [t for n, t, _ in self.calls if kind is None or n == kind]


def start_app(home, extra_env=None):
    """Run field_survey_report.py inside `home`; returns (globals, answers).
    Call stop_app(globals, answers) when done."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    os.environ["FSR_HOME"] = str(home)
    # MySQL rounds run at once on the calling thread, so a test sees their
    # result right after save_report(). The background itself is tested
    # separately (tests/test_mysql_background_gui.py), with this off.
    os.environ["FSR_MYSQL_INLINE"] = "1"
    os.environ.pop("FSR_DEMO", None)
    # The GUI tests of the workbook's own behaviour keep the reports in the
    # workbook; the tests of the reports database pass FSR_NO_SQLITE="0".
    os.environ["FSR_NO_SQLITE"] = "1"
    for key, value in (extra_env or {}).items():
        os.environ[key] = value
    sys.path.insert(0, str(ROOT))

    import app_auth
    saved_login = app_auth.run_login
    app_auth.run_login = lambda *a, **k: dict(TEST_USER)
    saved_mainloop = tkinter.Misc.mainloop
    tkinter.Misc.mainloop = lambda self, n=0: None
    answers = AutoAnswers()
    answers.install()
    try:
        # Loading the module builds nothing (Phase 4); build_window() then
        # sets up the program and its window, as main() does. The tests
        # get the module's own globals (runpy hands back a copy).
        loaded = runpy.run_path(str(ROOT / "field_survey_report.py"),
                                run_name="fsr_under_test")
        app = loaded["build_window"].__globals__
        app["build_window"]()
    finally:
        app_auth.run_login = saved_login
        tkinter.Misc.mainloop = saved_mainloop
    app["window"].update()
    return app, answers


def _stray_root(window):
    """A Tk root other than the program's window that ttkbootstrap's Style
    is still bound to - it would stop every later GUI test module from
    opening its window ("a Style is already bound to an existing live
    root"). Returns a description, or None."""
    try:
        from ttkbootstrap.style import Style
    except ImportError:
        return None
    existing = Style.get_instance()
    other = getattr(existing, "master", None)
    if other is None or other is window:
        return None
    try:
        if not other.winfo_exists():
            return None
        children = [f"{w.winfo_class()} {w.winfo_name()!r}"
                    for w in other.winfo_children()][:10]
        title = other.title() if hasattr(other, "title") else ""
    except tkinter.TclError:
        return None
    return f"{type(other).__name__} titled {title!r} holding {children}"


def stop_app(app, answers):
    try:
        app["window"].destroy()
    except tkinter.TclError:
        pass
    stray = _stray_root(app["window"])
    if stray is not None:
        # Close it so later modules can open their window, and say so: a
        # second root left behind is a fault of the code under test.
        from ttkbootstrap.style import Style
        try:
            Style.get_instance().master.destroy()
        except tkinter.TclError:
            pass
        answers.uninstall()
        os.environ.pop("FSR_HOME", None)
        os.environ.pop("FSR_MYSQL_INLINE", None)
        raise AssertionError(
            "A second Tk root window was left alive after the program's "
            f"window was closed: {stray}")
    answers.uninstall()
    os.environ.pop("FSR_HOME", None)
    os.environ.pop("FSR_MYSQL_INLINE", None)
    os.environ.pop("FSR_NO_SQLITE", None)
    import fsr_sqlite_store
    fsr_sqlite_store.listeners.clear()      # nothing of this window is left
    # The program put the test user's initials into new Control #s; tests
    # that run after this one start without initials again.
    import fsr_storage
    fsr_storage.set_control_initials("")
