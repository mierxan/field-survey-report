"""The real program on the reports database (Phase 5), driven without a
person: the move at the first start (with its progress window), saving,
editing and opening reports, a PO-linked Withdrawal, the Weekly Summary,
the daily backup, the Excel export (written after each save, waited for
when closing, an export open in Excel, an export changed outside the
program) and "Change Excel File" to a workbook that has not moved yet.

Invented data in a temporary FSR_HOME; MySQL off."""
import time
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook

import fsr_backup
import fsr_paths
import fsr_sqlite_export as export
import fsr_sqlite_store as sq
import fsr_storage
import fsr_store
from conftest import ANCHOR
from factories import report
from warehouse import sample_data as sd

pytestmark = pytest.mark.gui

WORKBOOK = "Field_Survey_Reports.xlsx"


def pump(g, until, limit=60):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        g["window"].update()
        if until():
            g["window"].update()
            return True
        time.sleep(0.02)
    return False


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_sqlite_home")
    sd.generate(home / "excel", anchor=ANCHOR, workbook_name=WORKBOOK)
    try:
        g, answers = h.start_app(home, {"FSR_NO_SQLITE": "0"})
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    g["home"] = home
    # the move runs from the start (window.after): let it finish
    assert pump(g, lambda: sq.is_active(book(g))
                and not live(g)["db_move_state"]["running"])
    yield g, answers
    h.stop_app(g, answers)


def live(g):
    return g["save_report"].__globals__


def book(g):
    return Path(g["excel_state"]["path"])


def store(g):
    return live(g)["data_store"]()


@pytest.fixture
def program(app):
    g, answers = app
    answers.calls.clear()
    answers.yes = True
    g["new_report"](confirm=False)
    g["app_shell"].show("inspection")
    yield g, answers


def fill(g, so, activity="Receiving", condition="Good Order"):
    g["new_report"](confirm=False)
    g["choose_condition"](condition)
    g["set_entry"](g["SO_number_entry"], so)
    g["schedule_entries"]["activity"].set(activity)
    g["location_combobox"].set("SQLite Warehouse")
    section = g["item_frames"][0]
    cols = g["ITEM_FORM_HEADERS"]
    for header, value in {"Description of Goods": "Database pump",
                          "Quantity": "5", "UOM": "PCS", "Packaging": "Box",
                          "PO Number": "PO-SQL-1"}.items():
        g["set_entry"](section.rows[0][cols.index(header)], value)
    return g["control_entry"].get()


def in_workbook(g, control):
    return [r[0] for r in fsr_storage.list_saved_reports(book(g))
            if r[0] == control]


# ---------- the first start ----------

def test_the_first_start_moved_the_reports_and_said_so(app):
    g, answers = app
    said = [m for kind, title, m in answers.calls
            if title == "Reports Database"]
    assert said and "were moved into the reports database" in said[0]
    import fsr_db_location
    assert str(fsr_db_location.database_dir()) in said[0]   # where it is
    assert store(g).kind == "sqlite"
    assert len(store(g).list_reports()) == 84
    backups = list((book(g).parent / "Backups").glob("before_sqlite_*"))
    assert len(backups) == 1 and (backups[0] / WORKBOOK).exists()


# ---------- saving, editing, opening ----------

def test_a_save_goes_into_the_database_and_the_export(program):
    g, answers = program
    control = fill(g, "SO-SQL-SAVE")
    assert g["save_report"]() is True
    saved = store(g).read_report(control)
    assert saved["general_information"]["so_number"] == "SO-SQL-SAVE"
    assert in_workbook(g, control) == [control]           # the export
    assert export.is_current(store(g))
    assert live(g)["fsr_save_journal"].Journal(book(g)).pending() == []
    # the daily backup is a copy of the database
    copy = fsr_backup.backup_path(store(g).backup_name, date.today())
    assert copy.exists()
    assert not [m for k, t, m in answers.calls if k == "showwarning"]


def test_editing_and_opening_again(program):
    g, answers = program
    control = fill(g, "SO-SQL-EDIT")
    assert g["save_report"]() is True
    g["set_entry"](g["SO_number_entry"], "SO-SQL-EDITED")
    assert g["save_report"]() is True
    assert len([r for r in store(g).list_reports() if r[0] == control]) == 1
    g["new_report"](confirm=False)
    g["load_report_into_form"](control, "excel")
    assert g["SO_number_entry"].get() == "SO-SQL-EDITED"
    assert fsr_storage.read_report(book(g), control)[
        "general_information"]["so_number"] == "SO-SQL-EDITED"


def test_a_po_linked_withdrawal(program):
    g, answers = program
    from test_withdrawal_gui import begin, pick, set_qty
    receiving = report("FSR-SQL-RCV-1", "Receiving", date(2026, 1, 5))
    row = {h: "" for h in fsr_storage.ITEM_LINE_HEADERS}
    row.update({"Description of Goods": "Pump", "PO Number": "4500001",
                "Packaging": "Crate", "Quantity": "100 pcs"})
    receiving["item_lists"][0]["rows"] = [row]
    store(g).write_report(receiving, True)
    g["new_report"](confirm=False)
    begin(g, so="SO-SQL-WD")
    pick(g)
    assert set_qty(g, 0, "30")
    control = g["control_entry"].get()
    assert g["save_report"]() is True
    assert store(g).owns_withdrawal(control)
    taken = store(g).read_withdrawal_report(control)
    assert taken["item_lists"][0]["rows"][0]["Quantity"] == "30"
    (line,) = store(g).find_po("4500001").lines
    assert line.remaining_qty == 70
    # the Withdrawal workbook is exported too, and PO_Master follows
    linked = book(g).with_name(fsr_paths.WITHDRAWAL_WORKBOOK_NAME)
    assert control in fsr_storage.withdrawal_control_numbers(book(g))
    assert linked.exists()
    po_master = load_workbook(book(g).with_name(fsr_paths.PO_MASTER_NAME))
    assert any("Pump" in row for row in po_master.active.iter_rows(
        values_only=True))


def test_the_weekly_summary_reads_the_database(program):
    g, answers = program
    fill(g, "SO-SQL-WEEK")
    assert g["save_report"]() is True
    today = date.today()
    lines = g["weekly_rows_from_excel"](today, today)
    assert any(line[0] == "SO-SQL-WEEK" for line in lines)


# ---------- the export ----------

def test_closing_waits_for_the_export(program, monkeypatch):
    g, answers = program
    sender = live(g)["export_sender"]
    monkeypatch.setattr(sender, "inline", False)          # the real thread
    real = export.write_export

    def slow(*args, **kwargs):
        time.sleep(0.6)
        return real(*args, **kwargs)
    monkeypatch.setattr(export, "write_export", slow)
    store(g).write_report(report("FSR-SQL-CLOSE-1", "Receiving",
                                 date(2026, 11, 5)), True)
    closed = []
    dialog = live(g)["close_when_sent"](lambda: closed.append(True))
    assert dialog is not None
    texts = [str(w.cget("text")) for w in dialog.winfo_children()
             if w.winfo_class() in ("TLabel", "TButton")]
    assert "Bringing the Excel file up to date..." in texts
    assert ("Close now; the Excel file is brought up to date at the next "
            "start") in texts
    assert pump(g, lambda: closed == [True], limit=30)
    assert in_workbook(g, "FSR-SQL-CLOSE-1") == ["FSR-SQL-CLOSE-1"]


def test_an_export_open_in_excel_is_said_once_and_tried_again(program,
                                                              monkeypatch):
    g, answers = program
    toasts = []
    monkeypatch.setitem(live(g), "notify",
                        lambda message, bootstyle="success":
                        toasts.append((bootstyle, message)))
    retries = []
    window = live(g)["window"]
    real_after = window.after
    monkeypatch.setattr(window, "after", lambda ms, func=None, *a:
                        retries.append(ms) if ms == live(g)["EXPORT_RETRY_MS"]
                        else real_after(ms, func, *a))

    def locked(*args, **kwargs):
        raise PermissionError("in use")
    live(g)["export_state"]["warned"] = False
    with monkeypatch.context() as in_use:           # the file is open
        in_use.setattr(export, "_save", locked)
        control = fill(g, "SO-SQL-LOCKED")
        assert g["save_report"]() is True
        store(g).write_report(report("FSR-SQL-LOCKED-2", "Receiving",
                                     date(2026, 11, 5)), True)
    warned = [m for style, m in toasts if "open in another program" in m]
    assert len(warned) == 1 and "safe in the database" in warned[0]
    assert retries == [live(g)["EXPORT_RETRY_MS"]]   # one waiting, not one
                                                   # per failed round
    assert store(g).read_report(control)["general_information"][
        "so_number"] == "SO-SQL-LOCKED"
    live(g)["export_state"]["retry"] = False        # the recorded retry ...
    live(g)["request_export_round"]()               # ... runs: file closed
    assert in_workbook(g, control) == [control]
    assert live(g)["export_state"]["warned"] is False


def test_an_export_changed_outside_is_never_overwritten(program):
    g, answers = program
    control = fill(g, "SO-SQL-MINE")
    assert g["save_report"]() is True
    # someone types into the Excel file and saves it
    other = fsr_store.ExcelStore(book(g))
    other.write_report(report("FSR-SQL-TYPED-1", "Receiving",
                              date(2026, 11, 5), so="SO-TYPED"), True)
    answers.calls.clear()
    fill(g, "SO-SQL-AFTER")
    assert g["save_report"]() is True
    ((kind, message),) = [(k, m) for k, t, m in answers.calls
                          if t == "Excel File Changed Outside the Program"]
    assert kind == "showwarning"
    assert "FSR-SQL-TYPED-1" in message and "were added" in message
    kept = list(book(g).parent.glob("Field_Survey_Reports (changed outside "
                                    "*).xlsx"))
    assert len(kept) == 1
    assert store(g).read_report("FSR-SQL-TYPED-1")["general_information"][
        "so_number"] == "SO-TYPED"
    assert in_workbook(g, control) == [control]
    assert export.changed_outside(store(g)) == []


# ---------- Change Excel File ----------

def test_another_workbook_moves_in_when_it_is_chosen(program, monkeypatch,
                                                     tmp_path):
    g, answers = program
    other = tmp_path / "Other_Reports.xlsx"
    fsr_store.ExcelStore(other).write_report(
        report("FSR-OTH-202611-0001", "Receiving", date(2026, 11, 5),
               so="SO-OTHER"), False)
    before = book(g)
    monkeypatch.setitem(live(g), "choose_excel_path", lambda: other)
    try:
        g["change_excel_file"]()
        assert pump(g, lambda: sq.is_active(other)
                    and not live(g)["db_move_state"]["running"])
        assert store(g).kind == "sqlite"
        assert store(g).read_report("FSR-OTH-202611-0001")[
            "general_information"]["so_number"] == "SO-OTHER"
        said = [m for kind, title, m in answers.calls
                if title == "Reports Database"]
        assert said and "1 report(s) were moved" in said[-1]
    finally:
        live(g)["excel_state"]["path"] = before
        live(g)["settings"]["excel_path"] = str(before)


# ---------- Import Master Data ----------

def test_import_master_data_into_the_database(program, monkeypatch,
                                              tmp_path):
    g, answers = program
    import fsr_master_export
    site = tmp_path / "site" / "data.xlsx"
    site.parent.mkdir()
    fsr_store.ExcelStore(site).write_report(          # a previous-version PC
        report("FSR-IMP-202611-0001", "Receiving", date(2026, 11, 5),
               so="SO-IMPORTED"), False)
    master = tmp_path / "FSR_Master_Data_site.json"
    fsr_master_export.write_export(site, master, "site-pc", "Site Inspector")
    monkeypatch.setattr(live(g)["filedialog"], "askopenfilename",
                        lambda **kw: str(master))
    live(g)["import_master_data_file"]()
    assert pump(g, lambda: not live(g)["import_state"]["running"])
    asked = [m for k, t, m in answers.calls
             if k == "askyesno" and t == "Import Master Data"]
    assert asked and "A copy of the reports database is made first" in \
        asked[0]
    told = "\n".join(str(m) for k, t, m in answers.calls
                     if t == "Import Master Data" and k != "askyesno")
    assert "Copy of the reports database before the import" in told
    assert ".sqlite3" in told
    assert store(g).read_report("FSR-IMP-202611-0001")[
        "general_information"]["so_number"] == "SO-IMPORTED"
    assert in_workbook(g, "FSR-IMP-202611-0001") == ["FSR-IMP-202611-0001"]


# ---------- where the database is (item 2) ----------

def test_the_account_menu_shows_where_the_database_is(program):
    g, answers = program
    menu = live(g)["account_menu"]
    live(g)["rebuild_account_menu"]()
    labels = [menu.entrycget(i, "label")
              for i in range(menu.index("end") + 1)
              if menu.type(i) == "command"]
    assert "Reports Database..." in labels
    dialog = live(g)["open_database_info"]()
    try:
        def texts(widget):
            for child in widget.winfo_children():
                if child.winfo_class() in ("TLabel", "TButton"):
                    yield str(child.cget("text"))
                yield from texts(child)
        shown = "\n".join(texts(dialog))
        db = live(g)["data_store"]().db_path
        assert str(db) in shown
        import fsr_db_location
        assert db.parent == fsr_db_location.database_dir()
        assert "Local AppData" in shown
        assert "uninstalling or reinstalling the program leaves it in place" \
            in shown
        assert "each one is a FULL copy of the reports" in shown
        assert str(book(g).parent / "Backups") in shown
        assert "Open the database folder" in shown
    finally:
        dialog.destroy()


def test_a_moved_workbook_chosen_again_finds_its_database(program,
                                                          monkeypatch,
                                                          tmp_path):
    g, answers = program
    first = tmp_path / "first" / "Moving_Reports.xlsx"
    first.parent.mkdir()
    fsr_store.ExcelStore(first).write_report(
        report("FSR-MOV-202611-0001", "Receiving", date(2026, 11, 5),
               so="SO-MOVING"), False)
    before = book(g)
    try:
        monkeypatch.setitem(live(g), "choose_excel_path", lambda: first)
        g["change_excel_file"]()
        assert pump(g, lambda: sq.is_active(first)
                    and not live(g)["db_move_state"]["running"])
        database_id = store(g).database_id
        store(g).write_report(report("FSR-MOV-202611-0002", "Receiving",
                                     date(2026, 11, 6), so="SO-SAVED"), True)
        assert pump(g, lambda: live(g)["export_sender"].idle())
        # back to the usual workbook; the folder is moved meanwhile
        monkeypatch.setitem(live(g), "choose_excel_path", lambda: before)
        g["change_excel_file"]()
        moved = tmp_path / "moved_here"
        (tmp_path / "first").rename(moved)
        again = moved / first.name
        answers.calls.clear()
        monkeypatch.setitem(live(g), "choose_excel_path", lambda: again)
        g["change_excel_file"]()
        assert pump(g, lambda: sq.is_active(again)
                    and not live(g)["db_move_state"]["running"])
        said = [m for kind, title, m in answers.calls
                if title == "Reports Database"]
        assert said and "is in a new place" in said[-1]
        assert store(g).database_id == database_id
        assert sorted(r[0] for r in store(g).list_reports()) == [
            "FSR-MOV-202611-0001", "FSR-MOV-202611-0002"]
    finally:
        live(g)["excel_state"]["path"] = before
        live(g)["settings"]["excel_path"] = str(before)
