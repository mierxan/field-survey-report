"""PO_Master and Withdrawn_Item rebuilt in the background (Phase 3): one
rebuild for every save waiting for it, a rebuild cut off midway recovered
from the save record, PO_Master open in Excel."""
import threading
from datetime import date

import pytest

import fsr_paths
import fsr_save_journal as j
import fsr_storage as s
import fsr_withdrawal
from factories import report


class Crash(BaseException):
    """The PC loses power: nothing after this line runs."""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    (tmp_path / "excel").mkdir()
    (tmp_path / "json").mkdir()
    return tmp_path / "excel" / "Field_Survey_Reports.xlsx"


def receiving(control, so="SO-1"):
    data = report(control, "Receiving", date(2026, 11, 5), "WH",
                  [{"qty": 4, "unit": "Crate", "desc": "Pump", "po": "PO-7",
                    "ref": f"RCV-{control}-1-01"}], so=so)
    data["other_item_forms"] = {}
    return data


def save_here(book, data, editing=False):
    """Save as the program does now: the lists are left for later."""
    journal, stores = j.Journal(book), j.Stores(book)
    record = j.open_save(journal, stores, data, editing, False, False)
    j.run(journal, record, stores, mysql=False, lists=False)
    return record


def in_po_master(book):
    path = book.with_name(fsr_paths.PO_MASTER_NAME)
    if not path.exists():
        return set()
    wb = s.load_workbook(path, data_only=True)
    return {row[0] for row in wb.active.iter_rows(min_row=2,
                                                 values_only=True) if row[0]}


def rebuild(book):
    return j.rebuild_lists(j.Journal(book), j.Stores(book))


def test_save_leaves_the_lists_for_later(env):
    book = env
    save_here(book, receiving("FSR-MPR-202611-0001"))
    assert in_po_master(book) == set()          # not rebuilt by the save
    (waiting,) = j.waiting_for_lists(j.Journal(book))
    assert waiting["steps"]["item_lists"] == j.PENDING
    assert j.local_complete(waiting) is False

    result = rebuild(book)

    assert result["rebuilt"] and result["error"] is None
    assert in_po_master(book) == {"FSR-MPR-202611-0001"}
    assert j.Journal(book).pending() == []


def test_one_rebuild_for_every_save_waiting(env, monkeypatch):
    book = env
    for number in range(1, 6):
        save_here(book, receiving(f"FSR-MPR-202611-{number:04d}"))
    calls = []
    real = fsr_withdrawal.sync_item_lists
    monkeypatch.setattr(fsr_withdrawal, "sync_item_lists",
                        lambda path: calls.append(path) or real(path))
    result = rebuild(book)
    assert len(calls) == 1 and result["waiting"] == 5
    assert len(in_po_master(book)) == 5
    assert j.Journal(book).pending() == []


def test_a_save_made_during_a_rebuild_waits_for_the_next(env, monkeypatch):
    """The rebuild read the workbook before this save: ticking it off
    would leave it out of PO_Master."""
    book = env
    save_here(book, receiving("FSR-MPR-202611-0001"))
    real = fsr_withdrawal.sync_item_lists

    def meanwhile(path):
        real(path)                              # read and written ...
        save_here(book, receiving("FSR-MPR-202611-0002"))   # ... then this
    monkeypatch.setattr(fsr_withdrawal, "sync_item_lists", meanwhile)
    rebuild(book)
    monkeypatch.setattr(fsr_withdrawal, "sync_item_lists", real)

    (left,) = j.waiting_for_lists(j.Journal(book))
    assert left["control"] == "FSR-MPR-202611-0002"
    assert in_po_master(book) == {"FSR-MPR-202611-0001"}
    rebuild(book)
    assert in_po_master(book) == {"FSR-MPR-202611-0001",
                                  "FSR-MPR-202611-0002"}


def test_po_master_open_in_excel_keeps_the_step_open(env):
    book = env
    save_here(book, receiving("FSR-MPR-202611-0001"))

    def open_in_excel(path):
        raise PermissionError("PO_Master.xlsx is open")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fsr_withdrawal, "sync_item_lists", open_in_excel)
        result = rebuild(book)
    assert isinstance(result["error"], PermissionError)
    (left,) = j.waiting_for_lists(j.Journal(book))
    assert "open" in left["errors"]["item_lists"]
    assert rebuild(book)["rebuilt"]             # Excel closed: next round
    assert j.Journal(book).pending() == []


@pytest.mark.parametrize("where", ["before_writing", "between_the_lists",
                                   "after_both"])
def test_rebuild_cut_off_midway_is_done_again_at_the_next_start(env,
                                                                where):
    book = env
    save_here(book, receiving("FSR-MPR-202611-0001"))
    rebuild(book)
    before = book.with_name(fsr_paths.PO_MASTER_NAME).read_bytes()
    save_here(book, receiving("FSR-MPR-202611-0002"))

    real_write = fsr_withdrawal._write_list
    calls = {"n": 0}

    def cut(path, *args):
        calls["n"] += 1
        if where == "before_writing" or (where == "between_the_lists"
                                         and calls["n"] == 2):
            raise Crash()
        real_write(path, *args)
        if where == "after_both" and calls["n"] == 2:
            raise Crash()               # written, not ticked off
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fsr_withdrawal, "_write_list", cut)
        with pytest.raises(Crash):
            rebuild(book)

    po = book.with_name(fsr_paths.PO_MASTER_NAME)
    if where == "before_writing":
        assert po.read_bytes() == before        # never half written
    (left,) = j.waiting_for_lists(j.Journal(book))       # still on record
    assert left["control"] == "FSR-MPR-202611-0002"
    # the repair at start leaves the lists to the background ...
    j.repair(j.Journal(book), j.Stores(book), mysql=False, lists=False)
    assert len(j.waiting_for_lists(j.Journal(book))) == 1
    # ... which rebuilds them
    assert rebuild(book)["rebuilt"]
    assert in_po_master(book) == {"FSR-MPR-202611-0001",
                                  "FSR-MPR-202611-0002"}
    assert j.Journal(book).pending() == []


def test_rebuild_and_save_at_the_same_time(env):
    """The window saves while the background rebuilds: no error, nothing
    lost, both end up in PO_Master."""
    book = env
    save_here(book, receiving("FSR-MPR-202611-0001"))
    errors = []

    def background():
        try:
            for _ in range(3):
                rebuild(book)
        except Exception as error:      # recorded
            errors.append(error)

    thread = threading.Thread(target=background)
    thread.start()
    for number in range(2, 6):
        save_here(book, receiving(f"FSR-MPR-202611-{number:04d}"))
    thread.join()
    rebuild(book)
    assert errors == []
    assert len(in_po_master(book)) == 5
    assert j.Journal(book).pending() == []
