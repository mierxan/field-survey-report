"""MySQL conflicts in the real program: a second copy with its own workbook
and the same database. Uses the in-memory FakeServer."""
import json
import tkinter
from pathlib import Path

import pytest

import fsr_mysql_guard
import fsr_save_journal
import fsr_storage
from fake_mysql import FakeServer

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_conflict_home")
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


@pytest.fixture
def copy(app, monkeypatch):
    """The program as one copy connected to a fresh shared database."""
    g, answers = app
    server = FakeServer()
    monkeypatch.setitem(live(g), "db_mysql", server.client())
    monkeypatch.setitem(live(g), "mysql_numbers", {"values": []})
    toasts = []
    monkeypatch.setitem(live(g), "notify", lambda message, bootstyle="success":
                        toasts.append(message))
    journal = fsr_save_journal.Journal(book(g))
    for record in journal.pending():
        journal.remove(record)
    answers.calls.clear()
    yield g, answers, server, toasts
    dialog = live(g)["conflict_state"]["dialog"]
    if dialog is not None:
        try:
            dialog.destroy()
        except tkinter.TclError:
            pass
    for record in journal.pending():
        journal.remove(record)


def fill(g, so):
    g["app_shell"].show("inspection")
    g["new_report"](confirm=False)
    g["choose_condition"]("Good Order")
    g["set_entry"](g["SO_number_entry"], so)
    g["schedule_entries"]["activity"].set("Receiving")
    g["location_combobox"].set("Conflict Warehouse")
    section = g["item_frames"][0]
    cols = g["ITEM_FORM_HEADERS"]
    for header, value in {"Description of Goods": "Valve", "Quantity": "3",
                          "UOM": "PCS", "Packaging": "Box"}.items():
        g["set_entry"](section.rows[0][cols.index(header)], value)
    return g["control_entry"].get()


def other_copys_report(server, control, so="THE OTHER COPY'S REPORT"):
    """Another copy of the program saved a different report under this
    number."""
    from datetime import date

    from factories import report
    data = report(control, "Receiving", date(2026, 11, 1), "Elsewhere",
                  [{"qty": 9, "unit": "Box", "desc": "Other goods",
                    "ref": f"RCV-{control}-1-01"}], so=so)
    server.put(data)


def in_mysql(server, control):
    found = server.get(control)
    return found["general_information"]["so_number"] if found else None


def waiting(g):
    return fsr_save_journal.conflicts(fsr_save_journal.Journal(book(g)))


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def press(dialog, label):
    for widget in widgets(dialog):
        if widget.winfo_class() == "TButton" and \
                str(widget.cget("text")) == label:
            assert str(widget.cget("state")) != "disabled", label
            widget.invoke()
            return
    raise AssertionError(f"no button {label!r}")


def dialog_text(dialog):
    return "\n".join(w.get("1.0", "end") for w in widgets(dialog)
                     if isinstance(w, tkinter.Text))


def notes(answers):
    return [m for kind, title, m in answers.calls
            if kind == "showwarning" and title == "Report Saved - Note"]


def offline_collision(g, server, so="MINE, SAVED OFFLINE"):
    """Saved while MySQL was away; meanwhile another copy used the number."""
    server.down = True
    control = fill(g, so)
    assert g["save_report"]() is True
    server.down = False
    other_copys_report(server, control)
    g["finish_unfinished_saves"](mysql_ok=True)        # MySQL is back
    return control


# ---------- numbering ----------

def test_new_report_takes_a_number_free_in_the_workbook_and_in_mysql(copy):
    g, answers, server, _ = copy
    g["new_report"](confirm=False)             # an untouched new report
    first = g["control_entry"].get()
    other_copys_report(server, first)
    live(g)["refresh_mysql_numbers"]()         # what "Server active" does

    control = g["control_entry"].get()
    # and every further new report avoids MySQL's numbers too
    g["new_report"](confirm=False)
    assert g["control_entry"].get() == control

    assert control != first                    # not handed out blindly
    assert control not in [r["control_no"] for r in server.reports.values()]
    assert control not in [e[0] for e in
                           fsr_storage.list_saved_reports(book(g))]


def test_number_is_checked_again_at_save_time(copy):
    """The number on the form was free when the form opened; another copy
    used it before Save was clicked."""
    g, answers, server, _ = copy
    shown = fill(g, "SO-RACE")
    other_copys_report(server, shown)

    assert g["save_report"]() is True

    saved_as = g["control_entry"].get()
    assert saved_as != shown
    assert in_mysql(server, shown) == "THE OTHER COPY'S REPORT"
    assert in_mysql(server, saved_as) == "SO-RACE"
    assert fsr_storage.read_report(book(g), saved_as)[
        "general_information"]["so_number"] == "SO-RACE"
    assert waiting(g) == [] and notes(answers) == []


# ---------- a conflict: local work goes on, nothing is overwritten ----------

def test_offline_collision_waits_and_overwrites_nothing(copy):
    g, answers, server, toasts = copy
    control = offline_collision(g, server)

    assert in_mysql(server, control) == "THE OTHER COPY'S REPORT"
    assert fsr_storage.read_report(book(g), control)[
        "general_information"]["so_number"] == "MINE, SAVED OFFLINE"
    (record,) = waiting(g)
    assert record["control"] == control
    # the account menu shows that one waits
    menu = live(g)["account_menu"]
    labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
              if menu.type(i) == "command"]
    assert "MySQL Conflicts...  (1 waiting)" in labels
    # and no box interrupted the start
    assert [c for c in answers.calls if c[0] == "showerror"] == []


def test_edit_of_a_report_changed_elsewhere_is_saved_locally_and_asked(copy):
    g, answers, server, toasts = copy
    control = fill(g, "SO-FIRST")
    assert g["save_report"]() is True
    assert in_mysql(server, control) == "SO-FIRST"
    other_copys_report(server, control, so="CHANGED BY ANOTHER COPY")
    answers.calls.clear()
    toasts.clear()

    g["set_entry"](g["SO_number_entry"], "SO-EDITED HERE")
    assert g["save_report"]() is True

    assert in_mysql(server, control) == "CHANGED BY ANOTHER COPY"
    assert fsr_storage.read_report(book(g), control)[
        "general_information"]["so_number"] == "SO-EDITED HERE"
    (note,) = notes(answers)
    assert "saved in the Excel file, but MySQL was NOT updated" in note
    assert "changed in MySQL by another copy" in note
    assert "Nothing in MySQL was changed" in note
    assert any("NOT sent to MySQL" in t for t in toasts)
    dialog = live(g)["conflict_state"]["dialog"]
    assert dialog.winfo_exists() and dialog.title() == "MySQL Conflicts"
    text = dialog_text(dialog)
    assert "IN THIS PC'S EXCEL FILE (mine)" in text and "IN MYSQL" in text
    assert "SO-EDITED HERE" in text and "CHANGED BY ANOTHER COPY" in text


# ---------- condition 1: the safe default ----------

def test_closing_the_window_writes_nothing_and_the_conflict_waits(copy):
    g, answers, server, _ = copy
    control = offline_collision(g, server)
    dialog = live(g)["open_mysql_conflicts"]()
    press(dialog, "Close")
    assert in_mysql(server, control) == "THE OTHER COPY'S REPORT"
    assert server.writes == [] and len(waiting(g)) == 1


def test_default_button_and_enter_keep_mysqls_report(copy):
    g, answers, server, toasts = copy
    control = offline_collision(g, server)
    dialog = live(g)["open_mysql_conflicts"]()
    g["window"].update()
    assert str(dialog.focus_get().cget("text")) == \
        "Keep MySQL's (write nothing)"

    dialog.event_generate("<Return>")
    g["window"].update()

    assert in_mysql(server, control) == "THE OTHER COPY'S REPORT"
    assert server.writes == [] and waiting(g) == []
    assert not (fsr_mysql_guard.Guard(None, book(g)).replaced_dir).exists()
    assert any("MySQL keeps its report" in t for t in toasts)
    assert fsr_storage.read_report(book(g), control)[
        "general_information"]["so_number"] == "MINE, SAVED OFFLINE"


# ---------- the two deliberate choices ----------

def test_replace_needs_a_click_and_a_yes_and_keeps_the_old_version(copy):
    g, answers, server, toasts = copy
    control = offline_collision(g, server)
    dialog = live(g)["open_mysql_conflicts"]()

    answers.yes = False                         # clicked, then said No
    press(dialog, "Replace MySQL's with mine...")
    assert in_mysql(server, control) == "THE OTHER COPY'S REPORT"
    question = next(c for c in answers.calls
                    if c[1] == "Replace the report in MySQL?")
    assert "kept first" in question[2]

    answers.yes = True
    try:
        press(dialog, "Replace MySQL's with mine...")
    finally:
        answers.yes = True

    assert in_mysql(server, control) == "MINE, SAVED OFFLINE"
    assert waiting(g) == []
    replaced = fsr_mysql_guard.Guard(None, book(g)).replaced_dir
    (kept,) = [p for p in replaced.glob("*.json")
               if p.name.startswith(control)]
    record = json.loads(kept.read_text(encoding="utf-8"))
    assert record["report"]["general_information"]["so_number"] == \
        "THE OTHER COPY'S REPORT"
    assert record["replaced_by"] == "Test User"
    assert control in (replaced / "replaced_log.csv").read_text(
        encoding="utf-8")


def test_renumber_changes_the_report_here_and_leaves_mysqls_alone(copy):
    g, answers, server, toasts = copy
    control = offline_collision(g, server)
    g["load_report_into_form"](control, "excel")    # open on the form
    dialog = live(g)["open_mysql_conflicts"]()

    press(dialog, "Save mine under the next free number...")

    new = g["control_entry"].get()
    assert new != control                       # the form follows
    assert in_mysql(server, control) == "THE OTHER COPY'S REPORT"
    assert in_mysql(server, new) == "MINE, SAVED OFFLINE"
    saved = [e[0] for e in fsr_storage.list_saved_reports(book(g))]
    assert new in saved and control not in saved
    row = fsr_storage.read_report(book(g), new)["item_lists"][0]["rows"][0]
    assert row["Receiving Ref"] == f"RCV-{new}-1-01"
    assert waiting(g) == []
    assert any(f"{control} is now {new}" in t for t in toasts)


# ---------- Sync to MySQL ----------

def test_sync_shows_what_differs_and_sends_only_the_safe_ones(copy):
    g, answers, server, _ = copy
    server.down = True
    mine_new = fill(g, "SYNC-NEW")
    assert g["save_report"]() is True
    mine_clash = fill(g, "SYNC-CLASH")
    assert g["save_report"]() is True
    server.down = False
    journal = fsr_save_journal.Journal(book(g))
    for record in journal.pending():
        journal.remove(record)
    other_copys_report(server, mine_clash)
    before = len(server.reports)
    answers.calls.clear()

    dialog = live(g)["sync_all_to_mysql"]()

    assert dialog is not None and dialog.title() == "Sync to MySQL"
    labels = "\n".join(str(w.cget("text")) for w in widgets(dialog)
                       if w.winfo_class() in ("TLabel", "TCheckbutton"))
    assert "Different in MySQL: 1" in labels
    assert "NOT sent" in labels and "unless you tick them" in labels
    assert mine_clash in labels
    ticks = [w for w in widgets(dialog) if w.winfo_class() == "TCheckbutton"]
    assert ticks and all(not w.instate(["selected"]) for w in ticks)
    assert len(server.reports) == before        # the preview wrote nothing

    press(dialog, "Send (ticked ones are replaced)")

    assert in_mysql(server, mine_new) == "SYNC-NEW"
    assert in_mysql(server, mine_clash) == "THE OTHER COPY'S REPORT"
    assert mine_clash in [r["control"] for r in waiting(g)]
    summary = next(m for kind, title, m in answers.calls
                   if title == "Sync to MySQL" and "Sent to MySQL" in m)
    assert "NOT sent (MySQL holds a different report): 1" in summary


def test_restore_from_mysql_then_edit_needs_no_question(copy):
    """A copy brings reports in with Restore Excel from MySQL. They are the
    same here and in MySQL, so they are this copy's own afterwards."""
    g, answers, server, _ = copy
    other_copys_report(server, "FSR-ZZZ-202611-0001", so="FROM MYSQL")
    live(g)["restore_excel_from_mysql"]()
    assert fsr_storage.read_report(book(g), "FSR-ZZZ-202611-0001")[
        "general_information"]["so_number"] == "FROM MYSQL"
    assert server.writes == []                  # restoring writes no MySQL

    g["load_report_into_form"]("FSR-ZZZ-202611-0001", "excel")
    g["set_entry"](g["SO_number_entry"], "FROM MYSQL, EDITED HERE")
    answers.calls.clear()
    assert g["save_report"]() is True

    assert in_mysql(server, "FSR-ZZZ-202611-0001") == \
        "FROM MYSQL, EDITED HERE"
    assert notes(answers) == [] and waiting(g) == []

    # but if another copy changes it in MySQL meanwhile, the next edit asks
    other_copys_report(server, "FSR-ZZZ-202611-0001", so="CHANGED ELSEWHERE")
    g["set_entry"](g["SO_number_entry"], "EDITED AGAIN HERE")
    assert g["save_report"]() is True
    assert in_mysql(server, "FSR-ZZZ-202611-0001") == "CHANGED ELSEWHERE"
    assert len(waiting(g)) == 1


def test_first_start_adopts_the_existing_reports_without_questions(copy):
    """The workbook and MySQL hold the same reports and there is no ledger
    yet (as on the owner's PC before this fix)."""
    g, answers, server, _ = copy
    server.down = True
    made = []
    for so in ("ADOPT-1", "ADOPT-2", "ADOPT-3"):
        made.append(fill(g, so))
        assert g["save_report"]() is True
    server.down = False
    journal = fsr_save_journal.Journal(book(g))
    for record in journal.pending():
        journal.remove(record)
    for control in made:                        # MySQL holds the same ones
        server.put(fsr_storage.read_report(book(g), control))
    guard = fsr_mysql_guard.Guard(None, book(g))
    guard.path.unlink(missing_ok=True)          # no ledger
    answers.calls.clear()

    adopted = live(g)["adopt_existing_reports"]()   # at "Server active"

    assert set(made) <= set(adopted) and server.writes == []
    assert answers.calls == []
    g["load_report_into_form"](made[0], "excel")
    g["set_entry"](g["SO_number_entry"], "ADOPT-1 EDITED")
    assert g["save_report"]() is True
    assert in_mysql(server, made[0]) == "ADOPT-1 EDITED"
    assert notes(answers) == [] and waiting(g) == []
