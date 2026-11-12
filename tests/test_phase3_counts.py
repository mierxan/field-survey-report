"""Slowdowns are caught by COUNTING, not by timing (a slow PC must not fail
a test): how often one operation loads and writes each workbook and the
save record. The figures are the ones Phase 3 brought them down to; see
docs/PERFORMANCE_BASELINE.md."""
from datetime import date

import pytest

import fsr_paths
import fsr_save_journal as j
import fsr_storage as s
import fsr_withdrawal
from factories import report


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    (tmp_path / "excel").mkdir()
    (tmp_path / "json").mkdir()
    book = tmp_path / "excel" / "Field_Survey_Reports.xlsx"
    for number in range(1, 6):
        s.write_report_to_excel(book, receiving(f"FSR-MPR-202611-{number:04d}"),
                                False)
    fsr_withdrawal.sync_item_lists(book)    # PO_Master exists, as in use
    return book


def receiving(control, so="SO-1"):
    data = report(control, "Receiving", date(2026, 11, 5), "WH",
                  [{"qty": 4, "unit": "Crate", "desc": "Pump", "po": "PO-7",
                    "ref": f"RCV-{control}-1-01"}], so=so)
    data["other_item_forms"] = {}
    return data


class Counts:
    def __init__(self, monkeypatch, book):
        from openpyxl.reader import excel
        from openpyxl.workbook import workbook
        self.loads, self.writes, self.records = {}, {}, 0
        real_read, real_save = excel.ExcelReader.read, workbook.Workbook.save
        real_json = s.write_json_atomic
        counts = self

        def name_of(value):
            text = str(value or "")
            for word in ("Withdrawal_Reports", "Field_Survey_Reports",
                         "PO_Master", "Withdrawn_Item"):
                if word in text:
                    return word
            return "other"

        def read(reader, *args, **kwargs):
            key = name_of(getattr(reader.archive, "filename", ""))
            counts.loads[key] = counts.loads.get(key, 0) + 1
            return real_read(reader, *args, **kwargs)

        def save(wb, filename, *args, **kwargs):
            key = name_of(filename)
            counts.writes[key] = counts.writes.get(key, 0) + 1
            return real_save(wb, filename, *args, **kwargs)

        def write_json(path, data):
            if str(path) == str(j.journal_path(book)):
                counts.records += 1
            return real_json(path, data)

        monkeypatch.setattr(excel.ExcelReader, "read", read)
        monkeypatch.setattr(workbook.Workbook, "save", save)
        monkeypatch.setattr(s, "write_json_atomic", write_json)


def save(book, data, editing, mysql=False):
    journal, stores = j.Journal(book), j.Stores(book)
    record = j.open_save(journal, stores, data, editing, False, mysql)
    return j.run(journal, record, stores, mysql=False), record


def test_edit_save_counts(env, monkeypatch):
    book = env
    counts = Counts(monkeypatch, book)
    outcome, _ = save(book, receiving("FSR-MPR-202611-0003", so="EDITED"),
                      True)
    assert outcome["failed"] == {}
    # the write, and ONE read to rebuild PO_Master / Withdrawn_Item
    # (it was 1 + 4 before Phase 3)
    assert counts.loads == {"Field_Survey_Reports": 2, "PO_Master": 1}
    assert counts.writes == {"Field_Survey_Reports": 1, "PO_Master": 1,
                             "Withdrawn_Item": 1}
    # the save record: on record, then removed (it was about 7 writes)
    assert counts.records == 2


def test_new_report_save_counts(env, monkeypatch):
    book = env
    counts = Counts(monkeypatch, book)
    save(book, receiving("FSR-MPR-202611-0006", so="NEW"), False)
    assert counts.loads["Field_Survey_Reports"] == 2
    assert counts.writes["Field_Survey_Reports"] == 1
    # a new report is noted once more right after the workbook write
    # (fsr_save_journal: the only way to tell its later states apart)
    assert counts.records == 3


def test_rebuild_reads_each_workbook_once(env, monkeypatch):
    book = env
    counts = Counts(monkeypatch, book)
    fsr_withdrawal.sync_item_lists(book)
    assert counts.loads == {"Field_Survey_Reports": 1, "PO_Master": 1}
    assert counts.writes == {"PO_Master": 1, "Withdrawn_Item": 1}


def test_rebuild_gives_the_same_lists_as_before(env):
    """One read instead of four must not change what the lists hold."""
    book = env
    s.write_report_to_excel(book, report(
        "FSR-MPR-202611-0009", "Withdrawal", date(2026, 11, 6), "WH",
        [{"qty": 1, "unit": "Crate", "desc": "Pump", "po": "PO-7",
          "ref": "RCV-FSR-MPR-202611-0002-1-01"}]), False)
    fsr_withdrawal.sync_item_lists(book)

    def rows(name):
        wb = s.load_workbook(book.with_name(name), data_only=True)
        return [list(r) for r in wb.active.iter_rows(values_only=True)]

    po = rows(fsr_paths.PO_MASTER_NAME)
    withdrawn = rows(fsr_paths.WITHDRAWN_ITEM_NAME)
    by_control = {r[0]: r for r in po[1:]}
    assert len(by_control) == 5
    assert "3" in str(by_control["FSR-MPR-202611-0002"])   # 4 - 1 taken
    assert [r[0] for r in withdrawn[1:]] == ["FSR-MPR-202611-0009"]
