"""A quantity is shown exactly as it was typed ("1,250.50", "12.50", "007")
- in the reopened form, the Excel file and the Weekly Summary - while the
stored value stays a number, so calculations and totals use the number.
Reports saved before keep working. Invented data in temporary folders."""
from datetime import date, datetime
from decimal import Decimal

import pytest
from openpyxl import load_workbook

import fsr_paths
import fsr_sqlite_export as export
import fsr_sqlite_migrate as migrate
import fsr_sqlite_store as sq
import fsr_storage as s
import fsr_store
import fsr_withdrawal
from factories import report

WHEN = datetime(2026, 11, 14, 9, 0, 0)


@pytest.mark.parametrize("typed, kind, excel_format", [
    ("1,250.50", s.TypedFloat, "0,000.00"),
    ("12.50", s.TypedFloat, "00.00"),
    ("007", s.TypedInt, "000"),
    ("1,000", s.TypedInt, "0,000"),
    ("-1,250.50", s.TypedFloat, "0,000.00"),
    ("12,345,678.125", s.TypedFloat, "00,000,000.000"),
])
def test_a_typed_quantity_keeps_its_look_and_its_number(typed, kind,
                                                        excel_format):
    number = s.typed_number(typed)
    assert type(number) is kind and s.cell_text(number) == typed
    assert s.typed_format(typed) == excel_format
    assert s.text_in_format(number, excel_format) == typed
    assert number == s.to_number(typed)                  # the same number
    assert sq.load_row(sq.dump_row([number]))[0].typed == typed


@pytest.mark.parametrize("typed", ["12", "1250.5", "0", "12 pcs", "12,50",
                                   "n/a", "", "0.1234567890123456789"])
def test_anything_else_is_stored_as_before(typed):
    number = s.typed_number(typed)
    assert number == s.to_number(typed)
    assert getattr(number, "typed", None) is None


def item(qty, uom="Kg"):
    return {"qty": qty, "unit": "Box", "desc": "Gasket", "po": "PO-T",
            "cargo": "C-1"}


def receiving(control, qty="1,250.50", goods_qty="1,000"):
    data = report(control, "Receiving", date(2026, 11, 5), "WH-T",
                  [item(qty)])
    data["item_lists"][0]["rows"][0]["UOM"] = "Kg"
    data["declared_goods"] = [{"description": "Crates",
                               "quantity": goods_qty, "packaging": "Box"}]
    data["other_item_forms"] = {}
    return data


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", tmp_path / "json")
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", tmp_path / "excel")
    (tmp_path / "excel").mkdir()
    return tmp_path / "excel"


def item_cell(book, sheet="Item List", column="Quantity", row=2):
    ws = load_workbook(book)[sheet]
    headers = [c.value for c in ws[1]]
    return ws.cell(row=row, column=headers.index(column) + 1)


@pytest.mark.parametrize("which", ["workbook", "database"])
def test_the_form_and_the_excel_file_show_it_as_typed(folder, which):
    book = folder / "Field_Survey_Reports.xlsx"
    store = (fsr_store.ExcelStore(book) if which == "workbook"
             else sq.new_store(book))
    store.write_report(receiving("FSR-TYP-202611-0001"), False, WHEN)
    back = store.read_report("FSR-TYP-202611-0001")
    assert back["item_lists"][0]["rows"][0]["Quantity"] == "1,250.50"
    assert back["declared_goods"][0]["quantity"] == "1,000"
    assert store.read_all_reports()[0]["item_lists"][0]["rows"][0][
        "Quantity"] == "1,250.50"
    if which == "database":
        export.write_export(store)
    # the Excel file: a number Excel can add up, shown as typed
    cell = item_cell(book)
    assert cell.value == 1250.5 and isinstance(cell.value, float)
    assert cell.number_format == "0,000.00"
    goods = item_cell(book, "Declared Goods", "Quantity")
    assert goods.value == 1000 and goods.number_format == "0,000"
    # prices keep their money format, as before
    assert item_cell(book, column="Unit Price").number_format in (
        "General", "#,##0.00")


# The Weekly Summary (on screen and exported): tests/test_weekly_gui.py,
# where "1,250.50 Kg" is checked in the table and in the exported sheet.


def test_calculations_and_totals_use_the_number(folder):
    from warehouse.transactions import build_transactions
    book = folder / "Field_Survey_Reports.xlsx"
    store = sq.new_store(book)
    store.write_report(receiving("FSR-TYP-202611-0001"), False, WHEN)
    store.write_report(receiving("FSR-TYP-202611-0002", qty="12.50"), False,
                       WHEN)
    # the PO line of a Withdrawal: what is left, as a number
    (line,) = [x for x in store.find_po("PO-T").lines
               if x.control_no == "FSR-TYP-202611-0001"]
    assert line.remaining_qty == Decimal("1250.50")
    # the dashboards: the quantity of each line and their total
    tx = build_transactions(store.read_all_reports())
    quantities = sorted(x.quantity for t in tx for x in t.lines)
    assert quantities == [12.5, 1250.5] and sum(quantities) == 1263.0
    assert sorted(t.packages for t in tx) == [1000.0, 1000.0]


def test_reports_saved_before_keep_working(folder):
    """A workbook written before: plain numbers in General cells."""
    book = folder / "Field_Survey_Reports.xlsx"
    fsr_store.ExcelStore(book).write_report(
        receiving("FSR-OLD-202611-0001", qty="1250.5", goods_qty="1000"),
        False, WHEN)
    cell = item_cell(book)
    assert cell.number_format == "General"
    assert fsr_store.ExcelStore(book).read_report("FSR-OLD-202611-0001")[
        "item_lists"][0]["rows"][0]["Quantity"] == "1250.5"
    # moved into the database and back out: still the same
    assert migrate.migrate(book).status == "migrated"
    store = fsr_store.open_store(book)
    assert store.read_report("FSR-OLD-202611-0001")["item_lists"][0][
        "rows"][0]["Quantity"] == "1250.5"
    assert item_cell(book).number_format == "General"


def test_a_typed_workbook_moves_into_the_database_as_typed(folder):
    book = folder / "Field_Survey_Reports.xlsx"
    fsr_store.ExcelStore(book).write_report(
        receiving("FSR-TYP-202611-0001"), False, WHEN)
    assert migrate.migrate(book).status == "migrated"
    store = fsr_store.open_store(book)
    assert store.kind == "sqlite"
    row = store.read_report("FSR-TYP-202611-0001")["item_lists"][0][
        "rows"][0]
    assert row["Quantity"] == "1,250.50"
    assert item_cell(book).number_format == "0,000.00"     # the export


def test_an_edited_quantity_loses_an_old_display_format(folder):
    book = folder / "Field_Survey_Reports.xlsx"
    store = fsr_store.ExcelStore(book)
    store.write_report(receiving("FSR-TYP-202611-0001"), False, WHEN)
    store.write_report(receiving("FSR-TYP-202611-0001", qty="12"), True,
                       WHEN)
    cell = item_cell(book)
    assert cell.value == 12 and cell.number_format == "General"
    assert store.read_report("FSR-TYP-202611-0001")["item_lists"][0][
        "rows"][0]["Quantity"] == "12"


def test_the_declared_goods_of_a_withdrawal_report_too(folder):
    book = folder / "Field_Survey_Reports.xlsx"
    store = sq.new_store(book)
    store.write_report(receiving("FSR-TYP-202611-0001", qty="10"), False,
                       WHEN)
    taken = report("FSR-TYP-202611-0002", "Withdrawal", date(2026, 11, 6),
                   "WH-T", [{"qty": 1, "unit": "Box", "desc": "Gasket",
                             "po": "PO-T",
                             "ref": "RCV-FSR-TYP-202611-0001-1-01"}])
    taken["item_lists"][0]["rows"][0].update(
        {fsr_withdrawal.LINE_NO_HEADER: "1",
         fsr_withdrawal.RECEIVED_HEADER: "10"})
    taken["declared_goods"] = [{"description": "Crates", "quantity": "1,000",
                                "packaging": "Box"}]
    taken["other_item_forms"] = {}
    store.write_withdrawal_report(taken, False, WHEN)
    back = store.read_withdrawal_report("FSR-TYP-202611-0002")
    assert back["declared_goods"][0]["quantity"] == "1,000"
