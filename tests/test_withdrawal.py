"""PO-linked Withdrawal: PO list, quantity rules, separate storage, control
numbers, stock and MySQL. No widgets. Every file is in a temporary folder, and
the PO lists are synthetic test fixtures, not real PO data."""

import hashlib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

import db_mysql
import fsr_import
import fsr_paths
import fsr_storage as s
import fsr_withdrawal as wd
from factories import rec, report, wdr
from test_db_mysql import BASE, FakeConnection, item_inserts
from warehouse import store

MAIN = "Field_Survey_Reports.xlsx"
PO = "4500001"
HEADERS = ["Control #", "Description", "PO", "Packaging", "Quantity",
           "Dimension", "Weight", "Unit Price", "Total Price", "Findings"]
LINES = [
    # two lines share a description on purpose
    ("OLD-1", "Pump", "4500001", "Crate", "100 pcs", "1x1x1 cm", "50 kg",
     "JPY 433,000", "JPY 43,300,000", "Good Order"),
    ("OLD-1", "Pump", "4500001", "Crate", "7 pcs", "2x2x2 cm", "'",
     "JPY 10.50", "JPY 73.50", "Good Order"),
    ("OLD-2", "Cable", "4500001", "Roll", "12.5 m", "n/a", "n/a",
     "n/a", "n/a", "Good Order"),
    ("OLD-3", "Valve", "4500002", "Box", "3 set", "n/a", "n/a",
     "USD 5", "USD 15", "Bad Order"),
]


def po_list(folder, lines=LINES, activity="Receiving"):
    """The main workbook of `folder`, holding these lines as saved reports."""
    path = Path(folder) / MAIN
    path.parent.mkdir(parents=True, exist_ok=True)
    by_control = {}
    for line in lines:
        by_control.setdefault(line[0], []).append(line)
    for control, group in by_control.items():
        data = report(control, activity, date(2026, 1, 5))
        rows = []
        for _, desc, po, pack, qty, dim, weight, unit, total, _ in group:
            row = {h: "" for h in s.ITEM_LINE_HEADERS}
            row.update({"Description of Goods": desc, "PO Number": str(po),
                        "Packaging": pack, "Quantity": qty, "Dimensions": dim,
                        "Weights": weight, "Unit Price": unit,
                        "Total Price": total})
            rows.append(row)
        data["item_lists"][0]["rows"] = rows
        s.write_report_to_excel(path, data, True)
    return path


def add_line(rows, line):
    rows.append(wd.new_row(line))


def bad_line(po="P1", quantity="1 pcs"):
    return ("C", "X", po, "", quantity, "", "", "", "", "")


def linked_report(tmp_path, control="FSR-209901-0001", picks=(("4500001", "1"),),
                  quantities=None):
    path = po_list(tmp_path / "source")
    rows = []
    for po, number in picks:
        line = next(l for l in wd.find_po(path, po).lines if l.line_no == number)
        add_line(rows, line)
    for row, quantity in zip(rows, quantities or []):
        wd.set_quantity(row, Decimal(quantity))
    data = report(control, "Withdrawal", date(2026, 10, 5))
    data["item_form"] = s.ITEM_FORM_DEFAULT
    data["item_lists"] = [{"name": "Item List 1", "rows": rows}]
    data["declared_goods"] = [{"description": "Pump crate", "quantity": "2",
                               "packaging": "Crate"}]
    data["other_important_remarks"] = ["Other remark"]
    data["findings_and_remarks"] = ["Finding one"]
    return data


def books(tmp_path):
    return tmp_path / MAIN, tmp_path / fsr_paths.WITHDRAWAL_WORKBOOK_NAME


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------- the PO list ----------

def test_valid_po_lists_all_its_lines_read_only(tmp_path):
    path = po_list(tmp_path)
    before = sha(path)
    found = wd.find_po(path, " 4500001 ")
    assert [(l.line_no, l.description, l.received_qty, l.uom, l.control_no,
             l.packaging) for l in found.lines] == [
        ("1", "Pump", Decimal("100"), "pcs", "OLD-1", "Crate"),
        ("2", "Pump", Decimal("7"), "pcs", "OLD-1", "Crate"),
        ("3", "Cable", Decimal("12.5"), "m", "OLD-2", "Roll")]
    assert sha(path) == before


def test_unknown_po_finds_nothing_and_missing_file_says_so(tmp_path):
    found = wd.find_po(po_list(tmp_path), "999")
    assert (found.lines, found.unreadable, found.shared) == ([], 0, 0)
    with pytest.raises(wd.PoSourceMissing):
        wd.find_po(tmp_path / "none" / MAIN, PO)


@pytest.mark.parametrize("text", ["", "n/a", "N/A", "Consolidated",
                                  "COnsolidated", "Consolidated PO",
                                  "Please see 2nd page for details", "-"])
def test_placeholder_po_values_are_not_usable(text):
    assert not wd.is_usable_po(text)


@pytest.mark.parametrize("quantity", ["n/a", "", "0 pcs", "-1 pcs", "many",
                                      "2 pkgs & 3 box"])
def test_unreadable_quantity_is_left_out_and_counted(tmp_path, quantity):
    path = po_list(tmp_path, [bad_line(quantity=quantity), bad_line()])
    found = wd.find_po(path, "P1")
    assert found.unreadable == 1
    # the good line keeps its place in the PO
    assert [l.line_no for l in found.lines] == ["2"]


def test_a_cell_with_several_pos_is_not_tied_to_any_of_them(tmp_path):
    path = po_list(tmp_path, [bad_line("1001 / 1002"), bad_line("1001/1003"),
                              bad_line("10010")])
    found = wd.find_po(path, "1001")
    assert (found.lines, found.shared) == ([], 2)


def test_repeated_rows_of_a_po_are_separate_lines(tmp_path):
    path = po_list(tmp_path, [bad_line(), bad_line()])
    assert [l.line_no for l in wd.find_po(path, "P1").lines] == ["1", "2"]


def test_numeric_po_cell_is_found_as_text(tmp_path):
    path = po_list(tmp_path, [bad_line(1001235525)])
    assert len(wd.find_po(path, "1001235525").lines) == 1


def test_a_workbook_of_another_layout_is_reported(tmp_path):
    path = tmp_path / MAIN
    wb = Workbook()
    wb.active.title = "Reports"
    wb.active.append(["something", "else"])
    wb.save(path)
    with pytest.raises(wd.PoSourceError):
        wd.find_po(path, "P1")


def test_a_file_that_is_not_a_workbook_is_reported(tmp_path):
    path = tmp_path / MAIN
    path.write_text("not excel")
    with pytest.raises(wd.PoSourceError):
        wd.find_po(path, "P1")


def test_withdrawal_reports_are_not_a_source_of_lines(tmp_path):
    path = po_list(tmp_path, [bad_line("P9")], activity="Withdrawal")
    assert wd.find_po(path, "P9").lines == []


def test_line_without_a_po_uses_the_po_of_its_report(tmp_path):
    path = tmp_path / MAIN
    data = rec("OLD-9", date(2026, 1, 5), "", 5)
    data["documents_used"]["po_number"] = "H-77"
    s.write_report_to_excel(path, data, True)
    assert len(wd.find_po(path, "H-77").lines) == 1


def test_new_receiving_report_can_be_picked_at_once(tmp_path):
    path = po_list(tmp_path, [bad_line()])
    assert len(wd.find_po(path, "P1").lines) == 1
    s.write_report_to_excel(
        path, rec("FSR-209901-0005", date(2026, 1, 6), "", 5, po="P1"), True)
    assert len(wd.find_po(path, "P1").lines) == 2


def test_line_carries_its_receiving_ref_and_cargo_id(tmp_path):
    path = tmp_path / MAIN
    s.write_report_to_excel(
        path, rec("FSR-209901-0005", date(2026, 1, 6), "CID", 5, po="P1"), True)
    line = wd.find_po(path, "P1").lines[0]
    assert (line.receiving_ref, line.cargo_id) == ("RCV-FSR-209901-0005-1-01", "CID")


@pytest.mark.parametrize("text, expected", [
    ("2 pkgs", (Decimal("2"), "pkgs")), ("1,000 kg", (Decimal("1000"), "kg")),
    ("12", (Decimal("12"), "")), ("12.5 m", (Decimal("12.5"), "m")),
    ("n/a", (None, "")), ("", (None, "")), ("12.5", (Decimal("12.5"), "")),
    ("0.3", (Decimal("0.3"), "")), ("0", (None, "")),
])
def test_received_quantity_is_split(text, expected):
    assert wd.split_received(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("JPY 433,000", ("433,000", "JPY")), ("jpy 460,000.-", ("460,000", "JPY")),
    ("n/a", ("n/a", "")), ("", ("", "")), ("5.00", ("5.00", "")),
])
def test_price_is_split(text, expected):
    assert wd.split_price(text) == expected


# ---------- rows and quantities ----------

def test_row_comes_from_its_own_line_when_description_repeats(tmp_path):
    data = linked_report(tmp_path, picks=[("4500001", "2")])
    row = data["item_lists"][0]["rows"][0]
    assert (row["PO Number"], row[wd.LINE_NO_HEADER]) == ("4500001", "2")
    assert (row[wd.RECEIVED_HEADER], row["Quantity"]) == ("7", "7")
    assert (row["Dimensions"], row["Currency"], row["Unit Price"]) == \
        ("2x2x2 cm", "JPY", "10.50")
    assert row["Receiving Ref"] == "RCV-OLD-1-1-02"
    assert row[wd.SOURCE_CONTROL_HEADER] == "OLD-1"
    assert row["Weights"] == ""         # a ditto mark is not a weight
    assert row["Findings"] == ""        # for the withdrawal to fill in


def test_partial_quantity_recalculates_total_and_clears_weight(tmp_path):
    data = linked_report(tmp_path)
    row = data["item_lists"][0]["rows"][0]
    assert (row["Total Price"], row["Weights"]) == ("43,300,000.00", "50 kg")
    wd.set_quantity(row, Decimal("40"))
    assert (row["Quantity"], row["Total Price"], row["Weights"]) == \
        ("40", "17,320,000.00", "")
    assert row[wd.RECEIVED_HEADER] == "100"


def test_same_line_number_on_another_po_is_another_line(tmp_path):
    path = po_list(tmp_path)
    first = wd.row_key(wd.new_row(wd.find_po(path, "4500001").lines[0]))
    assert first != wd.row_key(wd.new_row(wd.find_po(path, "4500002").lines[0]))


@pytest.mark.parametrize("text, uom, received, expected", [
    ("40", "PCS", "100", "40"),
    ("100", "PCS", "100", "100"),
    ("1,000", "PCS", "1000", "1000"),
    ("2.5", "M", "12.5", "2.5"),
    ("0.1", "KG", "0.3", "0.1"),
    (".5", "kgs", "1", "0.5"),
    ("3.0", "PCS", "5", "3"),
])
def test_valid_quantities(text, uom, received, expected):
    assert wd.format_quantity(
        wd.validate_quantity(text, uom, received)) == expected


@pytest.mark.parametrize("text, uom, received, message", [
    ("0", "PCS", "5", "greater than 0"),
    ("-1", "PCS", "5", "greater than 0"),
    ("abc", "PCS", "5", "not a number"),
    ("", "PCS", "5", "not a number"),
    ("1e2", "PCS", "500", "not a number"),
    ("NaN", "M", "5", "not a number"),
    ("6", "PCS", "5", "more than"),
    ("12.51", "M", "12.5", "more than"),
    ("1.5", "PCS", "5", "whole number"),
    ("1.5", "FURLONG", "5", "whole number"),
    ("1.5", "", "5", "whole number"),
])
def test_invalid_quantities(text, uom, received, message):
    with pytest.raises(wd.WithdrawalError, match=message):
        wd.validate_quantity(text, uom, received)


def test_decimal_limit_has_no_float_error():
    # 0.1 + 0.2 style rounding must not let this through or block it
    assert wd.validate_quantity("0.3", "KG", "0.3") == Decimal("0.3")
    with pytest.raises(wd.WithdrawalError):
        wd.validate_quantity("0.30000000000000001", "KG", "0.3")


# ---------- separate storage ----------

def test_save_writes_header_and_lines_and_read_restores_them(tmp_path):
    main, book = books(tmp_path)
    data = linked_report(tmp_path, picks=[("4500001", "1"), ("4500001", "3")],
                         quantities=["40", "2.5"])
    result = wd.write_withdrawal_report(book, data, False, main)
    assert (result["control"], result["updated"], result["items"]) == \
        ("FSR-209901-0001", False, 2)
    assert not main.exists()        # the main workbook is not even created

    wb = load_workbook(book)
    assert wb.sheetnames == ["Withdrawal Reports", "Withdrawal Lines",
                             "Declared Goods", "Remarks"]
    assert set(wb["Withdrawal Lines"].tables) == {"WithdrawalLinesTable"}
    headers = [c.value for c in wb["Withdrawal Lines"][1]]
    for name in ("Control #", "Line ID", "PO Number", "PO Line No",
                 "Description of Goods", "UOM", "Received Quantity", "Source Control #",
                 "Withdrawal Quantity"):
        assert name in headers
    rows = [dict(zip(headers, r)) for r in wb["Withdrawal Lines"].iter_rows(
        min_row=2, values_only=True)]
    assert [(r["Control #"], r["PO Line No"], r["Received Quantity"],
             r["Withdrawal Quantity"], r["Line ID"]) for r in rows] == [
        ("FSR-209901-0001", "1", 100, 40, "FSR-209901-0001-L0001"),
        ("FSR-209901-0001", "3", 12.5, 2.5, "FSR-209901-0001-L0002")]

    back = wd.read_report(book, "FSR-209901-0001")
    assert back["entry_source"] == wd.ENTRY_PO_LINKED
    assert back["item_form"] == s.ITEM_FORM_DEFAULT
    assert back["declared_goods"][0]["description"] == "Pump crate"
    assert back["other_important_remarks"] == ["Other remark"]
    assert back["findings_and_remarks"] == ["Finding one"]
    assert [(r["PO Number"], r[wd.LINE_NO_HEADER], r[wd.SOURCE_CONTROL_HEADER],
             r["Description of Goods"], r[wd.RECEIVED_HEADER], r["Quantity"],
             r["UOM"]) for r in back["item_lists"][0]["rows"]] == [
        ("4500001", "1", "OLD-1", "Pump", "100", "40", "pcs"),
        ("4500001", "3", "OLD-2", "Cable", "12.5", "2.5", "m")]


def test_typed_line_beside_taken_lines_is_saved_without_a_limit(tmp_path):
    main, book = books(tmp_path)
    data = linked_report(tmp_path)
    typed = {h: "" for h in s.ITEM_LINE_HEADERS}
    typed.update({"Description of Goods": "Typed", "Quantity": "999",
                  "UOM": "PCS"})
    data["item_lists"][0]["rows"].append(typed)
    wd.write_withdrawal_report(book, data, False, main)
    wd.write_withdrawal_report(book, data, True, main)     # no duplicates
    rows = wd.read_report(book, data["control_no"])["item_lists"][0]["rows"]
    assert [(r["Description of Goods"], r["Quantity"], r[wd.RECEIVED_HEADER])
            for r in rows] == [("Pump", "100", "100"), ("Typed", "999", "")]


def test_lines_stay_in_their_item_lists(tmp_path):
    main, book = books(tmp_path)
    data = linked_report(tmp_path, picks=[("4500001", "1"), ("4500001", "2")])
    first, second = data["item_lists"][0]["rows"]
    data["item_lists"] = [{"name": "Item List 1", "rows": [first]},
                          {"name": "Item List 2", "rows": [second]}]
    wd.write_withdrawal_report(book, data, False, main)
    back = wd.read_report(book, data["control_no"])["item_lists"]
    assert [[r[wd.LINE_NO_HEADER] for r in section["rows"]]
            for section in back] == [["1"], ["2"]]
    assert back[1]["rows"][0][wd.RECEIVED_HEADER] == "7"


def test_po_source_is_unchanged_by_select_edit_and_save(tmp_path):
    main, book = books(tmp_path)
    data = linked_report(tmp_path, quantities=["1"])
    source = tmp_path / "source" / MAIN
    before = sha(source)
    wd.write_withdrawal_report(book, data, False, main)
    wd.write_withdrawal_report(book, data, True, main)
    assert sha(source) == before
    assert wd.find_po(source, PO).lines[0].received_qty == 100


def test_edit_updates_in_place_with_stable_line_ids(tmp_path):
    main, book = books(tmp_path)
    data = linked_report(tmp_path, picks=[("4500001", "1"), ("4500001", "2")])
    wd.write_withdrawal_report(book, data, False, main)
    first, second = data["item_lists"][0]["rows"]
    second_id = second[wd.LINE_ID_HEADER]

    # remove line 10, change line 20, add line 30
    wd.set_quantity(second, Decimal("3"))
    data["item_lists"][0]["rows"] = [second]
    add_line(data["item_lists"][0]["rows"],
                wd.find_po(tmp_path / "source" / MAIN, PO).lines[2])
    assert wd.write_withdrawal_report(book, data, True, main)["updated"] is True

    assert len(wd.list_reports(book)) == 1
    rows = wd.read_report(book, data["control_no"])["item_lists"][0]["rows"]
    assert [(r[wd.LINE_ID_HEADER], r["Quantity"]) for r in rows] == [
        (second_id, "3"), ("FSR-209901-0001-L0003", "12.5")]

    wd.write_withdrawal_report(book, data, True, main)     # again: no duplicates
    assert len(wd.read_report(book, data["control_no"])["item_lists"][0]["rows"]) == 2
    assert load_workbook(book)["Withdrawal Lines"].max_row == 3


@pytest.mark.parametrize("change, message", [
    (lambda rows: rows[0].update(Quantity="999"), "more than"),
    (lambda rows: rows.append(dict(rows[0])), "twice"),
    (lambda rows: rows.clear(), "at least one"),
])
def test_save_refuses_rows_that_break_a_rule_and_writes_nothing(
        tmp_path, change, message):
    main, book = books(tmp_path)
    data = linked_report(tmp_path)
    change(data["item_lists"][0]["rows"])
    with pytest.raises(wd.WithdrawalError, match=message):
        wd.write_withdrawal_report(book, data, False, main)
    assert not book.exists()


def test_invalid_existing_workbook_is_not_overwritten(tmp_path):
    main, book = books(tmp_path)
    wb = Workbook()
    wb.active.append(["something", "else"])
    wb.save(book)
    before = sha(book)
    with pytest.raises(wd.WithdrawalWorkbookError, match="left as it is"):
        wd.write_withdrawal_report(book, linked_report(tmp_path), False, main)
    with pytest.raises(wd.WithdrawalWorkbookError):
        wd.read_all_reports(book)
    assert sha(book) == before

    book.write_text("not excel")
    with pytest.raises(wd.WithdrawalWorkbookError):
        wd.write_withdrawal_report(book, linked_report(tmp_path), False, main)
    assert book.read_text() == "not excel"


def test_locked_workbook_loses_nothing_and_leaves_no_temp_file(
        tmp_path, monkeypatch):
    main, book = books(tmp_path)
    data = linked_report(tmp_path)
    wd.write_withdrawal_report(book, data, False, main)
    before = sha(book)

    def locked(*_):
        raise PermissionError("in use")
    monkeypatch.setattr(wd.os, "replace", locked)
    data["item_lists"][0]["rows"][0]["Quantity"] = "5"
    with pytest.raises(PermissionError):
        wd.write_withdrawal_report(book, data, True, main)
    assert sha(book) == before
    assert data["item_lists"][0]["rows"][0]["Quantity"] == "5"
    assert [p.name for p in tmp_path.iterdir() if "saving" in p.name] == []


def test_withdrawal_save_leaves_main_workbook_byte_for_byte(tmp_path):
    main, book = books(tmp_path)
    s.write_report_to_excel(main, rec("FSR-209901-0009", date(2026, 1, 1), "C", 5),
                            True)
    before = sha(main)
    wd.write_withdrawal_report(book, linked_report(tmp_path), False, main)
    assert sha(main) == before


def test_main_save_leaves_withdrawal_workbook_byte_for_byte(tmp_path):
    main, book = books(tmp_path)
    wd.write_withdrawal_report(book, linked_report(tmp_path), False, main)
    before = sha(book)
    s.write_report_to_excel(main, rec("FSR-209901-0009", date(2026, 1, 1), "C", 5),
                            True)
    s.delete_reports_from_excel(main, ["FSR-209901-0009", "FSR-209901-0001"])
    assert sha(book) == before
    assert len(wd.list_reports(book)) == 1


def test_search_index_covers_po_and_description(tmp_path):
    main, book = books(tmp_path)
    wd.write_withdrawal_report(book, linked_report(tmp_path), False, main)
    item = wd.search_index(book)["FSR-209901-0001"]
    assert "4500001" in item["po"]
    assert "Pump" in item["description"]


# ---------- what is left of a line ----------

def picked(main, po, control, quantity):
    rows = [wd.new_row(wd.find_po(main, po).lines[0])]
    wd.set_quantity(rows[0], Decimal(quantity))
    data = report(control, "Withdrawal", date(2026, 10, 5))
    data["item_lists"] = [{"name": "Item List 1", "rows": rows}]
    return data


def receiving(main, quantity=23):
    s.write_report_to_excel(
        main, rec("FSR-209901-0001", date(2026, 10, 1), "", quantity, po="P1"),
        True)


def test_partial_withdrawal_leaves_the_rest_to_withdraw(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    before = sha(main)
    wd.write_withdrawal_report(
        book, picked(main, "P1", "FSR-209901-0002", "10"), False, main)
    line = wd.find_po(main, "P1").lines[0]
    assert (line.received_qty, line.remaining_qty) == (23, 13)
    # the new report starts at what is left
    assert wd.new_row(line)["Quantity"] == "13"
    # the Receiving record itself is not changed
    assert sha(main) == before
    assert s.read_report(main, "FSR-209901-0001")["item_lists"][0]["rows"][0][
        "Quantity"] == "23"


def test_next_report_cannot_take_more_than_is_left(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    wd.write_withdrawal_report(
        book, picked(main, "P1", "FSR-209901-0002", "10"), False, main)
    data = picked(main, "P1", "FSR-209901-0003", "13")
    wd.set_quantity(data["item_lists"][0]["rows"][0], Decimal("14"))
    with pytest.raises(wd.WithdrawalError, match="13 remaining"):
        wd.write_withdrawal_report(book, data, False, main)
    wd.set_quantity(data["item_lists"][0]["rows"][0], Decimal("13"))
    wd.write_withdrawal_report(book, data, False, main)


def test_fully_withdrawn_line_is_no_longer_offered(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    wd.write_withdrawal_report(
        book, picked(main, "P1", "FSR-209901-0002", "23"), False, main)
    found = wd.find_po(main, "P1")
    assert (found.lines, found.finished) == ([], 1)


def test_editing_a_report_does_not_count_its_own_quantity(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    data = picked(main, "P1", "FSR-209901-0002", "10")
    wd.write_withdrawal_report(book, data, False, main)
    assert wd.remaining_quantity(
        main, data["item_lists"][0]["rows"][0], "FSR-209901-0002") == 23
    wd.set_quantity(data["item_lists"][0]["rows"][0], Decimal("23"))
    wd.write_withdrawal_report(book, data, True, main)
    assert wd.find_po(main, "P1").finished == 1


def test_lowering_a_saved_withdrawal_gives_the_quantity_back(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    data = picked(main, "P1", "FSR-209901-0002", "20")
    wd.write_withdrawal_report(book, data, False, main)
    wd.set_quantity(data["item_lists"][0]["rows"][0], Decimal("5"))
    wd.write_withdrawal_report(book, data, True, main)
    assert wd.find_po(main, "P1").lines[0].remaining_qty == 18


def test_manual_withdrawal_naming_the_batch_counts_too(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    s.write_report_to_excel(main, wdr(
        "FSR-209901-0005", date(2026, 10, 3), "", 3,
        ref="RCV-FSR-209901-0001-1-01"), True)
    assert wd.find_po(main, "P1").lines[0].remaining_qty == 20


def test_each_batch_of_a_po_has_its_own_remaining(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    s.write_report_to_excel(
        main, rec("FSR-209901-0006", date(2026, 10, 2), "", 9, po="P1"), True)
    wd.write_withdrawal_report(
        book, picked(main, "P1", "FSR-209901-0007", "10"), False, main)
    assert [l.remaining_qty for l in wd.find_po(main, "P1").lines] == [13, 9]


def test_reading_what_is_left_changes_no_workbook(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    wd.write_withdrawal_report(
        book, picked(main, "P1", "FSR-209901-0002", "10"), False, main)
    before = sha(main), sha(book)
    wd.find_po(main, "P1")
    assert (sha(main), sha(book)) == before


def test_decimals_remain_exact(tmp_path):
    main, book = books(tmp_path)
    data = rec("FSR-209901-0001", date(2026, 10, 1), "", 0.3, po="P1")
    data["item_lists"][0]["rows"][0]["UOM"] = "kg"
    s.write_report_to_excel(main, data, True)
    wd.write_withdrawal_report(
        book, picked(main, "P1", "FSR-209901-0002", "0.1"), False, main)
    wd.write_withdrawal_report(
        book, picked(main, "P1", "FSR-209901-0003", "0.1"), False, main)
    assert wd.find_po(main, "P1").lines[0].remaining_qty == Decimal("0.1")


# ---------- PO_Master and Withdrawn_Item ----------

def sheet_rows(path):
    return list(load_workbook(path).worksheets[0].iter_rows(values_only=True))


def lists(tmp_path):
    return tmp_path / fsr_paths.PO_MASTER_NAME, \
        tmp_path / fsr_paths.WITHDRAWN_ITEM_NAME


def test_partial_lowers_po_master_and_is_listed_as_withdrawn(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    wd.write_withdrawal_report(
        book, picked(main, "P1", "FSR-209901-0002", "10"), False, main)
    wd.sync_item_lists(main)
    master, withdrawn = lists(tmp_path)
    head, row = sheet_rows(master)
    assert list(head) == [h for h, _ in wd.LIST_COLUMNS]
    assert (row[0], row[2], row[4]) == ("FSR-209901-0001", "P1", "13")
    head, row = sheet_rows(withdrawn)
    assert list(head) == [h for h, _ in wd.LIST_COLUMNS] + ["Date Withdrawn"]
    assert (row[0], row[2], row[4]) == ("FSR-209901-0002", "P1", "10")
    assert row[-1] == datetime(2026, 10, 5)


def test_fully_withdrawn_line_moves_out_of_po_master(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    s.write_report_to_excel(
        main, rec("FSR-209901-0006", date(2026, 10, 2), "", 9, po="P2"), True)
    wd.write_withdrawal_report(
        book, picked(main, "P1", "FSR-209901-0002", "23"), False, main)
    wd.sync_item_lists(main)
    master, withdrawn = lists(tmp_path)
    assert [r[2] for r in sheet_rows(master)[1:]] == ["P2"]
    assert [(r[2], r[4]) for r in sheet_rows(withdrawn)[1:]] == [("P1", "23")]


def test_editing_a_withdrawal_corrects_both_lists(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    data = picked(main, "P1", "FSR-209901-0002", "23")
    wd.write_withdrawal_report(book, data, False, main)
    wd.sync_item_lists(main)
    wd.set_quantity(data["item_lists"][0]["rows"][0], Decimal("3"))
    wd.write_withdrawal_report(book, data, True, main)
    wd.sync_item_lists(main)
    wd.sync_item_lists(main)        # running it twice changes nothing
    master, withdrawn = lists(tmp_path)
    assert [r[4] for r in sheet_rows(master)[1:]] == ["20"]
    assert [r[4] for r in sheet_rows(withdrawn)[1:]] == ["3"]


def test_rows_of_reports_not_imported_yet_stay_in_po_master(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    master, _ = lists(tmp_path)
    old = ["OLD-1", "Pump", "4500", "Crate", "2 pkgs", "n/a", "n/a",
           "JPY 5", "JPY 10", "Good Order"]
    wd._write_list(master, wd.LIST_SHEET, wd.LIST_COLUMNS, [old])
    wd.sync_item_lists(main)
    rows = sheet_rows(master)[1:]
    assert list(rows[0]) == old
    assert rows[1][0] == "FSR-209901-0001"


def test_po_master_of_another_layout_is_left_alone(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    master, _ = lists(tmp_path)
    wb = Workbook()
    wb.active.append(["something", "else"])
    wb.save(master)
    before = sha(master)
    with pytest.raises(wd.WithdrawalWorkbookError):
        wd.sync_item_lists(main)
    assert sha(master) == before


def test_syncing_changes_neither_report_workbook(tmp_path):
    main, book = books(tmp_path)
    receiving(main)
    wd.write_withdrawal_report(
        book, picked(main, "P1", "FSR-209901-0002", "10"), False, main)
    before = sha(main), sha(book)
    wd.sync_item_lists(main)
    assert (sha(main), sha(book)) == before


def test_partial_total_price_follows_what_remains(tmp_path):
    main, book = books(tmp_path)
    s.write_report_to_excel(main, _priced(), True)
    wd.write_withdrawal_report(
        book, picked(main, "P1", "FSR-209901-0002", "4"), False, main)
    wd.sync_item_lists(main)
    master, withdrawn = lists(tmp_path)
    assert sheet_rows(master)[1][7:9] == ("USD 5.00", "USD 30.00")
    assert sheet_rows(withdrawn)[1][7:9] == ("USD 5.00", "USD 20.00")


def _priced():
    data = rec("FSR-209901-0001", date(2026, 10, 1), "", 10, po="P1")
    data["item_lists"][0]["rows"][0].update(
        {"Unit Price": "5.00", "Total Price": "50.00", "Currency": "USD"})
    return data


# ---------- ownership and control numbers ----------

def this_month(number):
    return f"FSR-XX-{datetime.now():%Y%m}-{number:04d}"


def test_control_numbers_are_unique_across_both_workbooks(tmp_path):
    main, book = books(tmp_path)
    assert s.generate_control_number(main) == this_month(1)
    wd.write_withdrawal_report(
        book, linked_report(tmp_path, this_month(1)), False, main)
    assert s.generate_control_number(main) == this_month(2)

    s.write_report_to_excel(main, rec(this_month(2), date(2026, 1, 1), "C", 5),
                            False)
    assert s.generate_control_number(main) == this_month(3)


def test_new_main_report_with_a_withdrawal_number_gets_the_next(tmp_path):
    main, book = books(tmp_path)
    wd.write_withdrawal_report(
        book, linked_report(tmp_path, this_month(1)), False, main)
    result = s.write_report_to_excel(
        main, rec(this_month(1), date(2026, 1, 1), "C", 5), False)
    assert result["control"] == this_month(2)
    assert s.read_report(main, this_month(2))
    assert wd.owns_report(main, this_month(1))
    assert not wd.owns_report(main, this_month(2))


def test_new_withdrawal_with_a_main_number_gets_the_next(tmp_path):
    main, book = books(tmp_path)
    s.write_report_to_excel(main, rec(this_month(1), date(2026, 1, 1), "C", 5),
                            False)
    before = sha(main)
    result = wd.write_withdrawal_report(
        book, linked_report(tmp_path, this_month(1)), False, main)
    assert result["control"] == this_month(2)
    assert sha(main) == before


def test_an_edit_can_never_land_in_the_other_workbook(tmp_path):
    main, book = books(tmp_path)
    wd.write_withdrawal_report(
        book, linked_report(tmp_path, this_month(1)), False, main)
    with pytest.raises(ValueError, match="Withdrawal workbook"):
        s.write_report_to_excel(
            main, rec(this_month(1), date(2026, 1, 1), "C", 5), True)
    assert not main.exists()

    s.write_report_to_excel(main, rec(this_month(2), date(2026, 1, 1), "C", 5),
                            False)
    with pytest.raises(wd.WithdrawalError, match="main workbook"):
        wd.write_withdrawal_report(
            book, linked_report(tmp_path, this_month(2)), True, main)


def phone_file(control):
    data = report(control, "Withdrawal", date(2026, 10, 5),
                  lines=[{"cargo": "", "qty": 1, "po": "n/a"}])
    data["last_saved"] = "2026-10-05T08:00:00"
    return {"format": fsr_import.FORMAT, "version": 1, "device_id": "PHONE-1",
            "reports": [data]}


def test_phone_import_never_reuses_a_withdrawal_number(tmp_path):
    main, book = books(tmp_path)
    wd.write_withdrawal_report(
        book, linked_report(tmp_path, this_month(1)), False, main)
    before = sha(book)
    summary = fsr_import.import_master_data(main, phone_file(this_month(1)))
    assert summary["renumbered"] == [(this_month(1), this_month(2))]
    assert sha(book) == before
    assert [r[0] for r in s.list_saved_reports(main)] == [this_month(2)]


@pytest.mark.parametrize("placeholder", ["n/a", "Consolidated"])
def test_legacy_withdrawal_with_placeholder_po_stays_in_main(tmp_path, placeholder):
    main, book = books(tmp_path)
    data = wdr("OLD-2601-ABC", date(2026, 1, 5), "", 2)
    data["documents_used"]["po_number"] = placeholder
    fsr_import.import_master_data(main, {
        "format": fsr_import.FORMAT, "version": 1, "device_id": "legacy",
        "reports": [dict(data, last_saved="x")]})
    assert not book.exists()
    assert s.read_report(main, "OLD-2601-ABC")["documents_used"]["po_number"] \
        == placeholder


# ---------- paths ----------

def test_withdrawal_workbook_is_beside_the_active_workbook(tmp_path):
    active = tmp_path / "some" / "Custom.xlsx"
    assert fsr_paths.withdrawal_workbook_path(active) == \
        active.resolve().with_name("Withdrawal_Reports.xlsx")


def test_withdrawal_workbook_cannot_be_the_main_workbook(tmp_path):
    with pytest.raises(ValueError, match="main Excel file"):
        fsr_paths.withdrawal_workbook_path(tmp_path / "Withdrawal_Reports.xlsx")


def test_demo_folder_is_enforced(tmp_path):
    demo = tmp_path / "excel" / "demo_data"
    assert fsr_paths.withdrawal_workbook_path(
        demo / "Field_Survey_Reports_DEMO.xlsx", demo).parent == demo.resolve()
    with pytest.raises(ValueError, match="outside"):
        fsr_paths.withdrawal_workbook_path(tmp_path / "excel" / MAIN, demo)


# ---------- warehouse stock ----------

def stock_item(main):
    return store.load_snapshot(main, as_of=date(2026, 10, 29)).inventory.items[0]


def linked_with_cargo(tmp_path, control, quantity, warehouse="WH-1", cargo="C1"):
    data = linked_report(tmp_path, control, quantities=[quantity])
    data["general_information"]["location"] = warehouse
    data["item_lists"][0]["rows"][0]["Cargo ID"] = cargo
    data["item_lists"][0]["rows"][0]["Receiving Ref"] = ""
    data["item_lists"][0]["rows"][0]["UOM"] = "pcs"
    return data


def test_stock_before_and_after_a_po_linked_withdrawal(tmp_path):
    main, book = books(tmp_path)
    s.write_report_to_excel(
        main, rec("FSR-209901-0001", date(2026, 10, 1), "C1", 100), True)
    assert stock_item(main).remaining_qty == 100    # no Withdrawal workbook yet

    wd.write_withdrawal_report(
        book, linked_with_cargo(tmp_path, "FSR-209901-0002", "40"), False, main)
    item = stock_item(main)
    assert (item.received_qty, item.withdrawn_qty, item.remaining_qty) == \
        (100, 40, 60)


def test_picked_line_reduces_the_batch_it_came_from(tmp_path):
    main, book = books(tmp_path)
    s.write_report_to_excel(
        main, rec("FSR-209901-0001", date(2026, 10, 1), "", 100, po="P1"), True)
    rows = []
    add_line(rows, wd.find_po(main, "P1").lines[0])
    wd.set_quantity(rows[0], Decimal("40"))
    data = report("FSR-209901-0002", "Withdrawal", date(2026, 10, 5))
    data["item_lists"] = [{"name": "Item List 1", "rows": rows}]
    wd.write_withdrawal_report(book, data, False, main)
    item = stock_item(main)
    assert (item.received_qty, item.withdrawn_qty, item.remaining_qty) == \
        (100, 40, 60)


def test_manual_and_po_linked_withdrawals_add_up_once_each(tmp_path):
    main, book = books(tmp_path)
    s.write_report_to_excel(
        main, rec("FSR-209901-0001", date(2026, 10, 1), "C1", 100), True)
    s.write_report_to_excel(
        main, wdr("FSR-209901-0002", date(2026, 10, 2), "C1", 10), True)
    wd.write_withdrawal_report(
        book, linked_with_cargo(tmp_path, "FSR-209901-0003", "40"), False, main)
    assert stock_item(main).remaining_qty == 50


def test_a_report_in_both_workbooks_is_counted_once(tmp_path):
    main, book = books(tmp_path)
    s.write_report_to_excel(
        main, rec("FSR-209901-0001", date(2026, 10, 1), "C1", 100), True)
    wd.write_withdrawal_report(
        book, linked_with_cargo(tmp_path, "FSR-209901-0002", "40"), False, main)
    # bypass the guards, as a hand-edited file could
    merged = store.merge_withdrawal_reports(
        [wdr("FSR-209901-0002", date(2026, 10, 3), "C1", 40)],
        wd.read_all_reports(book))
    assert [r["control_no"] for r in merged] == ["FSR-209901-0002"]
    assert merged[0]["entry_source"] == wd.ENTRY_PO_LINKED


def test_existing_stock_rules_still_decide_what_is_deducted(tmp_path):
    """No Cargo ID / Receiving Ref, or another warehouse: nothing is deducted
    and the line goes to reconciliation, as for any other Withdrawal."""
    main, book = books(tmp_path)
    s.write_report_to_excel(
        main, rec("FSR-209901-0001", date(2026, 10, 1), "C1", 100), True)
    wd.write_withdrawal_report(
        book, linked_with_cargo(tmp_path, "FSR-209901-0002", "40", cargo=""),
        False, main)
    wd.write_withdrawal_report(
        book, linked_with_cargo(tmp_path, "FSR-209901-0003", "5",
                                warehouse="WH-2"), False, main)
    snapshot = store.load_snapshot(main, as_of=date(2026, 10, 29))
    assert snapshot.inventory.items[0].remaining_qty == 100
    assert {u.line.control_no for u in snapshot.inventory.unmatched} == \
        {"FSR-209901-0002", "FSR-209901-0003"}


def test_reading_stock_changes_neither_workbook(tmp_path):
    main, book = books(tmp_path)
    s.write_report_to_excel(
        main, rec("FSR-209901-0001", date(2026, 10, 1), "C1", 100), True)
    wd.write_withdrawal_report(
        book, linked_with_cargo(tmp_path, "FSR-209901-0002", "40"), False, main)
    before = sha(main), sha(book)
    stock_item(main)
    assert (sha(main), sha(book)) == before


def test_missing_or_empty_withdrawal_workbook_is_fine(tmp_path):
    main, book = books(tmp_path)
    assert wd.read_all_reports(book) == []
    assert store.load_reports(main) == []

    wb = Workbook()
    wb.remove(wb.active)
    for name, (_, headers) in wd.WITHDRAWAL_SHEETS.items():
        wb.create_sheet(name).append(headers)
    wb.save(book)
    assert wd.read_all_reports(book) == []
    assert wd.list_reports(book) == []
    assert s.generate_control_number(main) == this_month(1)


def test_mysql_source_is_not_merged_with_the_workbook(tmp_path, monkeypatch):
    """MySQL already holds its copy: reading it must not add the Excel one."""
    main, book = books(tmp_path)
    wd.write_withdrawal_report(
        book, linked_with_cargo(tmp_path, "FSR-209901-0002", "40"), False, main)
    mirrored = wd.read_report(book, "FSR-209901-0002")
    monkeypatch.setattr(db_mysql, "load_all_reports", lambda: [mirrored])
    assert store.load_reports(main, "mysql") == [mirrored]


# ---------- MySQL ----------

def test_mysql_gets_the_withdrawal_quantity_in_existing_columns(tmp_path):
    main, book = books(tmp_path)
    data = linked_report(tmp_path, quantities=["40"])
    wd.write_withdrawal_report(book, data, False, main)
    conn = FakeConnection(BASE)
    db_mysql.save_report(data, conn)
    assert conn.committed
    sql, params = item_inserts(conn)[0]
    columns = sql[sql.index("(") + 1:sql.index(")")].replace(" ", "").split(",")
    values = dict(zip(columns, params))
    assert values["quantity"] in ("40", 40)
    assert values["po_number"] == "4500001"
    assert not any("PO Line" in text or "original" in text.lower()
                   for text in columns)
    # no schema change is made by saving
    assert not any(sql.startswith(("ALTER", "CREATE", "DROP"))
                   for sql, _ in conn.statements)
