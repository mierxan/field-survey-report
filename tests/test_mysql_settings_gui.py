"""MySQL Settings: saving working settings updates the status at the top
right at once - no restart."""
import time
import tkinter

import pytest

pytestmark = pytest.mark.gui


class FakeMySQL:
    """Stands in for db_mysql. `password_in_server` is what MySQL accepts;
    the saved settings start with an old, wrong password."""

    def __init__(self):
        self.saved = {"enabled": True, "host": "localhost", "port": 3306,
                      "user": "fsr_app", "password": "old-wrong-password",
                      "database": "field_survey"}
        self.password_in_server = "the-new-password"
        self.writes = 0

    def is_enabled(self):
        return bool(self.saved.get("enabled"))

    def read_raw_config(self):
        return dict(self.saved)

    def write_config(self, config):
        self.saved = dict(config)
        self.writes += 1

    def test_connection(self, config=None):
        config = config or self.saved
        if config.get("password") == self.password_in_server:
            return True, "Connected. The database has 10 report(s)."
        return False, "MySQL refused the login for user 'fsr_app'."

    @staticmethod
    def explain_error(error):
        return str(error)


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_mysql_settings_home")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    yield g, answers
    h.stop_app(g, answers)


def live(g):
    return g["save_report"].__globals__


def status(g):
    return str(live(g)["mysql_label"].cget("text"))


def wait_for(g, wanted, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        g["window"].update()
        if status(g) == wanted:
            return True
        time.sleep(0.05)
    return False


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def settings_dialog(g):
    dialogs = [w for w in g["window"].winfo_children()
               if isinstance(w, tkinter.Toplevel)
               and w.title() == "MySQL Settings"]
    assert len(dialogs) == 1
    return dialogs[0]


def press(dialog, label):
    for widget in widgets(dialog):
        if widget.winfo_class() == "TButton" and \
                str(widget.cget("text")) == label:
            widget.invoke()
            return
    raise AssertionError(f"no button {label!r}")


def password_box(dialog):
    return next(w for w in widgets(dialog) if w.winfo_class() == "TEntry"
                and str(w.cget("show")) == "*")


def test_saving_working_settings_updates_the_status_without_a_restart(
        app, monkeypatch):
    g, answers = app
    fake = FakeMySQL()
    monkeypatch.setitem(live(g), "db_mysql", fake)
    monkeypatch.setitem(live(g), "MYSQL_ALLOWED", True)
    restarts = []
    monkeypatch.setitem(live(g), "restart_program",
                        lambda: restarts.append(1))

    # as after changing the password in MySQL: the saved one is refused
    live(g)["check_mysql_status"]()
    assert wait_for(g, "Server inactive")

    answers.calls.clear()
    live(g)["open_mysql_settings"]()
    dialog = settings_dialog(g)
    box = password_box(dialog)
    box.delete(0, "end")
    box.insert(0, "the-new-password")
    press(dialog, "Test Connection")
    assert "Connected. The database has 10 report(s)." in [
        str(w.cget("text")) for w in widgets(dialog)
        if w.winfo_class() == "TLabel"]
    assert status(g) == "Server inactive"       # testing alone saves nothing

    press(dialog, "Save")

    assert fake.writes == 1
    assert fake.saved["password"] == "the-new-password"
    assert not dialog.winfo_exists()
    assert wait_for(g, "Server active"), status(g)   # no restart needed
    assert restarts == []
    assert not [c for c in answers.calls if "restart" in str(c[2]).lower()]
    assert live(g)["mysql_state"]["text"].startswith("Connected.")


def test_saving_settings_that_do_not_work_shows_inactive(app, monkeypatch):
    g, answers = app
    fake = FakeMySQL()
    fake.saved["password"] = fake.password_in_server
    monkeypatch.setitem(live(g), "db_mysql", fake)
    monkeypatch.setitem(live(g), "MYSQL_ALLOWED", True)
    live(g)["check_mysql_status"]()
    assert wait_for(g, "Server active")

    live(g)["open_mysql_settings"]()
    dialog = settings_dialog(g)
    box = password_box(dialog)
    box.delete(0, "end")
    box.insert(0, "a-typo")
    press(dialog, "Save")

    assert wait_for(g, "Server inactive"), status(g)
    assert "refused the login" in live(g)["mysql_state"]["text"]


def test_cancel_changes_nothing(app, monkeypatch):
    g, answers = app
    fake = FakeMySQL()
    monkeypatch.setitem(live(g), "db_mysql", fake)
    monkeypatch.setitem(live(g), "MYSQL_ALLOWED", True)
    live(g)["open_mysql_settings"]()
    dialog = settings_dialog(g)
    password_box(dialog).insert(0, "x")
    press(dialog, "Cancel")
    assert fake.writes == 0 and not dialog.winfo_exists()
