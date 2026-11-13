"""A save must not fail with "File In Use" because something - the
program's own dashboards reading in the background, a virus scanner - has
the workbook open for a moment. Found while measuring on 12 November 2026:
right after a save or an import of a workbook with a few hundred reports,
the next one failed because the dashboards were still reading the file."""
import os
import threading
import time
from datetime import date

import pytest

import fsr_storage as s
import fsr_withdrawal
from factories import report


@pytest.fixture
def book(tmp_path):
    path = tmp_path / "Field_Survey_Reports.xlsx"
    s.write_report_to_excel(path, report(
        "FSR-202611-0001", "Receiving", date(2026, 11, 5), "WH",
        [{"qty": 2, "unit": "Crate", "desc": "Pump"}]), False)
    return path


def hold_open(path, seconds, started):
    def work():
        with open(path, "rb"):
            started.set()
            time.sleep(seconds)
    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    started.wait(5)
    return thread


def test_reading_keeps_the_file_open_only_for_a_moment(book, monkeypatch):
    """While openpyxl is busy with the workbook, the file itself is closed:
    replacing it then works."""
    real = s._openpyxl_load_workbook
    replaced = []

    def slow_parse(source, *args, **kwargs):
        other = book.with_name("other.xlsx")
        other.write_bytes(book.read_bytes())
        os.replace(other, book)         # someone saves meanwhile
        replaced.append(True)
        return real(source, *args, **kwargs)

    monkeypatch.setattr(s, "_openpyxl_load_workbook", slow_parse)
    wb = s.load_workbook(book, data_only=True)
    assert replaced == [True] and "Reports" in wb.sheetnames


def test_save_waits_for_a_reader_that_holds_the_file_briefly(book):
    started = threading.Event()
    reader = hold_open(book, 0.8, started)
    result = s.write_report_to_excel(book, report(
        "FSR-202611-0001", "Receiving", date(2026, 11, 5), "WH",
        [{"qty": 3, "unit": "Crate", "desc": "Pump"}], so="SO-AFTER"), True)
    reader.join()
    assert result["updated"]
    assert s.read_report(book, "FSR-202611-0001")[
        "general_information"]["so_number"] == "SO-AFTER"


def test_a_file_that_stays_open_still_fails_as_before(book, monkeypatch):
    """Excel keeps the file open: after about two seconds the save gives up
    with PermissionError ("File In Use") and the workbook is unchanged."""
    monkeypatch.setattr(s, "REPLACE_PAUSE", 0.01)
    before = book.read_bytes()
    started = threading.Event()
    reader = hold_open(book, 3, started)
    with pytest.raises(PermissionError):
        s.write_report_to_excel(book, report(
            "FSR-202611-0001", "Receiving", date(2026, 11, 5), "WH",
            [{"qty": 9, "unit": "Crate", "desc": "Pump"}]), True)
    reader.join()
    assert book.read_bytes() == before
    assert not book.with_name(book.stem + ".saving.tmp").exists()


def test_a_save_while_the_dashboards_read_does_not_fail(book):
    """The situation that was found: a background thread reads every report
    again and again while saves go on."""
    stop = threading.Event()
    errors = []

    def dashboards():
        while not stop.is_set():
            try:
                s.read_all_reports(book)
                fsr_withdrawal.read_all_reports(
                    book.with_name("Withdrawal_Reports.xlsx"))
            except Exception as error:      # noqa - recorded
                errors.append(error)

    thread = threading.Thread(target=dashboards, daemon=True)
    thread.start()
    try:
        for number in range(6):
            s.write_report_to_excel(book, report(
                "FSR-202611-0001", "Receiving", date(2026, 11, 5), "WH",
                [{"qty": number + 1, "unit": "Crate", "desc": "Pump"}],
                so=f"SO-{number}"), True)
    finally:
        stop.set()
        thread.join()
    assert errors == []
    assert s.read_report(book, "FSR-202611-0001")[
        "general_information"]["so_number"] == "SO-5"
