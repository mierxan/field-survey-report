"""Saving in the real program: the daily backup and the save record."""
import time
from datetime import date
from pathlib import Path

import pytest

import fsr_backup
import fsr_storage
from conftest import ANCHOR
from warehouse import sample_data as sd

pytestmark = pytest.mark.gui

WORKBOOK = "Field_Survey_Reports.xlsx"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_safety_home")
    sd.generate(home / "excel", anchor=ANCHOR, workbook_name=WORKBOOK)
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    g["home"] = home
    yield g, answers
    h.stop_app(g, answers)


def settle(g, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        g["window"].update()
        time.sleep(0.03)


def fill_form(g, so, activity="Receiving", condition="Good Order"):
    g["app_shell"].show("inspection")
    g["new_report"](confirm=False)
    g["choose_condition"](condition)
    g["set_entry"](g["SO_number_entry"], so)
    g["schedule_entries"]["activity"].set(activity)
    g["location_combobox"].set("Safety Warehouse")
    g["supplier_combobox"].set("Test Supplier Alpha Industrial")
    section = g["item_frames"][0]
    cols = g["ITEM_FORM_HEADERS"]
    values = {"Description of Goods": "Safety Pump", "Quantity": "3",
              "UOM": "PCS", "Packaging": "Box"}
    for header, value in values.items():
        g["set_entry"](section.rows[0][cols.index(header)], value)
    return g["control_entry"].get()


def book(g):
    return Path(g["excel_state"]["path"])


def notes(answers):
    return [m for kind, title, m in answers.calls
            if kind == "showwarning" and title == "Report Saved - Note"]


# ---------- the daily backup ----------

def test_first_save_of_the_day_backs_up_the_workbook_as_it_was(app):
    g, answers = app
    folder = book(g).parent / fsr_backup.FOLDER_NAME
    assert not folder.exists()
    before = book(g).read_bytes()
    control = fill_form(g, "SO-BACKUP-1")

    assert g["save_report"]() is True

    today = fsr_backup.backup_path(book(g), date.today())
    assert [p.name for p in folder.iterdir()] == [today.name]
    assert today.read_bytes() == before              # as it was before
    assert book(g).read_bytes() != before
    assert control not in [e[0] for e in fsr_storage.list_saved_reports(today)]
    assert fsr_storage.read_report(book(g), control)["control_no"] == control
    assert not any("backup" in note.lower() for note in notes(answers))


def test_second_save_of_the_day_keeps_the_morning_copy(app):
    g, answers = app
    today = fsr_backup.backup_path(book(g), date.today())
    morning = today.read_bytes()
    fill_form(g, "SO-BACKUP-2")
    assert g["save_report"]() is True
    assert today.read_bytes() == morning
    assert len(list(today.parent.iterdir())) == 1


def test_failed_backup_warns_but_the_report_is_saved(app, monkeypatch):
    g, answers = app
    answers.calls.clear()

    def no_backup(*args, **kwargs):
        raise fsr_backup.BackupError("The backup copy could not be made: "
                                     "disk full")

    monkeypatch.setattr(fsr_backup, "backup_before_save", no_backup)
    control = fill_form(g, "SO-BACKUP-3")

    assert g["save_report"]() is True

    assert fsr_storage.read_report(book(g), control)[
        "general_information"]["so_number"] == "SO-BACKUP-3"
    (note,) = notes(answers)
    assert "backup copy of the Excel file could NOT be made" in note
    assert "disk full" in note and "The report itself was saved" in note
    log_text = Path(g["LOG_FILE"]).read_text(encoding="utf-8")
    assert "Daily backup failed" in log_text


def test_number_of_backups_comes_from_the_settings(app, monkeypatch):
    g, answers = app
    seen = []
    real = fsr_backup.backup_before_save
    monkeypatch.setattr(fsr_backup, "backup_before_save",
                        lambda path, keep, **kw: seen.append(keep)
                        or real(path, keep, **kw))
    fill_form(g, "SO-BACKUP-4")
    assert g["save_report"]() is True
    monkeypatch.setitem(g["settings"], "backup_keep", 3)
    fill_form(g, "SO-BACKUP-5")
    assert g["save_report"]() is True
    assert seen == [14, 3]


# ---------- a save that stops halfway ----------

import fsr_save_journal as journal_module  # noqa: E402


def live(g):
    """The program's real globals (`g` from runpy is only a copy)."""
    return g["save_report"].__globals__


def pending(g):
    return journal_module.Journal(book(g)).pending()


def boxes(answers, title="Unfinished Save"):
    return [(kind, m) for kind, t, m in answers.calls if t == title]


class FakeMySQL:
    """Stands in for db_mysql: reachable or not."""

    def __init__(self):
        self.reports, self.away, self.lists = {}, False, 0

    def is_enabled(self):
        return True

    def save_report(self, data):
        if self.away:
            error = OSError("Can't connect to MySQL server on 'localhost'")
            error.errno = 2003
            raise error
        self.reports[data["control_no"]] = data
        return []

    def save_master_lists(self, master_data):
        self.lists += 1

    @staticmethod
    def explain_error(error):
        return str(error)

    @staticmethod
    def is_unreachable(error):
        return getattr(error, "errno", None) == 2003


def test_complete_save_leaves_nothing_on_record(app):
    g, answers = app
    answers.calls.clear()
    fill_form(g, "SO-REC-OK")
    assert g["save_report"]() is True
    assert pending(g) == []
    assert notes(answers) == [] and boxes(answers) == []


def test_failed_incident_file_is_finished_at_the_next_save(app, monkeypatch):
    g, answers = app
    answers.calls.clear()
    control = fill_form(g, "SO-REC-INC", condition="Bad Order")
    g["incident_cards"][0].rows[0].insert(0, "Crate broken on arrival")
    real = fsr_storage.save_incident_data

    def disk_full(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(fsr_storage, "save_incident_data", disk_full)
    assert g["save_report"]() is True

    # told plainly: saved, but one part is missing and will be finished
    (note,) = notes(answers)
    assert "The incident report file could not be saved" in note
    assert "disk full" in note
    assert "finished automatically at the next save or the next start" in note
    (record,) = pending(g)
    assert record["control"] == control
    assert record["steps"]["workbook"] == "done"
    assert record["steps"]["incidents"] == "pending"
    assert fsr_storage.load_incident_data(book(g), control) == []

    # the next save (of another report) finishes it
    monkeypatch.setattr(fsr_storage, "save_incident_data", real)
    answers.calls.clear()
    fill_form(g, "SO-REC-NEXT")
    assert g["save_report"]() is True

    assert pending(g) == []
    assert fsr_storage.load_incident_data(book(g), control)[0]["lines"] == [
        "Crate broken on arrival"]
    ((kind, message),) = boxes(answers)
    assert kind == "showinfo"
    assert control in message and "had not finished" in message
    assert "It was completed now: the incident report file" in message


def test_save_cut_off_before_the_workbook_is_finished_at_start(app):
    """As after a power cut: only the record exists."""
    g, answers = app
    control = fill_form(g, "SO-REC-CUT", condition="Bad Order")
    g["incident_cards"][0].rows[0].insert(0, "Wet cartons")
    data = g["collect_report_data"]()
    stores = journal_module.Stores(book(g))
    journal_module.open_save(journal_module.Journal(book(g)), stores, data,
                             False, False, False)
    g["new_report"](confirm=False)      # the form is gone, as after a restart
    assert control not in [e[0] for e in
                           fsr_storage.list_saved_reports(book(g))]
    answers.calls.clear()

    g["finish_unfinished_saves"]()          # what the start does

    saved = fsr_storage.read_report(book(g), control)
    assert saved["general_information"]["so_number"] == "SO-REC-CUT"
    assert saved["incident_reports"][0]["lines"] == ["Wet cartons"]
    assert pending(g) == []
    ((kind, message),) = boxes(answers)
    assert kind == "showinfo"
    assert "It was completed now: the Excel file" in message
    # running it again does and says nothing
    answers.calls.clear()
    before = book(g).read_bytes()
    assert g["finish_unfinished_saves"]() == []
    assert boxes(answers) == [] and book(g).read_bytes() == before


def test_store_that_still_fails_is_reported_as_not_done(app, monkeypatch):
    g, answers = app
    control = fill_form(g, "SO-REC-STILL", condition="Bad Order")
    g["incident_cards"][0].rows[0].insert(0, "Torn bag")
    real = fsr_storage.save_incident_data

    def disk_full(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(fsr_storage, "save_incident_data", disk_full)
    assert g["save_report"]() is True
    answers.calls.clear()

    g["finish_unfinished_saves"]()

    ((kind, message),) = boxes(answers)
    assert kind == "showwarning"
    assert "the incident report file could still NOT be written" in message
    assert "tried again at the next save or the next start" in message
    assert len(pending(g)) == 1
    monkeypatch.setattr(fsr_storage, "save_incident_data", real)
    g["finish_unfinished_saves"]()
    assert pending(g) == []
    assert fsr_storage.load_incident_data(book(g), control) != []


def test_workbook_in_use_saves_nothing_and_keeps_no_record(app, monkeypatch):
    g, answers = app
    answers.calls.clear()
    control = fill_form(g, "SO-REC-LOCKED")

    def locked(*args, **kwargs):
        raise PermissionError("in use")

    monkeypatch.setattr(fsr_storage, "write_report_to_excel", locked)
    assert g["save_report"]() is False
    assert "File In Use" in [t for kind, t, _ in answers.calls
                             if kind == "showerror"]
    assert pending(g) == []                 # the user was told: not saved
    monkeypatch.undo()
    assert g["save_report"]() is True
    assert fsr_storage.read_report(book(g), control)["control_no"] == control


def test_mysql_not_reachable_is_normal_and_catches_up(app, monkeypatch):
    g, answers = app
    fake = FakeMySQL()
    fake.away = True
    monkeypatch.setitem(live(g), "db_mysql", fake)
    toasts = []
    monkeypatch.setitem(live(g), "notify",
                        lambda message, bootstyle="success":
                        toasts.append((bootstyle, message)))
    answers.calls.clear()
    first = fill_form(g, "SO-REC-OFFLINE-1")

    assert g["save_report"]() is True

    # no error box - but it is said that MySQL was skipped
    assert notes(answers) == [] and boxes(answers) == []
    assert [e for e in answers.calls if e[0] == "showerror"] == []
    (style, toast), = toasts
    assert style == "warning" and first in toast
    assert "on this PC" in toast and "MySQL was not reached" in toast
    (record,) = pending(g)
    assert journal_module.local_complete(record)
    assert [s for s, v in record["steps"].items() if v == "pending"] == [
        "mysql"]
    assert fsr_storage.read_report(book(g), first)["control_no"] == first

    # a second report while still offline: both wait
    second = fill_form(g, "SO-REC-OFFLINE-2")
    assert g["save_report"]() is True
    assert len(pending(g)) == 2 and fake.reports == {}

    # the server is back: the next check sends both, without a message box
    fake.away = False
    toasts.clear()
    answers.calls.clear()
    g["finish_unfinished_saves"](mysql_ok=True)
    assert set(fake.reports) == {first, second}
    assert pending(g) == []
    assert boxes(answers) == [] and notes(answers) == []
    assert toasts == [("success", "MySQL caught up: 2 report(s) saved "
                       "earlier on this PC are now in MySQL")]


def test_other_mysql_errors_are_still_shown(app, monkeypatch):
    g, answers = app
    fake = FakeMySQL()

    def refused(data):
        error = OSError("Access denied for user 'fsr_app'")
        error.errno = 1045
        raise error

    fake.save_report = refused
    monkeypatch.setitem(live(g), "db_mysql", fake)
    answers.calls.clear()
    fill_form(g, "SO-REC-DENIED")
    assert g["save_report"]() is True
    (note,) = notes(answers)
    assert "saved to Excel, but NOT to MySQL" in note
    assert "Access denied" in note
    assert "finished automatically" in note
    monkeypatch.setitem(live(g), "db_mysql", FakeMySQL())
    g["finish_unfinished_saves"](mysql_ok=True)
    assert pending(g) == []


def test_unreadable_record_file_warns_once_and_saving_still_works(app):
    g, answers = app
    path = journal_module.journal_path(book(g))
    original = path.read_bytes()
    path.write_text("{not json", encoding="utf-8")
    try:
        answers.calls.clear()
        control = fill_form(g, "SO-REC-BROKEN")
        assert g["save_report"]() is True
        assert fsr_storage.read_report(book(g), control)[
            "control_no"] == control
        ((kind, message),) = boxes(answers)
        assert kind == "showwarning" and "could not be read" in message
        assert "left as it is" in message
        assert path.read_text(encoding="utf-8") == "{not json"
        fill_form(g, "SO-REC-BROKEN-2")
        assert g["save_report"]() is True
        assert len(boxes(answers)) == 1         # said once
    finally:
        path.write_bytes(original)



# ---------- a price without a currency ----------

def test_a_price_without_a_currency_asks_before_saving(app):
    g, answers = app
    fill_form(g, "SO-NO-CURRENCY-1")
    section = g["item_frames"][0]
    cols = g["ITEM_FORM_HEADERS"]
    g["set_entry"](section.rows[0][cols.index("Total Price")], "6,585")
    g["set_entry"](section.rows[0][cols.index("Currency")], "")
    asked = len(answers.calls)
    answers.yes = False
    try:
        assert g["save_report"]() is False          # "Go back"
    finally:
        answers.yes = True
    question = [c for c in answers.calls[asked:]
                if c[1] == "Price Without a Currency"]
    assert len(question) == 1 and "Item List 1: line 1" in question[0][2]

    g["set_entry"](section.rows[0][cols.index("Currency")], "PHP")
    asked = len(answers.calls)
    assert g["save_report"]() is True
    assert "Price Without a Currency" not in [c[1] for c in
                                              answers.calls[asked:]]
