"""The SQLite store against the workbook, side by side ("twins").

The invented sample data set (84 reports) is written once into a workbook;
a copy of that folder is moved into its database. Then the SAME steps are
done on both - new reports, edits, PO-linked Withdrawal reports, a number
taken in the meantime, a renumbering, incidents, PO_Master - and after
every step:

* every way the program reads reports gives the same result from both
  (fsr_sqlite_migrate.compare_stores: every report field by field, the
  saved lists, search indexes, Last Saved times, Control #s);
* the workbook the database exports holds exactly the rows of the twin
  workbook, sheet by sheet, row by row, cell by cell;
* PO_Master and Withdrawn_Item have the same rows.
"""
import shutil
from datetime import date, datetime

import pytest
from openpyxl import load_workbook

import fsr_paths
import fsr_sqlite_export
import fsr_sqlite_migrate as migrate
import fsr_sqlite_store as sq
import fsr_store
from conftest import ANCHOR
from factories import report
from warehouse import sample_data as sd

WHEN = datetime(2026, 11, 13, 10, 0, 0, 125000)


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    folder = tmp_path_factory.mktemp("twin_source")
    path, _ = sd.generate(folder / "excel", anchor=ANCHOR)
    return path


@pytest.fixture
def twins(generated, tmp_path):
    """(the workbook store, the SQLite store) holding the same reports."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    shutil.copytree(generated.parent, a)
    shutil.copytree(generated.parent, b)
    excel = fsr_store.ExcelStore(a / generated.name)
    result = migrate.migrate(b / generated.name)
    assert result.status == "migrated", result.message
    sql = fsr_store.open_store(b / generated.name)
    assert sql.kind == "sqlite"
    return excel, sql


def same(excel, sql):
    assert migrate.compare_stores(excel, sql) == []
    fsr_sqlite_export.write_export(sql)
    mine = migrate.read_rows(excel.excel_path)
    exported = migrate.read_rows(sql.excel_path)
    for book in (sq.MAIN, sq.BOOK):
        assert exported[book][0] == mine[book][0], book
        for sheet, rows in mine[book][1].items():
            assert exported[book][1][sheet] == rows, (book, sheet)


def receiving(control, qty=10, po="PO-TWIN", so="SO-TWIN"):
    data = report(control, "Receiving", date(2026, 11, 5), "WH-T",
                  [{"qty": qty, "unit": "Crate", "desc": "Twin pump",
                    "po": po, "cargo": "C-T"},
                   {"qty": "1,250.50", "unit": "Kg", "desc": "Twin bar",
                    "po": po}], so=so)
    data["declared_goods"] = [{"description": "Pumps", "quantity": "2",
                               "packaging": "Crates"}]
    data["other_important_remarks"] = ["Sealed"]
    data["findings_and_remarks"] = ["Dent", "Wet corner"]
    return data


def withdrawal(control, ref, qty, po="PO-TWIN"):
    data = report(control, "Withdrawal", date(2026, 11, 6), "WH-T",
                  [{"qty": qty, "unit": "Crate", "desc": "Twin pump",
                    "po": po, "ref": ref}], so="SO-TWIN-W")
    row = data["item_lists"][0]["rows"][0]
    row.update({"PO Line No": "1", "Source Control #": "",
                "Received Quantity": "10"})
    data["other_item_forms"] = {}
    return data


def both(excel, sql, method, *args, compare=True, **kwargs):
    """Do one step on both twins (each with its own copy of the data);
    the results must be the same (`compare`: not for a step that returns
    the path of its own file)."""
    import copy
    one = getattr(excel, method)(*copy.deepcopy(args), **kwargs)
    two = getattr(sql, method)(*copy.deepcopy(args), **kwargs)
    if compare:
        assert one == two, method
    return one


def test_the_moved_data_is_the_same(twins):
    same(*twins)


def test_new_reports_edits_and_a_taken_number(twins):
    excel, sql = twins
    number = excel.next_control_number()
    assert sql.next_control_number() == number
    both(excel, sql, "write_report", receiving(number), False, WHEN)
    same(excel, sql)
    edited = receiving(number, qty=12, so="SO-TWIN-EDITED")
    edited["item_lists"][0]["rows"].pop()          # one line less
    both(excel, sql, "write_report", edited, True, WHEN)
    same(excel, sql)
    # a NEW report with a number that is taken gets the next free one
    result = both(excel, sql, "write_report", receiving(number), False,
                  WHEN)
    assert result["control"] != number
    same(excel, sql)


def test_several_reports_in_one_write_and_all_or_none(twins):
    excel, sql = twins
    items = [(receiving(f"FSR-TWN-202611-{n:04d}", so=f"SO-{n}"), False,
              WHEN) for n in range(1, 6)]
    both(excel, sql, "write_reports", items)
    same(excel, sql)
    bad = receiving("FSR-TWN-202611-0099")
    del bad["general_information"]            # this one cannot be written
    for store in twins:
        with pytest.raises(KeyError):
            store.write_reports([(receiving("FSR-TWN-202611-0098"), False,
                                  WHEN), (bad, False, WHEN)])
    same(excel, sql)
    assert "FSR-TWN-202611-0098" not in sql.control_numbers()


def test_withdrawals_po_lines_and_the_lists(twins):
    excel, sql = twins
    both(excel, sql, "write_report", receiving("FSR-TWN-202611-0001"),
         False, WHEN)
    ref = "RCV-FSR-TWN-202611-0001-1-01"
    assert both(excel, sql, "find_po", "po-twin") == \
        excel.find_po("PO-TWIN")
    both(excel, sql, "write_withdrawal_report",
         withdrawal("FSR-TWN-202611-0002", ref, 3), False, WHEN)
    same(excel, sql)
    first = sql.read_withdrawal_report("FSR-TWN-202611-0002")
    # edit it: one more line, Line IDs kept
    first["item_lists"][0]["rows"].append(dict(
        first["item_lists"][0]["rows"][0], **{"Line ID": "",
                                              "Quantity": "2"}))
    import fsr_withdrawal
    for store in twins:
        with pytest.raises(fsr_withdrawal.WithdrawalError):
            store.write_withdrawal_report(first, True, WHEN)   # twice
    first["item_lists"][0]["rows"][1]["PO Line No"] = ""      # typed line
    both(excel, sql, "write_withdrawal_report", first, True, WHEN)
    same(excel, sql)
    row = {"Receiving Ref": ref, "Received Quantity": "10"}
    assert both(excel, sql, "remaining_quantity", row) == 5    # 10 - 3 - 2
    assert both(excel, sql, "owns_withdrawal", "fsr-twn-202611-0002")
    # too much is refused by both, and nothing is written
    for store in twins:
        with pytest.raises(fsr_withdrawal.WithdrawalError):
            store.write_withdrawal_report(
                withdrawal("FSR-TWN-202611-0003", ref, 6), False, WHEN)
    same(excel, sql)
    for store in twins:
        store.rebuild_item_lists()
    for name in (fsr_paths.PO_MASTER_NAME, fsr_paths.WITHDRAWN_ITEM_NAME):
        rows = [list(load_workbook(store.excel_path.with_name(name))
                     .active.iter_rows(values_only=True)) for store in twins]
        assert rows[0] == rows[1], name


def test_renumber_incidents_and_item_forms(twins):
    excel, sql = twins
    data = receiving("FSR-TWN-202611-0001")
    data["cargo_condition"] = "Bad Order"
    both(excel, sql, "write_report", data, False, WHEN)
    both(excel, sql, "save_incidents", "FSR-TWN-202611-0001", "SO-TWIN",
         [{"vessel": "MV", "lines": ["Dent"]}], compare=False)
    both(excel, sql, "save_item_forms", "FSR-TWN-202611-0001", {},
         compare=False)
    ref = "RCV-FSR-TWN-202611-0001-1-01"
    both(excel, sql, "write_withdrawal_report",
         withdrawal("FSR-TWN-202611-0002", ref, 3), False, WHEN)
    for store in twins:
        touched = store.renumber("FSR-TWN-202611-0001",
                                 "FSR-TWN-202611-0050")
        assert touched["cells"] >= 4
    same(excel, sql)
    assert sql.load_incidents("FSR-TWN-202611-0050")[0]["lines"] == ["Dent"]
    taken = sql.read_withdrawal_report("FSR-TWN-202611-0002")
    assert taken["item_lists"][0]["rows"][0]["Receiving Ref"] == \
        "RCV-FSR-TWN-202611-0050-1-01"


def test_import_master_data_into_both(twins, tmp_path):
    import fsr_import
    import fsr_master_export
    excel, sql = twins
    site = tmp_path / "site"
    site.mkdir()
    site_store = fsr_store.ExcelStore(site / "data.xlsx")
    site_store.write_report(receiving("FSR-SIT-202611-0001"), False, WHEN)
    target = tmp_path / "site.json"
    fsr_master_export.write_export(site / "data.xlsx", target, "site-pc")
    data = fsr_import.read_master_file(target)
    one = excel.import_master_data(data)
    two = sql.import_master_data(data)
    for key in ("added", "updated", "unchanged", "renumbered", "conflicts"):
        assert one[key] == two[key], key
    assert one["added"] == ["FSR-SIT-202611-0001"]
    # the reports themselves match; only the import time differs
    a = excel.read_report("FSR-SIT-202611-0001")
    b = sql.read_report("FSR-SIT-202611-0001")
    assert a == b
    again = sql.import_master_data(data)
    assert again["unchanged"] == ["FSR-SIT-202611-0001"]
    assert sql.read_report("FSR-SIT-202611-0001") == b


def test_a_write_is_one_transaction_and_tells_the_window(twins,
                                                        monkeypatch):
    _, sql = twins
    told = []
    monkeypatch.setattr(sq, "listeners", [told.append])
    before = sql.changes()
    sql.write_report(receiving("FSR-TWN-202611-0001"), False, WHEN)
    assert sql.changes() == before + 1
    assert told == [sql.excel_path]
    told.clear()
    with pytest.raises(KeyError):
        sql.write_reports([(receiving("FSR-TWN-202611-0002"), False, WHEN),
                           ({"control_no": "X"}, False, WHEN)])
    assert told == [] and sql.changes() == before + 1
    assert "FSR-TWN-202611-0002" not in sql.control_numbers()


def test_cell_values_keep_their_kind():
    values = [None, "text", 12, 12.5, True, datetime(2026, 1, 2, 3, 4, 5,
                                                     125000),
              date(2026, 1, 2)]
    assert list(sq.load_row(sq.dump_row(values))) == values
    from decimal import Decimal
    assert sq.load_row(sq.dump_row([Decimal("2"), Decimal("2.5")])) == \
        (2, 2.5)
