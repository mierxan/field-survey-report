"""GO_BACK_TO_WORKBOOK.bat: the program started with --database-status /
--go-back-to-workbook answers in plain words, in a report file, without a
window or a sign-in - and only then puts the database aside.

Invented data in temporary folders (FSR_HOME), never the test copy's."""
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

import fsr_paths
import fsr_sqlite_export as export
import fsr_sqlite_migrate as migrate
import fsr_sqlite_store as sq
import fsr_store
from factories import report

ROOT = Path(__file__).resolve().parent.parent
WHEN = datetime(2026, 11, 14, 9, 0, 0)


def receiving(control, so="SO-GB"):
    data = report(control, "Receiving", date(2026, 11, 5), "WH",
                  [{"qty": 2, "unit": "Box", "desc": "Pump"}], so=so)
    data["other_item_forms"] = {}
    return data


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A data folder laid out as the program's (FSR_HOME)."""
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    (tmp_path / "excel").mkdir()
    (tmp_path / "json").mkdir()
    book = tmp_path / "excel" / "Field_Survey_Reports.xlsx"
    fsr_store.ExcelStore(book).write_report(receiving("FSR-GBK-202611-0001"),
                                            False, WHEN)
    return tmp_path, book


def test_the_answers_in_plain_words(home, tmp_path):
    _, book = home
    out = tmp_path / "answer.txt"
    assert migrate.command(migrate.STATUS, book, report=out) == \
        migrate.NOTHING_TO_DO
    assert "kept in the Excel file" in out.read_text(encoding="utf-8")

    assert migrate.migrate(book).status == "migrated"
    store = fsr_store.open_store(book)
    store.write_report(receiving("FSR-GBK-202611-0002", so="SO-SINCE"),
                       False, WHEN)
    assert migrate.command(migrate.STATUS, book, report=out) == migrate.DONE
    text = out.read_text(encoding="utf-8")
    assert "kept in the database" in text and "2 report(s)" in text
    assert "is not up to date yet" in text

    assert migrate.command(migrate.GO_BACK, book, report=out) == migrate.DONE
    text = out.read_text(encoding="utf-8")
    assert "holds every report and is used again" in text
    assert "previous version of the program can be used now" in text
    assert fsr_store.open_store(book).kind == "excel"
    assert "FSR-GBK-202611-0002" in fsr_store.ExcelStore(
        book).control_numbers()


def test_a_changed_excel_file_stops_the_way_back(home, tmp_path):
    _, book = home
    migrate.migrate(book)
    export.write_export(fsr_store.open_store(book))
    fsr_store.ExcelStore(book).write_report(           # edited outside
        receiving("FSR-GBK-202611-0003"), False, WHEN)
    out = tmp_path / "answer.txt"
    assert migrate.command(migrate.STATUS, book, report=out) == \
        migrate.NOT_DONE
    assert "CHANGED outside the program" in out.read_text(encoding="utf-8")
    assert migrate.command(migrate.GO_BACK, book, report=out) == \
        migrate.NOT_DONE
    assert "Nothing was changed" in out.read_text(encoding="utf-8")
    assert sq.is_active(book)


def test_a_problem_is_said_not_shown_as_an_error(home, tmp_path,
                                                 monkeypatch):
    _, book = home
    migrate.migrate(book)

    def broken(*args, **kwargs):
        raise OSError("the disk is full")
    monkeypatch.setattr(migrate, "use_excel_again", broken)
    out = tmp_path / "answer.txt"
    assert migrate.command(migrate.GO_BACK, book, report=out) == \
        migrate.NOT_DONE
    text = out.read_text(encoding="utf-8")
    assert "Nothing was changed" in text and "the disk is full" in text


def run_program(home, *args):
    """The real program, as the .bat starts it (no window may appear: the
    timeout would catch one waiting)."""
    env = dict(os.environ, FSR_HOME=str(home), FSR_SECRET_STORE="memory")
    env.pop("FSR_DEMO", None)
    env.pop("FSR_NO_SQLITE", None)
    return subprocess.run([sys.executable, str(ROOT / "main.py"), *args],
                          env=env, cwd=str(home), capture_output=True,
                          text=True, timeout=120)


def test_the_program_switches_need_no_window_or_sign_in(home, tmp_path):
    data, book = home
    migrate.migrate(book)
    fsr_store.open_store(book).write_report(
        receiving("FSR-GBK-202611-0004", so="SO-PROGRAM"), False, WHEN)
    out = tmp_path / "answer.txt"
    done = run_program(data, "--database-status", "--report", str(out))
    assert done.returncode == 0, done.stderr
    assert "kept in the database" in out.read_text(encoding="utf-8")
    assert sq.is_active(book)                         # only looked
    done = run_program(data, "--go-back-to-workbook", "--report", str(out))
    assert done.returncode == 0, done.stderr
    assert "used again" in out.read_text(encoding="utf-8")
    assert not sq.is_active(book)
    assert "FSR-GBK-202611-0004" in fsr_store.ExcelStore(
        book).control_numbers()
    # nothing was signed in: no account file was made
    assert not (data / "json" / "private" / "users.json").exists()


def test_the_switches_are_read_from_the_command_line():
    import runpy
    names = runpy.run_path(str(ROOT / "field_survey_report.py"),
                           run_name="fsr_switches")
    read = names["database_command"]
    assert read([]) is None
    assert read(["--database-status"]) == ("status", None)
    assert read(["--go-back-to-workbook", "--report", "x.txt"]) == \
        ("go-back", "x.txt")
