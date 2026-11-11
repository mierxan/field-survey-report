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
