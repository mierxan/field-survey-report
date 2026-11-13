"""Save (fsr_save_ui.save_report) in the real program, the paths the other
save tests do not take: what stops a save before anything is written, a
failed write, the notes for parts that could not be written, the report
form, and MySQL done at once when the save record cannot be written.
Invented reports in a temporary folder; MySQL is the in-memory FakeServer."""
from pathlib import Path

import pytest

import fsr_save_journal
import fsr_save_ui
import fsr_storage
import fsr_withdrawal
from fake_mysql import FakeServer

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_save_ui_home")
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


def saved_numbers(g):
    return [e[0] for e in fsr_storage.list_saved_reports(book(g))] \
        if book(g).exists() else []


def notes(answers):
    return [m for kind, title, m in answers.calls
            if kind == "showwarning" and title == "Report Saved - Note"]


def titles(answers, kind):
    return [t for k, t, _ in answers.calls if k == kind]


@pytest.fixture
def program(app, monkeypatch):
    g, answers = app
    toasts = []
    monkeypatch.setitem(live(g), "notify", lambda message, bootstyle="success":
                        toasts.append((bootstyle, message)))
    journal = fsr_save_journal.Journal(book(g))
    for record in journal.pending():
        journal.remove(record)
    answers.calls.clear()
    yield g, answers, toasts
    for record in journal.pending():
        journal.remove(record)


def fill(g, so, condition="Good Order", activity="Receiving"):
    g["app_shell"].show("inspection")
    g["new_report"](confirm=False)
    if condition:
        g["choose_condition"](condition)
    g["set_entry"](g["SO_number_entry"], so)
    g["schedule_entries"]["activity"].set(activity)
    g["location_combobox"].set("Save UI Warehouse")
    section = g["item_frames"][0]
    cols = g["ITEM_FORM_HEADERS"]
    for header, value in {"Description of Goods": "Valve", "Quantity": "3",
                          "UOM": "PCS", "Packaging": "Box"}.items():
        g["set_entry"](section.rows[0][cols.index(header)], value)
    return g["control_entry"].get()


# ---------- stopped before anything is written ----------

def test_no_cargo_condition_stops_the_save(program):
    g, answers, _ = program
    control = fill(g, "SO-UI-NOCOND", condition=None)
    live(g)["condition_var"].set("")
    assert g["save_report"]() is False
    assert answers.calls[-1][:2] == ("showwarning", "Cargo Condition")
    assert control not in saved_numbers(g)


def test_no_so_number_stops_the_save_and_shows_the_field(program):
    g, answers, _ = program
    control = fill(g, "")
    assert g["save_report"]() is False
    assert answers.calls[-1][:2] == ("showwarning", "Missing SO Number")
    w = live(g)
    assert w["notebook"].select() == str(w["general_tab"])
    assert control not in saved_numbers(g)


def test_a_field_in_the_wrong_format_stops_the_save(program, monkeypatch):
    g, answers, _ = program
    control = fill(g, "SO-UI-FORMAT")
    monkeypatch.setitem(live(g), "validate_format_fields", lambda: False)
    assert g["save_report"]() is False
    assert control not in saved_numbers(g)


def test_bad_order_without_incident_lines_asks_first(program):
    g, answers, _ = program
    control = fill(g, "SO-UI-BAD", condition="Bad Order")
    answers.yes = False
    try:
        assert g["save_report"]() is False
    finally:
        answers.yes = True
    assert ("askyesno", "Bad Order - No Incident Lines") == \
        answers.calls[-1][:2]
    w = live(g)
    assert w["notebook"].select() == str(w["incident_tab"])
    assert control not in saved_numbers(g)
    assert g["save_report"]() is True               # "Save anyway"
    assert control in saved_numbers(g)


def test_without_openpyxl_nothing_is_saved(program, monkeypatch):
    g, answers, _ = program
    control = fill(g, "SO-UI-NOXL")
    told = []
    monkeypatch.setattr(fsr_save_ui, "Workbook", None)
    monkeypatch.setitem(live(g), "excel_missing_message",
                        lambda: told.append(1))
    assert g["save_report"]() is False
    assert told == [1] and control not in saved_numbers(g)


def test_a_failed_write_says_so_and_keeps_no_record(program, monkeypatch):
    g, answers, _ = program
    control = fill(g, "SO-UI-FAIL")

    def broken(*args, **kwargs):
        raise ValueError("the sheet has an unexpected layout")
    monkeypatch.setattr(fsr_storage, "write_report_to_excel", broken)
    assert g["save_report"]() is False
    ((kind, title, message),) = [c for c in answers.calls
                                 if c[0] == "showerror"]
    assert title == "Save Error"
    assert "Unable to save the report" in message
    assert "unexpected layout" in message
    assert fsr_save_journal.Journal(book(g)).pending() == []
    assert control not in saved_numbers(g)


# ---------- saved, with a note for a part that was not written ----------

def test_other_item_forms_not_written_is_said(program, monkeypatch):
    g, answers, _ = program
    control = fill(g, "SO-UI-FORMS")

    def disk_full(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(fsr_storage, "save_other_item_forms", disk_full)
    assert g["save_report"]() is True
    (note,) = notes(answers)
    assert "The lines of the other Item List forms could not be saved" in note
    assert "disk full" in note and "Click Save again to retry." in note
    assert "finished automatically at the next save" in note
    assert control in saved_numbers(g)


def test_po_lists_not_written_is_said(program, monkeypatch):
    g, answers, _ = program
    fill(g, "SO-UI-LISTS")

    def broken(*args, **kwargs):
        raise OSError("PO_Master.xlsx is damaged")
    monkeypatch.setattr(fsr_withdrawal, "sync_item_lists", broken)
    assert g["save_report"]() is True
    (note,) = notes(answers)
    assert "PO_Master and Withdrawn_Item could not be updated:" in note
    assert "PO_Master.xlsx is damaged" in note


def test_report_form_open_in_another_program(program, monkeypatch):
    g, answers, _ = program
    control = fill(g, "SO-UI-PRINT")

    def in_use(*args, **kwargs):
        raise PermissionError("in use")
    monkeypatch.setitem(live(g), "create_report_forms", in_use)
    assert g["save_report"]() is True
    (note,) = notes(answers)
    assert "report form could not be updated because it is open" in note
    assert control in saved_numbers(g)


def test_report_form_that_fails_otherwise(program, monkeypatch):
    g, answers, _ = program
    fill(g, "SO-UI-PRINT-2")

    def broken(*args, **kwargs):
        raise RuntimeError("template missing")
    monkeypatch.setitem(live(g), "create_report_forms", broken)
    assert g["save_report"]() is True
    (note,) = notes(answers)
    assert note == "The report form could not be created:\ntemplate missing"


# ---------- MySQL ----------

@pytest.fixture
def mysql(program, monkeypatch):
    g, answers, toasts = program
    server = FakeServer()
    monkeypatch.setitem(live(g), "db_mysql", server.client())
    monkeypatch.setitem(live(g), "mysql_numbers", {"values": []})
    dots = []
    monkeypatch.setitem(live(g), "set_mysql_dots",
                        lambda state, *detail: dots.append(state))
    opened = []
    monkeypatch.setitem(live(g), "open_mysql_conflicts",
                        lambda select=None: opened.append(select))
    return g, answers, toasts, server, dots, opened


def no_record(monkeypatch):
    """The save record cannot be written (as on a full or read-only disk):
    the save goes on, and MySQL is done at once."""
    def cannot(*args, **kwargs):
        raise OSError("the record file cannot be written")
    monkeypatch.setattr(fsr_save_journal, "open_save", cannot)


def test_a_new_number_taken_in_mysql_moves_to_a_free_one(mysql):
    g, answers, toasts, server, _, _ = mysql
    from test_mysql_conflicts_gui import other_copys_report
    control = fill(g, "SO-UI-TAKEN")
    other_copys_report(server, control)
    assert g["save_report"]() is True
    now = g["control_entry"].get()
    assert now != control
    assert now in saved_numbers(g) and control not in saved_numbers(g)
    assert server.get(control)["general_information"]["so_number"] == \
        "THE OTHER COPY'S REPORT"                     # untouched
    assert server.get(now)["general_information"]["so_number"] == \
        "SO-UI-TAKEN"


def test_without_a_record_mysql_is_written_at_once(mysql, monkeypatch):
    g, answers, toasts, server, dots, _ = mysql
    no_record(monkeypatch)
    control = fill(g, "SO-UI-NOREC")
    assert g["save_report"]() is True
    assert server.get(control)["general_information"]["so_number"] == \
        "SO-UI-NOREC"
    assert dots == ["ok"]
    assert control in live(g)["mysql_numbers"]["values"]
    assert notes(answers) == []
    assert toasts[-1][0] == "success" and control in toasts[-1][1]
    assert fsr_save_journal.Journal(book(g)).pending() == []


def test_without_a_record_a_conflict_waits_for_a_decision(mysql,
                                                          monkeypatch):
    g, answers, toasts, server, dots, opened = mysql
    from test_mysql_conflicts_gui import other_copys_report
    control = fill(g, "SO-UI-CONFLICT")
    assert g["save_report"]() is True              # this copy's report
    other_copys_report(server, control)            # replaced by another PC
    answers.calls.clear()
    toasts.clear()
    no_record(monkeypatch)
    assert g["save_report"]() is True              # saved again (editing)
    (note,) = notes(answers)
    assert "saved in the Excel file, but MySQL was NOT updated" in note
    assert "Nothing in MySQL was changed" in note
    assert server.get(control)["general_information"]["so_number"] == \
        "THE OTHER COPY'S REPORT"
    assert toasts[-1][0] == "warning"
    assert "holds a different report under this number" in toasts[-1][1]
    assert len(opened) == 1


def test_without_a_record_a_mysql_error_is_shown(mysql, monkeypatch):
    g, answers, toasts, server, dots, _ = mysql
    no_record(monkeypatch)
    client = live(g)["db_mysql"]

    def refused(*args, **kwargs):
        error = OSError("Access denied for user 'fsr_app'")
        error.errno = 1045
        raise error
    monkeypatch.setattr(client, "write_report", refused)
    control = fill(g, "SO-UI-DENIED")
    assert g["save_report"]() is True
    (note,) = notes(answers)
    assert "saved to Excel, but NOT to MySQL" in note
    assert "Access denied" in note
    assert "finished automatically" not in note     # no record to finish it
    assert dots == ["bad"]
    assert control in saved_numbers(g) and server.get(control) is None


def test_without_a_record_failed_master_lists_are_shown(mysql, monkeypatch):
    g, answers, toasts, server, dots, _ = mysql
    no_record(monkeypatch)
    client = live(g)["db_mysql"]

    def broken(*args, **kwargs):
        raise OSError("master_list table is missing")
    monkeypatch.setattr(client, "save_master_lists", broken)
    fill(g, "SO-UI-LISTS-DB")
    assert g["save_report"]() is True
    (note,) = notes(answers)
    assert "NOT to MySQL" in note and "master_list table is missing" in note
    assert dots == ["bad"]
