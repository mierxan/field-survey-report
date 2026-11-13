"""MySQL in the background, in the real program: Save does not wait for
MySQL, the user sees what is still waiting, and what MySQL said comes as
a notice when the background round is done. FakeServer; the sender runs
in its real thread here (the other GUI tests run it inline)."""
import threading
import time
import tkinter
from pathlib import Path

import pytest

import fsr_save_journal
import fsr_storage
from fake_mysql import FakeServer

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_background_home")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    yield g, answers
    h.stop_app(g, answers)


def live(g):
    return g["save_report"].__globals__


def book(g):
    return Path(g["excel_state"]["path"])


class Gate:
    """MySQL answers only when the test lets it."""

    def __init__(self, db):
        self.open = threading.Event()
        self.open.set()
        self.connections = 0
        real = db.connect

        def connect(config=None):
            self.connections += 1
            assert self.open.wait(15), "the test never opened the gate"
            return real(config)
        db.connect = connect


@pytest.fixture
def copy(app, monkeypatch):
    g, answers = app
    server = FakeServer()
    db = server.client()
    gate = Gate(db)
    monkeypatch.setitem(live(g), "db_mysql", db)
    monkeypatch.setitem(live(g), "mysql_numbers", {"values": []})
    sender = live(g)["mysql_sender"]
    monkeypatch.setattr(sender, "inline", False)       # the real thread
    toasts = []
    monkeypatch.setitem(live(g), "notify", lambda message, bootstyle="success":
                        toasts.append((bootstyle, message)))
    journal = fsr_save_journal.Journal(book(g))
    for record in journal.pending():
        journal.remove(record)
    answers.calls.clear()
    yield g, answers, server, gate, toasts
    gate.open.set()
    pump(g, lambda: sender.idle())
    dialog = live(g)["conflict_state"]["dialog"]
    if dialog is not None:
        try:
            dialog.destroy()
        except tkinter.TclError:
            pass
    for record in journal.pending():
        journal.remove(record)


def pump(g, until, limit=20):
    """Let the window run (as its main loop would) until `until()`."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        g["window"].update()
        if until():
            g["window"].update()
            return True
        time.sleep(0.02)
    return False


def quiet(g):
    return pump(g, lambda: live(g)["mysql_sender"].idle())


def fill(g, so):
    g["app_shell"].show("inspection")
    g["new_report"](confirm=False)
    g["choose_condition"]("Good Order")
    g["set_entry"](g["SO_number_entry"], so)
    g["schedule_entries"]["activity"].set("Receiving")
    g["location_combobox"].set("Background Warehouse")
    section = g["item_frames"][0]
    cols = g["ITEM_FORM_HEADERS"]
    for header, value in {"Description of Goods": "Valve", "Quantity": "3",
                          "UOM": "PCS", "Packaging": "Box"}.items():
        g["set_entry"](section.rows[0][cols.index(header)], value)
    return g["control_entry"].get()


def in_mysql(server, control):
    found = server.get(control)
    return found["general_information"]["so_number"] if found else None


def waiting_note(g):
    return str(live(g)["mysql_waiting_label"].cget("text"))


def said(toasts, text):
    return any(text in message for _, message in toasts)


def test_save_does_not_wait_for_mysql(copy):
    g, answers, server, gate, toasts = copy
    control = fill(g, "SO-BACKGROUND")
    gate.open.clear()                       # MySQL takes its time

    started = time.monotonic()
    assert g["save_report"]() is True
    took = time.monotonic() - started

    # saved on this PC; MySQL not yet - and the window is free
    assert fsr_storage.read_report(book(g), control)[
        "general_information"]["so_number"] == "SO-BACKGROUND"
    assert in_mysql(server, control) is None
    assert not live(g)["mysql_sender"].idle()
    assert said(toasts, "Sending it to MySQL")
    assert pump(g, lambda: "MySQL" in waiting_note(g), 5)
    assert "1" in waiting_note(g)
    assert took < 10                        # did not wait for the gate

    gate.open.set()
    assert quiet(g)
    assert in_mysql(server, control) == "SO-BACKGROUND"
    assert said(toasts, f"Report {control} is now in MySQL")
    assert waiting_note(g) == ""
    assert fsr_save_journal.Journal(book(g)).pending() == []
    assert [c for c in answers.calls if c[0] == "showerror"] == []


def test_one_connection_per_save(copy):
    g, answers, server, gate, toasts = copy
    fill(g, "SO-ONE-CONNECTION")
    gate.connections = 0
    assert g["save_report"]() is True
    assert quiet(g)
    assert gate.connections == 1            # it was 2 to 3 before Phase 3


def test_mysql_stopped_the_report_waits_and_the_user_is_told(copy):
    g, answers, server, gate, toasts = copy
    server.down = True
    control = fill(g, "SO-WAITS")
    assert g["save_report"]() is True
    assert quiet(g)
    assert said(toasts, "MySQL was not reached")
    assert "1 waiting for MySQL" in waiting_note(g)
    assert [c for c in answers.calls if c[0] == "showerror"] == []

    server.down = False
    toasts.clear()
    g["finish_unfinished_saves"](mysql_ok=True)     # the server is back
    assert quiet(g)
    assert in_mysql(server, control) == "SO-WAITS"
    assert said(toasts, "MySQL caught up: 1 report(s)")
    assert waiting_note(g) == ""


def test_conflict_found_in_the_background_is_shown(copy):
    g, answers, server, gate, toasts = copy
    control = fill(g, "SO-MINE")
    assert g["save_report"]() is True
    assert quiet(g)
    changed = server.get(control)
    changed["general_information"]["so_number"] = "CHANGED ELSEWHERE"
    server.put(changed)
    answers.calls.clear()

    g["set_entry"](g["SO_number_entry"], "SO-MINE, EDITED")
    assert g["save_report"]() is True
    assert quiet(g)

    assert in_mysql(server, control) == "CHANGED ELSEWHERE"   # untouched
    (box,) = [c for c in answers.calls if c[1] == "MySQL - Not Updated"]
    assert "This copy of the program sent report" in box[2]
    dialog = live(g)["conflict_state"]["dialog"]
    assert dialog is not None and dialog.winfo_exists()
    assert len(fsr_save_journal.conflicts(
        fsr_save_journal.Journal(book(g)))) == 1


def test_number_used_meanwhile_is_handed_on(copy):
    """Another copy used the number after MySQL was last seen. Save no
    longer asks MySQL first; the background finds it and the report takes
    the next free number - here and in MySQL - as Save did before."""
    from datetime import date

    from factories import report
    g, answers, server, gate, toasts = copy
    shown = fill(g, "SO-RACE")
    server.put(report(shown, "Receiving", date(2026, 11, 1), "Elsewhere",
                      [{"qty": 9, "unit": "Box", "desc": "Other goods"}],
                      so="THE OTHER COPY'S"))

    assert g["save_report"]() is True
    assert quiet(g)

    now = g["control_entry"].get()
    assert now != shown
    assert in_mysql(server, shown) == "THE OTHER COPY'S"
    assert in_mysql(server, now) == "SO-RACE"
    assert fsr_storage.read_report(book(g), now)[
        "general_information"]["so_number"] == "SO-RACE"
    assert said(toasts, f"{shown} was already used in MySQL")
    assert fsr_save_journal.Journal(book(g)).pending() == []


def test_import_writes_once_shows_progress_and_sends_in_the_background(
        copy, tmp_path):
    import json
    from datetime import date

    from openpyxl.workbook import workbook

    import fsr_import
    from factories import report
    g, answers, server, gate, toasts = copy
    reports = []
    for number in range(1, 31):
        data = report(f"FSR-JDC-209912-{number:04d}", "Withdrawal",
                      date(2026, 10, 5), "WH",
                      [{"qty": 1, "unit": "Box", "desc": "Item"}],
                      so=f"SO-IMPORT-{number}")
        data["last_saved"] = "01-Nov-2026 10:00"
        data["other_item_forms"] = {}
        reports.append(data)
    source = tmp_path / "FSR_Master_Data_import.json"
    source.write_text(json.dumps({
        "format": fsr_import.FORMAT, "version": 1, "device_id": "bg-phone",
        "inspector": "Phone Inspector", "reports": reports}),
        encoding="utf-8")
    writes = []
    real_save = workbook.Workbook.save

    def counted(wb, filename, *args, **kwargs):
        if "Field_Survey_Reports" in str(filename):
            writes.append(filename)
        return real_save(wb, filename, *args, **kwargs)

    dialog = g["filedialog"]
    original = dialog.askopenfilename
    dialog.askopenfilename = lambda **_: str(source)
    workbook.Workbook.save = counted
    answers.calls.clear()
    try:
        g["import_master_button"].invoke()
        state = live(g)["import_state"]
        assert state["running"]             # the window is not held up
        assert pump(g, lambda: not state["running"], 60)
    finally:
        dialog.askopenfilename = original
        workbook.Workbook.save = real_save

    assert len(writes) == 1                 # one write for 30 reports
    (summary,) = [c[2] for c in answers.calls
                  if c[1] == "Import Master Data" and c[0] == "showinfo"]
    assert "Added: 30" in summary and "in the background" in summary
    assert quiet(g)
    assert all(in_mysql(server, f"FSR-JDC-209912-{n:04d}")
               == f"SO-IMPORT-{n}" for n in range(1, 31))
    assert fsr_save_journal.Journal(book(g)).pending() == []
