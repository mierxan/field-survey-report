"""PO_Master and Withdrawn_Item rebuilt in the background, in the real
program (MySQL off; the rebuild runs in its real thread here)."""
import threading
import time
from pathlib import Path

import pytest

import fsr_paths
import fsr_save_journal
import fsr_storage
import fsr_withdrawal

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_lists_home")
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
def program(app, monkeypatch):
    g, answers = app
    sender = live(g)["lists_sender"]
    monkeypatch.setattr(sender, "inline", False)      # the real thread
    monkeypatch.setitem(live(g), "lists_state", {"warned": False})
    journal = fsr_save_journal.Journal(book(g))
    for record in journal.pending():
        journal.remove(record)
    answers.calls.clear()
    yield g, answers
    pump(g, lambda: sender.idle())
    for record in journal.pending():
        journal.remove(record)


def pump(g, until, limit=30):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        g["window"].update()
        if until():
            g["window"].update()
            return True
        time.sleep(0.02)
    return False


def quiet(g):
    return pump(g, lambda: live(g)["lists_sender"].idle())


def fill(g, so):
    g["app_shell"].show("inspection")
    g["new_report"](confirm=False)
    g["choose_condition"]("Good Order")
    g["set_entry"](g["SO_number_entry"], so)
    g["schedule_entries"]["activity"].set("Receiving")
    g["location_combobox"].set("Lists Warehouse")
    section = g["item_frames"][0]
    cols = g["ITEM_FORM_HEADERS"]
    for header, value in {"Description of Goods": "Valve", "Quantity": "3",
                          "UOM": "PCS", "Packaging": "Box",
                          "PO Number": "4500777"}.items():
        g["set_entry"](section.rows[0][cols.index(header)], value)
    return g["control_entry"].get()


def in_po_master(g):
    path = book(g).with_name(fsr_paths.PO_MASTER_NAME)
    if not path.exists():
        return set()
    wb = fsr_storage.load_workbook(path, data_only=True)
    return {row[0] for row in wb.active.iter_rows(min_row=2,
                                                 values_only=True) if row[0]}


def test_save_does_not_wait_for_the_lists(program, monkeypatch):
    g, answers = program
    gate = threading.Event()
    real = fsr_withdrawal.sync_item_lists

    def slow(path):
        assert gate.wait(20)
        real(path)
    monkeypatch.setattr(fsr_withdrawal, "sync_item_lists", slow)
    control = fill(g, "SO-LISTS-LATER")

    started = time.monotonic()
    assert g["save_report"]() is True
    assert time.monotonic() - started < 15      # did not wait for the gate

    assert fsr_storage.read_report(book(g), control)[
        "general_information"]["so_number"] == "SO-LISTS-LATER"
    assert control not in in_po_master(g)       # not yet
    assert len(fsr_save_journal.waiting_for_lists(
        fsr_save_journal.Journal(book(g)))) == 1
    gate.set()
    assert quiet(g)
    assert control in in_po_master(g)
    assert "PO_Master and Withdrawn_Item are up to date" in \
        live(g)["status_var"].get()
    assert fsr_save_journal.Journal(book(g)).pending() == []


def test_po_master_open_in_excel_is_said_once_and_caught_up(program,
                                                           monkeypatch):
    g, answers = program

    def open_in_excel(path):
        raise PermissionError("PO_Master.xlsx is open")
    monkeypatch.setattr(fsr_withdrawal, "sync_item_lists", open_in_excel)
    first = fill(g, "SO-PO-OPEN-1")
    assert g["save_report"]() is True
    assert quiet(g)
    second = fill(g, "SO-PO-OPEN-2")
    assert g["save_report"]() is True
    assert quiet(g)
    boxes = [c for c in answers.calls if c[1] == "PO_Master - Not Updated"]
    assert len(boxes) == 1                      # once, not after every save
    assert "open in another program" in boxes[0][2]
    assert len(fsr_save_journal.waiting_for_lists(
        fsr_save_journal.Journal(book(g)))) == 2

    monkeypatch.undo()                          # Excel closed
    monkeypatch.setattr(live(g)["lists_sender"], "inline", False)
    third = fill(g, "SO-PO-CLOSED")
    assert g["save_report"]() is True
    assert quiet(g)
    assert {first, second, third} <= in_po_master(g)
    assert fsr_save_journal.Journal(book(g)).pending() == []


def test_lists_left_waiting_are_rebuilt_at_the_next_start(program):
    g, answers = program
    control = fill(g, "SO-LEFT-WAITING")
    journal = fsr_save_journal.Journal(book(g))
    stores = fsr_save_journal.Stores(book(g))
    data = g["collect_report_data"]()
    record = fsr_save_journal.open_save(journal, stores, data, False, False,
                                        False)
    fsr_save_journal.run(journal, record, stores, mysql=False, lists=False)
    assert record["control"] not in in_po_master(g)

    g["finish_unfinished_saves"]()              # what the start does
    assert quiet(g)
    assert record["control"] in in_po_master(g)
    assert fsr_save_journal.Journal(book(g)).pending() == []
    assert control                              # (the form's number)
