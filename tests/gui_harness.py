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
    os.environ.pop("FSR_DEMO", None)
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
        app = runpy.run_path(str(ROOT / "field_survey_report.py"),
                             run_name="fsr_under_test")
    finally:
        app_auth.run_login = saved_login
        tkinter.Misc.mainloop = saved_mainloop
    app["window"].update()
    return app, answers


def stop_app(app, answers):
    try:
        app["window"].destroy()
    except tkinter.TclError:
        pass
    answers.uninstall()
    os.environ.pop("FSR_HOME", None)
